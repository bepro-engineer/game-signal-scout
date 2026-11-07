"""機械で 1 つの LLM 枠への接続口（部品は共有の scout-infra の scout_llm_gate。Game は専用の LLM・ロック・常駐を持たない）。

今の Game の処理は LLM を使わない。LLM を使う処理を足すときは、Ollama へ要求を出す前に必ず hold() を通す（直接の呼び出しを足さない）。
順序は DB のロック → 枠（scout-infra の規則）。[llm_gate] enabled = false のときは何もしない。
"""
from __future__ import annotations

from contextlib import contextmanager


class GateUnavailableError(TimeoutError):
    """枠を取れなかった（要求は出していない）。TimeoutError なので一時的な失敗として扱われる。"""


_GATE = None


def _settings() -> dict:
    from game_signal_scout import config
    return dict(config.load_daily_config().get("llm_gate") or {})


def gate():
    """1 プロセスに 1 つの枠。部品か設定を読めなければ、枠なしで推論を始めない。"""
    global _GATE
    if _GATE is None:
        try:
            from scout_llm_gate import Gate, load_config
            _GATE = Gate(load_config(_settings()["config"]))
        except (ImportError, OSError, KeyError, ValueError) as e:
            raise GateUnavailableError(f"LLM 枠の部品か設定を読めない: {type(e).__name__}: {e}"[:300]) from e
    return _GATE


@contextmanager
def hold(owner: str, wait: float | None = None, stop=None):
    if not _settings().get("enabled"):
        yield None
        return
    g = gate()
    try:
        from scout_llm_gate import GateError
        g.acquire(f"game:{owner}", wait, stop)
    except GateError as e:
        raise GateUnavailableError(str(e)) from e
    try:
        yield g
    finally:
        g.release()
