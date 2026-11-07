"""公開の内容を読む Service（読む側。Anime の web/services/public_content を移植）。表 public_document を鍵で 1 つ読むだけ。
内容を作らない・書かない。"""
from __future__ import annotations

import json
import re

from game_signal_scout.repositories import public_document as public_document_repo

APPID = re.compile(r"\d{1,10}")


class NotPublishedError(LookupError):
    """その文書はない。"""


def _text(conn, path: str) -> str:
    text = public_document_repo.get_document_text(conn, path)
    if text is None:
        raise NotPublishedError(path)
    return text


def get_overview(conn) -> str:
    return _text(conn, "overview")


def get_game(conn, appid: str) -> str:
    if not APPID.fullmatch(appid):
        raise NotPublishedError(appid)
    return _text(conn, f"game/{appid}")


def load(text: str) -> dict:
    return json.loads(text)


def get_health(conn) -> dict:
    """文書の状態: 文書があるか・最後に作った時刻と最新の報告の日・最後の作り直しが失敗して前の内容のままか（stale）。理由の文は返さない。"""
    last = public_document_repo.get_last_published_build(conn)
    tried = public_document_repo.get_last_finished_build(conn)
    return {"ok": last is not None, "built_at": last["finished_at"].isoformat() if last else None,
            "latest": str(last["latest_day"]) if last and last["latest_day"] else None, "stale": bool(tried and tried["status"] != "published")}
