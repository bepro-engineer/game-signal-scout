"""ページの骨組み（HTML）。本文は画面の部品（static/*.js）が接続口から読んで描く。"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse

from game_signal_scout.web import pages

router = APIRouter()


def _page(name: str):
    def show_page():
        return HTMLResponse(pages.page_html(name))
    show_page.__name__ = f"show_{name}_page"
    return show_page


for _name in pages.PAGES:
    router.add_api_route("/" if _name == "index" else f"/{_name}.html", _page(_name), methods=["GET"])
router.add_api_route("/index.html", _page("index"), methods=["GET"])


@router.get("/robots.txt")
def show_robots():
    """クローラーへの決まり（利用規約・データ利用ポリシーと同じ。検索エンジンは許可、AI の学習用のクローラーは断る）。robots.txt はドメインの直下でしか読まれない（#65）。"""
    return FileResponse(pages.STATIC / "robots.txt", media_type="text/plain; charset=utf-8")
