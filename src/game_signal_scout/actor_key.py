"""投稿者の識別子を HMAC にする（生の識別子を保存しない。Anime の actor_key を移植）。

鍵は runtime/author_hmac.key（32 バイト・600・Git の外）。なければ止まる: 黙って新しい鍵を作ると、投稿者の同一性が過去の記録と合わなくなる。
初回だけ `python -m game_signal_scout init-author-key` で作る（あれば作らない）。
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets

from game_signal_scout import config

KEY_FILE = "author_hmac.key"


def load_key() -> bytes:
    p = config.RUNTIME / KEY_FILE
    if not p.exists():
        raise RuntimeError(f"投稿者の識別子の鍵がない: {p}（新しく作らない。退避から戻すか、初回なら init-author-key で作る）")
    return p.read_bytes()


def create_key() -> bool:
    """鍵がなければ作る（作ったら True）。あれば何もしない。"""
    p = config.RUNTIME / KEY_FILE
    if p.exists():
        return False
    p.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(secrets.token_bytes(32))
    return True


def author_hash(actor: str) -> str:
    """投稿者の参照（識別子の HMAC の先頭 20 桁）。"""
    return hmac.new(load_key(), actor.encode(), hashlib.sha256).hexdigest()[:20]
