"""ページの骨組み（HTML）。本文は画面の部品（static/*.js）が接続口から読んで描く。"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse

from game_signal_scout.web import pages, plain

router = APIRouter()


def _page(name: str):
    def show_page(request: Request):
        summary = ""
        pool = getattr(request.app.state, "pool", None)
        if pool is not None and not pages.PAGES[name].info:
            with pool.connection() as conn:
                summary = plain.block(conn, name, request.query_params.get("id"))
        return HTMLResponse(pages.page_html(name, summary))
    show_page.__name__ = f"show_{name}_page"
    return show_page


for _name in pages.PAGES:
    router.add_api_route("/" if _name == "index" else f"/{_name}.html", _page(_name), methods=["GET"])
router.add_api_route("/index.html", _page("index"), methods=["GET"])


@router.get("/revival.html")
def moved_revival_page():
    """「再燃」は「プレイヤーの発見」の「いま変わったこと」にまとめた（#2）。"""
    from fastapi.responses import RedirectResponse
    return RedirectResponse("finds.html?view=changed", status_code=308)


@router.get("/spread.html")
def moved_spread_page():
    """「世界で広がる作品」は「プレイヤーの発見」に置き換えた（#2）。古いリンクは新しいページへ。"""
    from fastapi.responses import RedirectResponse
    return RedirectResponse("finds.html", status_code=308)


def _moved_intent(key: str):
    def go():
        """遊びたい体験の入口のページ（2026-11-11 に一時置いた deep.html など）は、注目の作品の「どんな体験を探す？」の同じ選択へ（#2 の配置確定）。"""
        from fastapi.responses import RedirectResponse
        return RedirectResponse(f"finds.html?i={key}", status_code=308)
    return go


for _k in ("deep", "short", "novel", "friends"):
    router.add_api_route(f"/{_k}.html", _moved_intent(_k), methods=["GET"])


@router.get("/robots.txt")
def show_robots():
    """クローラーへの決まり（利用規約・データ利用ポリシーと同じ。検索エンジンは許可、AI の学習用のクローラーは断る）。robots.txt はドメインの直下でしか読まれない（#65）。"""
    # 途中の cache（Cloudflare）に長く残さない。決まりを変えたらすぐ届くように（2026-11-08: 4 時間古いまま残った）
    return FileResponse(pages.STATIC / "robots.txt", media_type="text/plain; charset=utf-8", headers={"Cache-Control": "public, max-age=300"})
