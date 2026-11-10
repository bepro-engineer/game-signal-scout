"""作品詳細のゲーム内容の描き方（#7 2026-11-09）。"""
from pathlib import Path


def test_about_list_items_are_not_spread_one_per_paragraph():
    """ゲーム内容（#7 2026-11-09）: 箇条書きの項目の間に空行を作らず、画面は「・」の行の続きを 1 つの詰めた一覧として描く。文は消さない。"""
    from game_signal_scout.sources.steam_store import about_text
    assert about_text("<p>Editions</p><ul><li>A</li><br><li>B</li><br><li>C</li></ul><p>次</p>") == "Editions\n・A\n・B\n・C\n\n次"
    js = (Path(__file__).parents[1] / "src/game_signal_scout/web/static/work.js").read_text()
    css = (Path(__file__).parents[1] / "src/game_signal_scout/web/static/work.css").read_text()
    assert 'class="wk-ul"' in js and 'class="wk-li"' in js and "${synHtml(syn)}" in js
    assert ".wk-syn.open .wk-ul { display: grid;" in css and "max-height" not in css.split("ゲーム内容の中の一覧")[1][:600]   # 高さで切らない
