"""公開の内容を読む Service（読む側）。公開用の文書（publication/publishing が書いた表 public_document）を鍵で 1 つ読むだけ。
内容を作らない・書かない。本文は表にある JSON の文字列のまま返す（読み込んで作り直さない）。"""
from __future__ import annotations

import re

from game_signal_scout.repositories import public_document as public_document_repo

DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
WORK = re.compile(r"w\d+")


class NotPublishedError(LookupError):
    """その文書は公開していない。"""


def _text(conn, path: str) -> str:
    text = public_document_repo.get_document_text(conn, path)
    if text is None:
        raise NotPublishedError(path)
    return text


def get_days(conn) -> str:
    return _text(conn, "days")


def get_day(conn, day: str) -> str:
    if not DAY.fullmatch(day):
        raise NotPublishedError(day)
    return _text(conn, f"day/{day}")


def get_pages(conn) -> str:
    return _text(conn, "pages")


def get_search(conn) -> str:
    return _text(conn, "search")


def get_soon(conn) -> str:
    return _text(conn, "soon")


def get_work(conn, work: str) -> str:
    if not WORK.fullmatch(work):
        raise NotPublishedError(work)
    return _text(conn, f"work/{work}")


def get_health(conn) -> dict:
    """公開の状態: 公開した内容があるか・最後に公開した時刻と最新の日・最後の作り直しが失敗して前の内容のままか（stale）。理由の文は返さない。"""
    last = public_document_repo.get_last_published_build(conn)
    tried = public_document_repo.get_last_finished_build(conn)
    return {"ok": last is not None, "built_at": last["finished_at"].isoformat() if last else None,
            "latest": str(last["latest_day"]) if last else None, "stale": bool(tried and tried["status"] != "published")}
