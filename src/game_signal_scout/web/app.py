"""処理の層のアプリ（FastAPI。ADR 0056）の組み立て。ページの骨組み（HTML）と、画面が読む接続口（/api/…）を返す。

- Controller = web/routers（api: 接続口、pages: ページの骨組み）。Model = Service（web/services/public_content）と Repository（repositories/public_document）。
  View = ページの骨組み（web/pages）と画面の部品（web/static）。
- データの層（PostgreSQL）を読むだけ。内容は書く側（publication/publishing）が表 public_document に置き換えておき、ここは鍵で 1 行を読んで返す。
  内容を作る・写しを持つ・版を見張ることはしない。
- 接続は psycopg_pool の溜めから要求ごとに借りる（大きさは config/daily.toml [web]）。
- 画面の部品（static/）は、本番では Apache が直接配る（docs/DEPLOY.md）。開発では、このアプリも配る（/static）。
- 安全のための見出し（CSP など）は、本番では Apache が付ける。開発でも同じ値を付ける（SECURITY_HEADERS・csp）。
"""
from __future__ import annotations

from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from psycopg_pool import PoolTimeout
from fastapi.staticfiles import StaticFiles

from game_signal_scout import catalog
from game_signal_scout.web import pages as page_views
from game_signal_scout.web.routers import api, pages

# 画面が読むもの: 自分の origin、Google Fonts、作品情報の提供元の画像。script は static/*.js と、配信の Cloudflare が差し込むアクセス解析の beacon だけ
# （inline の script は書かない。beacon の場所は config/daily.toml [web] analytics_script_src。送り先は自分の origin の /cdn-cgi/rum で connect-src 'self'。#66）。
# style は部品が inline の style= を使うので 'unsafe-inline'（守りの本体は escape と URL の検査）
SECURITY_HEADERS = {"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer",
                    "Cross-Origin-Opener-Policy": "same-origin"}


def csp(html: bool, analytics: str) -> str:
    if not html:
        return "default-src 'none'; frame-ancestors 'none'; sandbox"
    img = "https://*.steamstatic.com"   # 作品の画像（Steam の配信元。Game の作品情報 game_profile の URL）
    return (f"default-src 'self'; script-src 'self' {analytics}; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            f"font-src 'self' https://fonts.gstatic.com; img-src 'self' data: {img}; connect-src 'self'; object-src 'none'; base-uri 'none'; "
            "form-action 'none'; frame-ancestors 'none'").replace("  ", " ")


def open_pool(cfg: dict):
    """読むだけの接続の溜め（接続の設定は環境変数 ASS_DB_DSN。本番は役割 ass_viewer）。"""
    import os
    from psycopg_pool import ConnectionPool
    from game_signal_scout.config import db_dsn
    schema = os.environ.get("ASS_TEST_SCHEMA")   # 試験用の一時的な schema（tests/db_fixture.py）。本番では未設定
    kwargs = {"autocommit": True, **({"options": f"-c search_path={schema}"} if schema else {})}
    w = cfg["web"]
    from game_signal_scout import db
    return ConnectionPool(db_dsn(), min_size=int(w["pool_min_size"]), max_size=int(w["pool_max_size"]), kwargs=kwargs, configure=db.verify_identity, open=True)


def create_app(cfg: dict | None = None, serve_static: bool = True, pool=None) -> FastAPI:
    """pool を渡せば、それを使う（試験）。渡さなければ起動のときに開き、終わるときに閉じる。"""
    from game_signal_scout.config import load_daily_config
    cfg = cfg or load_daily_config()
    analytics = str(cfg["web"]["analytics_script_src"])

    @asynccontextmanager
    async def lifespan(app):
        own = pool is None
        app.state.pool = open_pool(cfg) if own else pool
        yield
        if own:
            app.state.pool.close()
    app = FastAPI(title="Game Signal Scout", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    if serve_static:
        app.mount("/static", StaticFiles(directory=str(page_views.STATIC)), name="static")

    # 受けてよい相手（Issue #6）: この機械自身と、公開の入口（VAIO の Apache。Cloudflare Tunnel の内側）だけ。
    # 公開の入口から届いた要求（X-Forwarded-For つき）には、稼働の確認の口を出さない（管理・運用の情報を外に出さない）
    allow = set((cfg["web"].get("allow_from") or ["127.0.0.1", "::1"]))

    @app.middleware("http")
    async def only_known_peers(request: Request, call_next):
        peer = request.client.host if request.client else ""
        if peer not in allow:
            return Response(status_code=403)
        if request.headers.get("x-forwarded-for") and request.url.path.startswith("/healthz"):
            return Response(status_code=404)
        return await call_next(request)

    @app.middleware("http")
    async def headers(request: Request, call_next):
        r: Response = await call_next(request)
        html = r.headers.get("content-type", "").startswith("text/html")
        for k, v in SECURITY_HEADERS.items():
            r.headers[k] = v
        r.headers["Content-Security-Policy"] = csp(html, analytics)
        if html or r.headers.get("content-type", "").startswith("application/json"):
            r.headers["Cache-Control"] = "no-store"
        return r

    @app.exception_handler(psycopg.OperationalError)
    @app.exception_handler(PoolTimeout)
    async def database_unavailable(request: Request, exc: Exception):
        # データベースに一時的に届かない（起動し直し・接続の溜めの待ち切れ）: 画面の部品は 503 を一時的とみなして自分で読み直す
        return JSONResponse({"detail": "一時的に応答できない"}, status_code=503)

    app.include_router(api.router)
    app.include_router(pages.router)
    return app

