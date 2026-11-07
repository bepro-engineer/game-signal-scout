"""Viewer（FastAPI。Anime の web/app の形を Game に必要な分だけ移植）。

- Controller = このファイルのルート。Model = services/viewer と repositories。View = web/templates（Jinja2）と web/static。
- データの層を読むだけ。書かない。画面はサーバー側で HTML にする（JavaScript を持たない）。
- 接続は psycopg_pool の溜めから借りる。溜めの接続は開くときに Game の DB であることを確かめる（db.verify_identity）。
- 待ち受けは既定で自分の機械だけ（config/daily.toml [web]）。公開はしていない。
"""
from __future__ import annotations

import json
import re
from contextlib import asynccontextmanager
from pathlib import Path

import psycopg
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape
from psycopg_pool import PoolTimeout

from game_signal_scout import config, db
from game_signal_scout.ops.status import status
from game_signal_scout.services import viewer

WEB = Path(__file__).resolve().parent
SECURITY_HEADERS = {"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer",
                    "Cross-Origin-Opener-Policy": "same-origin"}
CSP_HTML = ("default-src 'none'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; base-uri 'none'; form-action 'none'; "
            "frame-ancestors 'none'")
CSP_OTHER = "default-src 'none'; frame-ancestors 'none'; sandbox"
APPID = re.compile(r"\d{1,10}")

_ENV = Environment(loader=FileSystemLoader(str(WEB / "templates")), autoescape=select_autoescape(["html"]))
_ENV.filters["pct"] = lambda x: f"{x * 100:.0f}%"
_ENV.filters["day"] = lambda d: d.strftime("%Y-%m-%d") if d else "—"
_ENV.filters["ts"] = lambda d: d.strftime("%Y-%m-%d %H:%M UTC") if d else "—"


def open_pool(cfg: dict):
    from psycopg_pool import ConnectionPool
    w = cfg["web"]
    return ConnectionPool(config.db_dsn(), min_size=int(w["pool_min_size"]), max_size=int(w["pool_max_size"]),
                          kwargs={"autocommit": True}, configure=db.verify_identity, open=True)


def render(name: str, **ctx) -> HTMLResponse:
    return HTMLResponse(_ENV.get_template(name).render(**ctx))


def create_app(cfg: dict | None = None, pool=None) -> FastAPI:
    """pool を渡せば、それを使う（試験）。渡さなければ起動のときに開き、終わるときに閉じる。"""
    cfg = cfg or config.load_daily_config()
    version = cfg["analysis"]["version"]

    @asynccontextmanager
    async def lifespan(app):
        own = pool is None
        app.state.pool = open_pool(cfg) if own else pool
        yield
        if own:
            app.state.pool.close()

    app = FastAPI(title="Game Signal Scout", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=str(WEB / "static")), name="static")

    @app.middleware("http")
    async def headers(request: Request, call_next):
        r: Response = await call_next(request)
        html = r.headers.get("content-type", "").startswith("text/html")
        r.headers.update(SECURITY_HEADERS)
        r.headers["Content-Security-Policy"] = CSP_HTML if html else CSP_OTHER
        if not request.url.path.startswith("/static/"):
            r.headers["Cache-Control"] = "no-store"
        return r

    @app.exception_handler(psycopg.OperationalError)
    @app.exception_handler(PoolTimeout)
    async def database_unavailable(request: Request, exc: Exception):
        return JSONResponse({"detail": "一時的に応答できない"}, status_code=503)

    @app.get("/", response_class=HTMLResponse)
    def show_overview(request: Request):
        with request.app.state.pool.connection() as conn:
            return render("index.html", v=viewer.overview(conn, version))

    @app.get("/games/{appid}", response_class=HTMLResponse)
    def show_game(appid: str, request: Request):
        if not APPID.fullmatch(appid):
            raise HTTPException(404)
        with request.app.state.pool.connection() as conn:
            g = viewer.game(conn, version, appid)
        if g is None:
            raise HTTPException(404)
        return render("game.html", g=g)

    @app.get("/api/status")
    def show_status(request: Request):
        """監視が読む状態（CLI の status と同じ）。"""
        with request.app.state.pool.connection() as conn:
            return JSONResponse(json.loads(json.dumps(status(conn), default=str)))

    return app
