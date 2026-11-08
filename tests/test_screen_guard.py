"""画面の守り（#2 6723899842: 別の修正の副作用で、オーナーが決めた段を消す・動かす・隠すことを試験で止める）。"""
import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "src" / "game_signal_scout" / "web"


def test_top_sections_keep_the_owner_order():
    """トップの段の並びは オーナーの決めた 今日の兆し → 地図 → 今日の注目 → もっと見る（入口はその前）。"""
    html = (WEB / "templates" / "pages" / "index.html").read_text()
    ids = re.findall(r'id="([a-z]+)"', html)
    assert ids == ["intro", "lead", "world", "others", "more"]


def test_top_script_never_removes_or_hides_a_section():
    """段を丸ごと消す・隠す処理を入れない（空になったら理由を書く）。"""
    js = (WEB / "static" / "dashboard.js").read_text()
    for sec in ("intro", "lead", "world", "others", "more"):
        assert not re.search(rf'\$\("{sec}"\)\.(remove|hidden|style)', js), sec
        assert not re.search(rf'getElementById\("{sec}"\)\.(remove|hidden|style)', js), sec


def test_japanese_badges_always_come_with_a_legend():
    """日本語の札の出る領域には凡例を必ず入れる（ページを描いた後に必ず呼ぶ）。札は記号でなく言葉。"""
    boot = (WEB / "static" / "boot.js").read_text()
    common = (WEB / "static" / "common.js").read_text()
    assert "A.ensureJpLegend()" in boot
    for word in ("日本語音声", "日本語字幕", "日本語UI", "日本語非対応"):
        assert word in common


def test_finds_document_uses_only_public_keys():
    """発見の公開文書は、公開しない項目名（did・generated_at など）を使わない。"""
    from game_signal_scout.signal import content
    ev = content._pub_ev({"did": "スナイパーで頭を撃ち抜いた", "happened": "快感があった", "verdict": "fun"})
    doc = {"finds": {"items": [{"id": "w1", "finds": [{"title": "t", "examples": [ev]}], "singles": [ev], "since": "2026-11-01"}]}}
    assert content.audit_public(doc, "pages") == []
    assert ev["act"] and ev["result"] and "did" not in ev
