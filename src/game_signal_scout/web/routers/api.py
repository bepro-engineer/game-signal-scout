"""画面が読む接続口（/api/…・/healthz）。Service（web/services/public_content）を呼んで、表にある JSON をそのまま返す。"""
from __future__ import annotations

from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from game_signal_scout.web.services import public_content

router = APIRouter()


def connection(request: Request) -> Iterator:
    """要求ごとに接続の溜めから 1 本借りる（読むだけ。autocommit）。"""
    with request.app.state.pool.connection() as conn:
        yield conn


def _json(read) -> Response:
    try:
        return Response(read(), media_type="application/json")
    except public_content.NotPublishedError:
        raise HTTPException(404, "公開していない") from None


@router.get("/api/days")
def get_days(conn=Depends(connection)):
    return _json(lambda: public_content.get_days(conn))


@router.get("/api/days/{day}")
def get_day(day: str, conn=Depends(connection)):
    return _json(lambda: public_content.get_day(conn, day))


@router.get("/api/pages")
def get_pages(conn=Depends(connection)):
    return _json(lambda: public_content.get_pages(conn))


@router.get("/api/search")
def get_search(conn=Depends(connection)):
    return _json(lambda: public_content.get_search(conn))


@router.get("/api/soon")
def get_soon(conn=Depends(connection)):
    return _json(lambda: public_content.get_soon(conn))


@router.get("/api/works/{work}")
def get_work(work: str, conn=Depends(connection)):
    return _json(lambda: public_content.get_work(conn, work))


@router.get("/healthz")
def get_health(conn=Depends(connection)):
    h = public_content.get_health(conn)
    return JSONResponse(h, status_code=200 if h["ok"] else 503)
