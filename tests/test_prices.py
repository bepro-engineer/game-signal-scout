"""作品の日本向けの販売価格（#2 2026-11-10）: 取得 → 作品の属性 price → 画面の値 → 公開の文書 → 画面。
通常価格・割引中・無料・発売前・未確認を区別し、0 円・架空の価格を作らない。古い価格は今の価格として出さない。日英で国・通貨・数値は同じ。"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from game_signal_scout.sources.steam_prices import PRICES, SteamPrices, price_value

T = datetime(2026, 11, 10, 3, 0, tzinfo=timezone.utc)
PO = lambda ini, fin, off: {"price_overview": {"currency": "JPY", "initial": ini, "final": fin, "discount_percent": off}}


def test_price_cases_are_told_apart_and_nothing_is_made_up():
    at = T.isoformat()
    assert price_value("1", PO(299900, 299900, 0), None, "JP", at) | {} == {
        "country": "JP", "url": "https://store.steampowered.com/app/1/", "checked_at": at, "status": "paid", "currency": "JPY", "initial": 2999, "final": 2999, "discount": 0}
    sale = price_value("1", PO(400000, 200000, 50), None, "JP", at)
    assert (sale["initial"], sale["final"], sale["discount"]) == (4000, 2000, 50)               # 割引中: 通常価格・現在価格・割引率
    odd = price_value("1", PO(400000, 390000, 50), None, "JP", at)
    assert (odd["initial"], odd["final"], odd["discount"]) == (3900, 3900, 0)                   # 割引率が価格と合わない: 割引として出さない
    assert price_value("1", [], {"is_free": True, "release_date": {"coming_soon": False}}, "JP", at)["status"] == "free"
    assert price_value("1", [], {"is_free": False, "release_date": {"coming_soon": True}}, "JP", at)["status"] == "coming_soon"
    unk = price_value("1", [], {"is_free": False, "release_date": {"coming_soon": False}}, "JP", at)
    assert unk["status"] == "unknown" and "final" not in unk                                     # 価格も無料の印もない: 0 円にしない
    assert price_value("1", [], None, "JP", at) is None                                         # 区別できない: 記録しない


class Http:
    def __init__(self, bodies):
        self.bodies, self.urls = bodies, []

    def get_json(self, source, url):
        self.urls.append(url)
        return next((b for k, b in self.bodies.items() if k in url), None)


def test_reader_asks_many_titles_at_once_and_details_only_where_no_price():
    prices = {"10": {"success": True, "data": PO(140000, 140000, 0)}, "20": {"success": True, "data": []}, "30": {"success": True, "data": []},
              "40": {"success": False}, "50": {"success": True, "data": []}}
    http = Http({"appids=10,20,30,40,50": prices,
                 "appids=20&": {"20": {"success": True, "data": {"type": "game", "is_free": True}}},
                 "appids=30&": {"30": {"success": True, "data": {"type": "dlc", "is_free": False}}},
                 "appids=50&": None})                                                                 # 通信の失敗: 記録しない（前の値は鮮度つきで残る）
    r = SteamPrices({"appids": ["10", "20", "30", "40", "50"], "batch_size": 50, "country": "jp"}, http)
    r.name = "steam_prices"
    items = {i.item_id: i for b in r.read(None) for i in b.items}
    assert set(items) == {"10", "20"}
    assert items["10"].payload["price"]["final"] == 1400 and items["20"].payload["price"]["status"] == "free"
    assert http.urls[0] == PRICES.format(ids="10,20,30,40,50", cc="jp") and len(http.urls) == 4   # 価格は 1 回で。詳しく聞くのは価格のない 3 作品だけ
    rows = SteamPrices.attributes("10", T, items["10"].payload)
    assert rows == [("10", "price", items["10"].payload["price"])]


def test_screen_value_drops_stale_prices_and_keeps_unknown_apart():
    from game_signal_scout.ops.work_display import price_of, work_attrs
    v = lambda **k: {"price": [{"source": "s", "value": {"country": "JP", "url": "u", **k}, "fetched_at": T.isoformat()}]}
    assert price_of({}, 3) == {} and "price" not in work_attrs({})                                # 属性なし = 未確認（画面は未確認・カードは何も出さない）
    paid = price_of(v(status="paid", currency="JPY", initial=4000, final=2000, discount=50), 3, now=T + timedelta(hours=5))["price"]
    assert paid == {"s": "paid", "cc": "JP", "at": "2026-11-10", "url": "u", "cur": "JPY", "fin": 2000, "ini": 4000, "off": 50}
    full = price_of(v(status="paid", currency="JPY", initial=2999, final=2999, discount=0), 3, now=T)["price"]
    assert "ini" not in full and "off" not in full                                               # 割引していなければ現在価格だけ
    assert price_of(v(status="free"), 3, now=T)["price"]["s"] == "free" and "fin" not in price_of(v(status="free"), 3, now=T)["price"]
    assert price_of(v(status="paid", currency="JPY", initial=1, final=1, discount=0), 3, now=T + timedelta(days=4)) == {}   # 古い価格は出さない


def test_price_flows_from_store_item_to_public_work(conn):
    from game_signal_scout.ops.work_display import work_meta
    from game_signal_scout.services import normalize
    from game_signal_scout.signal.content import _judge
    import json
    now = datetime.now(timezone.utc)
    for a in ("10", "20"):
        conn.execute("INSERT INTO source_item (source, item_id, occurred_at, received_at, payload) VALUES ('steam_store', %s, now(), now(), '{}')", (a,))
        conn.execute("INSERT INTO game_profile (appid, source, item_id, title, genres, modes, platforms, fetched_at) VALUES (%s, 'steam_store', %s, 'x', '[]', '[]', '[]', now())", (a, a))
    p = {"appid": "10", "price": price_value("10", PO(400000, 200000, 50), None, "JP", now.isoformat())}
    conn.execute("INSERT INTO source_item (source, item_id, occurred_at, received_at, payload, version) VALUES ('steam_prices', '10', now(), now(), %s, 'v')", (json.dumps(p),))
    conn.commit()
    assert normalize.attributes(conn, "steam_prices") == 1
    m = work_meta(conn, [10, 20])
    assert _judge(m[10])["price"]["fin"] == 2000 and _judge(m[10])["price"]["off"] == 50 and _judge(m[10])["price"]["cur"] == "JPY"
    assert "price" not in _judge(m[20])                                                          # 価格のない作品: 0 円にも無料にもしない


def test_screens_show_price_without_making_up_values():
    root = Path(__file__).parents[1] / "src/game_signal_scout/web/static"
    common, work = (root / "common.js").read_text(), (root / "work.js").read_text()
    for s in ('tr(`${num(v)}円`, `¥${num(v)}`)', 'tr("無料", "Free")', 'tr("発売前", "Not yet released")', "<s>${money(p.ini, p.cur)}</s>"):
        assert s in common
    assert 'tr(`日本のストアの価格（${esc(W.price.at)} 確認。変わることがあります）`' in work and 'tr("未確認", "Unknown")' in work   # 日付・地域・ストアへの道。なければ未確認
    assert "A.priceTag(x.w)" in (root / "finds.js").read_text() and "A.priceTag(w)" in (root / "search.js").read_text()
    assert "税込" not in common + work                                                            # 根拠のない税込の断定をしない

