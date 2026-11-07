"""公開用の文書（public_document）と、作った回の記録（public_build）。書くのは publication/publishing、読むのは Viewer（web）。
Anime の repositories/public_document をそのまま移植。"""
from __future__ import annotations

import json
from datetime import date, datetime

from psycopg.types.json import Json


# ---------------------------------------------------------------- public_build
def create_build(conn, input_version: str, trigger: str, started_at: datetime) -> int:
    return conn.execute("INSERT INTO public_build (input_version, trigger, status, started_at) VALUES (%s, %s, 'running', %s) RETURNING build_id",
                        (input_version, trigger, started_at)).fetchone()[0]


def finish_build(conn, build_id: int, status: str, finished_at: datetime, latest_day: date | None = None, documents: int | None = None,
                 detail: dict | None = None) -> None:
    conn.execute("UPDATE public_build SET status=%s, finished_at=%s, latest_day=%s, documents=%s, detail=%s WHERE build_id=%s",
                 (status, finished_at, latest_day, documents, Json(detail or {}), build_id))


def get_last_published_build(conn) -> dict | None:
    """最後に公開した回 {build_id, input_version, latest_day, documents, finished_at}。まだなければ None。"""
    r = conn.execute("SELECT build_id, input_version, latest_day, documents, finished_at FROM public_build WHERE status='published' "
                     "ORDER BY finished_at DESC LIMIT 1").fetchone()
    return dict(zip(("build_id", "input_version", "latest_day", "documents", "finished_at"), r)) if r else None


def get_last_finished_build(conn) -> dict | None:
    """最後に終わった回（公開・検査に通らない・作れないのどれでも）{build_id, input_version, status, finished_at}。"""
    r = conn.execute("SELECT build_id, input_version, status, finished_at FROM public_build WHERE status <> 'running' "
                     "ORDER BY finished_at DESC LIMIT 1").fetchone()
    return dict(zip(("build_id", "input_version", "status", "finished_at"), r)) if r else None


# ---------------------------------------------------------------- public_document
def replace_documents(conn, build_id: int, documents: dict[str, object], published_at: datetime) -> None:
    """公開用の文書をすべて置き換える（この回にない鍵は消す）。1 つの取引の中で呼ぶので、読む側は前の回か今回のどちらか一方だけを見る。"""
    with conn.cursor() as cur:
        cur.executemany("INSERT INTO public_document (path, body, build_id, published_at) VALUES (%s, %s::json, %s, %s) "
                        "ON CONFLICT (path) DO UPDATE SET body = EXCLUDED.body, build_id = EXCLUDED.build_id, published_at = EXCLUDED.published_at",
                        [(path, json.dumps(body, ensure_ascii=False, separators=(",", ":")), build_id, published_at) for path, body in documents.items()])
    conn.execute("DELETE FROM public_document WHERE build_id <> %s", (build_id,))


def get_document_text(conn, path: str) -> str | None:
    """公開用の文書の本文（JSON の文字列のまま）。なければ None。"""
    r = conn.execute("SELECT body::text FROM public_document WHERE path = %s", (path,)).fetchone()
    return r[0] if r else None


def get_document(conn, path: str):
    """公開用の文書（読み込んだ値）。なければ None。"""
    text = get_document_text(conn, path)
    return json.loads(text) if text is not None else None
