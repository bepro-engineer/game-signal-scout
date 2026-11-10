"""作品のユーザー評価（#2 2026-11-10）: ストアが示す集計（全期間・日本語のレビュー）だけを持ち、換算・推定をしない。古い集計は出さない。"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from game_signal_scout.sources.steam_ratings import SteamRatings, summary

T = datetime(2026, 11, 10, 3, 0, tzinfo=timezone.utc)


class Http:
    def __init__(self, by_lang):
        self.by_lang, self.urls = by_lang, []

    def get_json(self, source, url):
        self.urls.append(url)
        return next((b for k, b in self.by_lang.items() if f"%22language%22%3A%22{k}%22" in url), None)


def it(appid, all_=None, lang=None):
    return {"appid": appid, "reviews": {**({"summary_filtered": all_} if all_ else {}), **({"summary_language_specific": lang} if lang else {})}}


def test_reader_keeps_store_totals_and_both_labels():
    ja = {"response": {"store_items": [
        it(1, {"review_count": 766462, "percent_positive": 97, "review_score": 9, "review_score_label": "圧倒的に好評"},
           {"review_count": 1840, "percent_positive": 94, "review_score": 8, "review_score_label": "非常に好評"}),
        it(2, {"review_count": 7, "percent_positive": 71}),        # 件数が少なく段階がない: 件数だけ
        it(3)]}}                                                    # 集計なし: 記録しない
    en = {"response": {"store_items": [it(1, {"review_count": 766462, "percent_positive": 97, "review_score": 9, "review_score_label": "Overwhelmingly Positive"},
                                          {"review_count": 9, "percent_positive": 90, "review_score": 8, "review_score_label": "Very Positive"})]}}
    r = SteamRatings({"appids": ["1", "2", "3"]}, Http({"japanese": ja, "english": en}))
    r.name = "steam_ratings"
    items = {i.item_id: i for b in r.read(None) for i in b.items}
    assert set(items) == {"1", "2"}
    v = items["1"].payload["rating"]
    assert v["all"] == {"n": 766462, "pct": 97, "score": 9, "label": {"ja": "圧倒的に好評", "en": "Overwhelmingly Positive"}}
    assert v["lang"] == {"n": 1840, "pct": 94, "score": 8, "label": {"ja": "非常に好評", "en": "Very Positive"}, "code": "ja"}
    assert items["2"].payload["rating"]["all"] == {"n": 7, "pct": 71} and "lang" not in items["2"].payload["rating"]
    assert SteamRatings.attributes("1", T, items["1"].payload) == [("1", "rating", v)]
    assert summary({"review_count": 0}, {}) is None


def test_screen_value_is_the_store_total_and_drops_stale_values():
    from game_signal_scout.ops.work_display import rating_of
    a = {"rating": [{"source": "s", "value": {"all": {"n": 10, "pct": 80, "score": 7, "label": {"ja": "好評", "en": "Positive"}}, "url": "u"}, "fetched_at": T.isoformat()}]}
    got = rating_of(a, 7, now=T + timedelta(days=1))["rating"]
    assert got == {"all": {"n": 10, "pct": 80, "score": 7, "label": {"ja": "好評", "en": "Positive"}}, "url": "u", "at": "2026-11-10"}
    assert rating_of(a, 7, now=T + timedelta(days=8)) == {} and rating_of({}, 7) == {}


def test_work_page_shows_ratings_apart_from_this_sites_counts():
    js = (Path(__file__).parents[1] / "src/game_signal_scout/web/static/work.js").read_text()
    assert 'sec("wk-rating", "ストアのユーザー評価", "Store user reviews"' in js
    assert '"全期間のレビュー"' in js and '"日本語のレビュー"' in js and "このサイトが数えた人数や、プレイヤーの体験の読み取りとは別の数です" in js
    assert "最近 30 日の評価は、ストアのページで確かめられます" in js and "/ 100" not in js.split("ストアのユーザー評価（#2")[1][:3000]   # 100 点に換算しない


def test_work_page_does_not_use_the_local_number_helper_before_it_is_defined():
    """作品詳細の上部（作品の判断の欄）は、ページの後ろで定義する数の部品（num）より前に描く。前で使うとページ全体が描けなくなる（2026-11-10 に一度起きた）。"""
    js = (Path(__file__).parents[1] / "src/game_signal_scout/web/static/work.js").read_text()
    head = js[:js.index("num = A.num")]
    assert "${num(" not in head
