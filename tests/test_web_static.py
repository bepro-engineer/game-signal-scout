"""画面の静的なファイル（DB なし）: 指定のヘッダー画像（Issue #2）と画面の部品が配られること。"""
from fastapi.testclient import TestClient

from game_signal_scout.web.app import create_app


def test_header_image_and_assets_are_served():
    with TestClient(create_app(cfg={"web": {}}, pool=object())) as c:
        for path, kind in (("/static/banner.jpg", "image/jpeg"), ("/static/banner-1240.jpg", "image/jpeg"), ("/static/banner-sp.jpg", "image/jpeg"),
                           ("/static/base.css", "text/css"), ("/static/favicon.svg", "image/svg+xml")):
            r = c.get(path)
            assert r.status_code == 200 and r.headers["content-type"].startswith(kind), path
        assert len(c.get("/static/banner.jpg").content) > 100_000


def test_base_template_uses_the_header_image_without_overlaid_title():
    from pathlib import Path
    base = (Path(__file__).parents[1] / "src/game_signal_scout/web/templates/base.html").read_text()
    assert 'src="/static/banner.jpg"' in base and 'srcset="/static/banner-sp.jpg"' in base and 'alt="Game Signal Scout' in base
    assert "<h1" not in base                                   # 題名は画像の中にある。文字を重ねない
    assert 'class="sidecol"' in base and 'class="navm"' in base   # Anime と同じ左の案内と、狭い画面の「メニュー」
