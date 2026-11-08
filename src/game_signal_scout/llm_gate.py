"""機械で 1 つの LLM 枠の Adapter（Port は llm.py。部品は別の Repo の scout_llm_gate。ADR 0062・Issue #69）。

業務の処理は hold / Turns / request だけを使い、枠の仕組みを知らない。[llm_gate] enabled = false（既定）のときは何もしない。
枠の解放と推論の終了は別のこと: 応答を受け取れなかった要求があれば、この保持の返却は「未確認」のまま残り、次の利用者が確かめる。
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from functools import lru_cache


class GateUnavailableError(TimeoutError):
    """枠を取れなかった（要求は出していない）。TimeoutError（OSError）なので、呼ぶ側の一時的な失敗の扱いに乗る。"""


_flight = threading.Lock()   # 実行中の要求の数と、区切りで譲る判断を同時に動かさない
_inflight = 0
_auto_yield = True


@lru_cache(maxsize=1)
def settings() -> dict:
    from game_signal_scout import config
    return dict(config.load_toml("providers.toml").get("llm_gate") or {})


def enabled() -> bool:
    return bool(settings().get("enabled"))


@lru_cache(maxsize=1)
def _load():
    from scout_llm_gate import Gate, load_config   # 旗を入れた機械（Mac mini）にだけ入っている部品
    return Gate(load_config(settings()["config"]))


def _gate():
    """旗がオンなのに部品や設定を読めないときは、枠なしで推論を始めない（一時的な失敗として返す）。"""
    try:
        return _load()
    except (ImportError, OSError, KeyError, ValueError) as e:
        raise GateUnavailableError(f"LLM 枠の部品か設定を読めない: {type(e).__name__}: {e}"[:300]) from e


def _acquire(g, name: str, wait: float | None, stop) -> None:
    from scout_llm_gate import GateError
    try:
        g.acquire(name, wait, stop)
    except GateError as e:
        raise GateUnavailableError(str(e)) from e


@contextmanager
def hold(name: str, wait: float | None = None, stop=None, auto_yield: bool = True):
    """処理のまとまりの間、枠を持つ。auto_yield: 1 つずつ要求する処理は、要求の区切りで待つ人に譲る（単独なら手放さない）。"""
    global _auto_yield
    if not enabled():
        yield
        return
    g = _gate()
    _acquire(g, name, wait, stop)
    prev, _auto_yield = _auto_yield, auto_yield
    try:
        yield
    finally:
        _auto_yield = prev
        g.release()


class Turns:
    """仕事を取る前に枠を持ち、束の区切りで譲る（Observation の分類。貸し出しを待ちで消費しない）。旗がオフなら何もしない。"""

    def __init__(self, name: str, wait: float | None = None, stop=None):
        self.name, self.wait, self.stop, self.on, self.holding = name, wait, stop, enabled(), False

    def ensure(self) -> None:
        global _auto_yield
        if self.on and not self.holding:
            g = _gate()
            _acquire(g, self.name, self.wait, self.stop)
            self.holding, self.prev, _auto_yield = True, _auto_yield, False   # 3 並列の要求の途中では譲らない

    def between(self) -> None:
        """束の間（実行中の要求なし）。待つ人がいて持ち時間を過ぎていれば譲り、順番が来たら戻る。"""
        if self.holding:
            from scout_llm_gate import GateError
            g = _gate()
            try:
                g.yield_turn(self.wait, self.stop)
            except GateError as e:
                self.close()
                raise GateUnavailableError(str(e)) from e

    def close(self) -> None:
        global _auto_yield
        if self.holding:
            self.holding, _auto_yield = False, self.prev
            _gate().release()


@contextmanager
def request(model: str):
    """1 回の要求（llm.py だけが使う）。保持していなければ、この要求の間だけ枠を持つので、どの経路も枠を素通りしない。"""
    global _inflight
    if not enabled():
        yield
        return
    from scout_llm_gate import GateError
    g = _gate()
    _acquire(g, str(settings().get("owner", "anime")), None, None)
    try:
        with _flight:
            try:
                if _auto_yield and _inflight == 0:
                    g.yield_turn()
                g.prepare_model(model)
            except GateError as e:
                raise GateUnavailableError(str(e)) from e
            _inflight += 1
        try:
            yield
            g.progress()
        except BaseException:
            g.mark_uncertain()   # 応答を受け取れなかった = 推論が残っているかもしれない
            raise
        finally:
            with _flight:
                _inflight -= 1
    finally:
        g.release()


def status() -> dict | None:
    """指標用の現在の状態（読むだけ）。旗がオフなら None。固着の判定・復旧・通知は部品の監視（scout-llm check。#69 の F7）が持つ。"""
    if not enabled():
        return None
    from scout_llm_gate import load_config, status as st
    return st(load_config(settings()["config"]))
