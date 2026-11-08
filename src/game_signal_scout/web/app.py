"""Viewer（FastAPI。Anime の web/app・web/routers を Game に必要な分だけ移植）。

- Controller = このファイルのルート。Model = web/public_content と repositories/public_document（読む側）。View = web/templates と web/static。
- 表 public_document を鍵で 1 行読むだけ（内容は publication/publishing が分析の表から作り、検査に通ったものだけを置いておく）。
  Anime と同じく、Viewer の接続に要るのは public_document と public_build を読む権限だけ。
- Anime と違い、画面は JavaScript で描かず、文書からサーバー側で HTML にする（Anime の static/*.js はアニメの画面ごとの描き方で、
  Game の 2 つの画面には使えないため）。文書そのものは /api/… で JSON のまま返す（Anime と同じ）。
- 接続は psycopg_pool の溜めから借りる。溜めの接続は開くときに Game の DB であることを確かめる（db.verify_identity）。
- 待ち受けは既定で自分の機械だけ（config/daily.toml [web]）。外への公開はしていない。
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import psycopg
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape
from psycopg_pool import PoolTimeout

from game_signal_scout import config, db
from game_signal_scout.web import public_content

WEB = Path(__file__).resolve().parent
SECURITY_HEADERS = {"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer",
                    "Cross-Origin-Opener-Policy": "same-origin"}
CSP_HTML = ("default-src 'none'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; base-uri 'none'; form-action 'none'; "
            "frame-ancestors 'none'")
CSP_OTHER = "default-src 'none'; frame-ancestors 'none'; sandbox"

_ENV = Environment(loader=FileSystemLoader(str(WEB / "templates")), autoescape=select_autoescape(["html"]))
_ENV.filters["pct"] = lambda x: f"{x * 100:.0f}%"
_ENV.filters["day"] = lambda s: s[:10] if s else "—"
_ENV.filters["ts"] = lambda s: f"{s[:10]} {s[11:16]} UTC" if s else "—"
_ENV.filters["md"] = lambda s: f"{int(s[5:7])}月{int(s[8:10])}日" if s else "—"


def open_pool(cfg: dict):
    from psycopg_pool import ConnectionPool
    w = cfg["web"]
    return ConnectionPool(config.db_dsn(), min_size=int(w["pool_min_size"]), max_size=int(w["pool_max_size"]),
                          kwargs={"autocommit": True}, configure=db.verify_identity, open=True)


def create_app(cfg: dict | None = None, pool=None) -> FastAPI:
    """pool を渡せば、それを使う（試験）。渡さなければ起動のときに開き、終わるときに閉じる。"""
    cfg = cfg or config.load_daily_config()

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

    @app.exception_handler(public_content.NotPublishedError)
    async def not_published(request: Request, exc: Exception):
        return JSONResponse({"detail": "ない"}, status_code=404)

    def read(request: Request, fn, *args):
        with request.app.state.pool.connection() as conn:
            return fn(conn, *args), public_content.get_health(conn)

    def page(name: str, **ctx) -> HTMLResponse:
        return HTMLResponse(_ENV.get_template(name).render(**ctx))

    @app.get("/", response_class=HTMLResponse)
    def show_overview(request: Request):
        text, health = read(request, public_content.get_overview)
        return page("index.html", v=public_content.load(text), health=health, nav="top")

    @app.get("/about", response_class=HTMLResponse)
    def show_about(request: Request):
        text, health = read(request, public_content.get_overview)
        return page("about.html", v=public_content.load(text), health=health, nav="about")

    @app.get("/games/{appid}", response_class=HTMLResponse)
    def show_game(appid: str, request: Request):
        text, health = read(request, public_content.get_game, appid)
        return page("game.html", g=public_content.load(text), health=health, nav="game")

    @app.get("/api/overview")
    def get_overview(request: Request):
        return Response(read(request, public_content.get_overview)[0], media_type="application/json")

    @app.get("/api/games/{appid}")
    def get_game(appid: str, request: Request):
        return Response(read(request, public_content.get_game, appid)[0], media_type="application/json")

    @app.get("/healthz")
    def get_health(request: Request):
        with request.app.state.pool.connection() as conn:
            h = public_content.get_health(conn)
        return JSONResponse(h, status_code=200 if h["ok"] else 503)

    return app
