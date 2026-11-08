"""画面の静的なファイル（DB なし）: 指定のヘッダー画像（Issue #2）と画面の部品が配られること。"""
from fastapi.testclient import TestClient

from game_signal_scout.web.app import create_app


def test_header_image_and_assets_are_served():
    with TestClient(create_app(cfg={"web": {}}, pool=object())) as c:
        for path, kind in (("/static/site-header.jpg", "image/jpeg"), ("/static/site-header-1100.jpg", "image/jpeg"),
                           ("/static/base.css", "text/css"), ("/static/favicon.svg", "image/svg+xml")):
            r = c.get(path)
            assert r.status_code == 200 and r.headers["content-type"].startswith(kind), path
        assert len(c.get("/static/site-header.jpg").content) > 100_000


def test_base_template_uses_the_header_image_without_overlaid_title():
    from pathlib import Path
    base = (Path(__file__).parents[1] / "src/game_signal_scout/web/templates/base.html").read_text()
    assert 'src="/static/site-header.jpg"' in base and "srcset=" in base and 'alt="Game Signal Scout' in base
    assert "<h1" not in base                                   # 題名は画像の中にある。文字を重ねない
