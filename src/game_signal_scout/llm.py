"""推論エンジン（LLM の対話・意味表現）の境界（Port と Adapter。ADR 0054）。

業務の処理は chat / embed / model_digest だけを呼び、HTTP・応答の形・接続先・エンジンの名前を知らない。
すべての要求は機械で 1 つの LLM 枠（llm_gate。ADR 0062）を通る。接続先は config/providers.toml [ollama]（1 か所。環境変数 GSS_OLLAMA_URL で上書き）。エンジンを替えるときは _ENGINES に 1 つ足し、設定の engine で選ぶ。
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from dataclasses import dataclass
from functools import lru_cache

from game_signal_scout import llm_gate


@dataclass(frozen=True)
class ChatResult:
    content: str                     # モデルの返答（文字列。JSON を求めたときも文字列。json() で読む）
    seconds: float
    prompt_tokens: int | None = None
    output_tokens: int | None = None

    def json(self, default=None):
        """返答を JSON として読む。読めなければ default（None なら ValueError）。"""
        try:
            return json.loads(self.content)
        except ValueError:
            if default is None:
                raise
            return default


@lru_cache(maxsize=1)
def settings() -> dict:
    from game_signal_scout import config
    s = dict(config.load_toml("providers.toml").get("ollama") or {})
    if not s.get("base_url"):
        raise KeyError("config/providers.toml [ollama] base_url がない")
    if os.environ.get("GSS_OLLAMA_URL"):
        s["base_url"] = os.environ["GSS_OLLAMA_URL"]
    s["base_url"] = s["base_url"].rstrip("/")
    s.setdefault("engine", "ollama")
    s.setdefault("timeout_seconds", 180)
    return s


def chat(model: str, system: str, user: str, *, format=None, options: dict | None = None, timeout: float | None = None,
         keep_alive: str | None = None, think: bool | None = None) -> ChatResult:
    """1 回の対話（system と user の 2 つの文）。format = None / "json" / JSON schema。options は温度・seed・文脈の長さなど。"""
    s = settings()
    with llm_gate.request(model):
        return _ENGINES[s["engine"]]["chat"](s, model, system, user, format, options or {}, float(timeout or s["timeout_seconds"]), keep_alive, think)


def embed(model: str, texts: list[str], *, max_chars: int | None = None, timeout: float | None = None, keep_alive: str | None = None) -> list[list[float]]:
    """文の一覧 → ベクトルの一覧（正規化はしない。呼ぶ側の用途ごと）。"""
    s = settings()
    if not texts:
        return []
    with llm_gate.request(model):
        return _ENGINES[s["engine"]]["embed"](s, model, [t[:max_chars] if max_chars else t for t in texts], float(timeout or s["timeout_seconds"]), keep_alive)


def loaded() -> list[str]:
    """いまメモリに載っているモデルの名前（取れなければ空）。"""
    s = settings()
    return _ENGINES[s["engine"]]["loaded"](s)


def release(model: str) -> None:
    """載っているモデルをすぐに外す（保持の時間を待たない。使っている途中なら、その要求が終わってから外れる）。"""
    s = settings()
    _ENGINES[s["engine"]]["release"](s, model)


def model_digest(model: str) -> str | None:
    """モデルの中身の識別子（入れ替えの検知。取れなければ None）。"""
    s = settings()
    return _ENGINES[s["engine"]]["digest"](s, model)


# ---------------------------------------------------------------- Ollama（Adapter）
def _ollama_post(s: dict, path: str, body: dict, timeout: float) -> dict:
    req = urllib.request.Request(f"{s['base_url']}{path}", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _ollama_chat(s, model, system, user, format, options, timeout, keep_alive, think) -> ChatResult:
    body = {"model": model, "stream": False, "options": options,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    if format is not None:
        body["format"] = format
    if keep_alive is not None:
        body["keep_alive"] = keep_alive
    if think is not None:
        body["think"] = think
    t0 = time.perf_counter()
    res = _ollama_post(s, "/api/chat", body, timeout)
    return ChatResult(((res.get("message") or {}).get("content") or "").strip(), time.perf_counter() - t0,
                      res.get("prompt_eval_count"), res.get("eval_count"))


def _ollama_embed(s, model, texts, timeout, keep_alive) -> list[list[float]]:
    body = {"model": model, "input": texts, "truncate": True}
    if keep_alive is not None:
        body["keep_alive"] = keep_alive
    return _ollama_post(s, "/api/embed", body, timeout)["embeddings"]


def _ollama_digest(s, model) -> str | None:
    try:
        with urllib.request.urlopen(f"{s['base_url']}/api/tags", timeout=10) as r:
            for m in json.load(r).get("models", []):
                if m.get("name") == model:
                    return (m.get("digest") or "")[:12] or None
    except Exception:  # noqa: BLE001 — 止まっていれば識別子なし
        pass
    return None


def _ollama_loaded(s) -> list[str]:
    try:
        with urllib.request.urlopen(f"{s['base_url']}/api/ps", timeout=10) as r:
            return [m.get("name") for m in json.load(r).get("models", []) if m.get("name")]
    except Exception:  # noqa: BLE001 — 止まっていれば載っているものはない
        return []


def _ollama_release(s, model) -> None:
    _ollama_post(s, "/api/generate", {"model": model, "keep_alive": 0}, 30)


_ENGINES = {"ollama": {"chat": _ollama_chat, "embed": _ollama_embed, "digest": _ollama_digest, "loaded": _ollama_loaded, "release": _ollama_release}}
