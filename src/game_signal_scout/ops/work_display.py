"""Anime の ops/work_display.work_meta の Game 版: 作品の名前と画像（作品の情報 game_profile。画像は Steam の配信元の URL）。"""
from __future__ import annotations


def work_meta(conn, work_ids: list[int]) -> dict[int, dict]:
    ids = list(work_ids)
    if not ids:
        return {}
    from game_signal_scout.repositories import catalog
    rows = catalog.names_images(conn, [str(i) for i in ids])
    art = catalog.covers(conn, list(rows))
    conn.rollback()
    attrs = catalog.attributes_of(conn, list(rows))
    from game_signal_scout import config
    dcfg = config.load_daily_config()
    stale = int((dcfg.get("prices") or {}).get("stale_days", 3))
    rstale = int((dcfg.get("ratings") or {}).get("stale_days", 7))
    plats = catalog.platforms_of(conn, list(rows))
    conn.rollback()
    # 画像: 縦長の枠には縦長の表紙（なければストアのヘッダー）、作品詳細の帯には横長の帯（なければヘッダー）
    # 日本人が最初に判断する属性（#2）: 日本語の UI・字幕・音声（jp）、開発元と国・地域（dev）、遊べる機種（plat）。どの画面のカードにも同じ値
    return {int(a): {"id": f"w{a}", "name": {"ja": t, "en": en or t}, "cover": (art.get(a) or (None, None))[0] or img,
                     "banner": (art.get(a) or (None, None))[1] or img, **work_attrs(attrs.get(a) or {}, stale), **rating_of(attrs.get(a) or {}, rstale), "plat": plats.get(a) or [], "shots": next((x["value"] for x in (attrs.get(a) or {}).get("shots") or [] if x.get("value")), []), "header": img}
            for a, (t, en, img) in rows.items()}


def work_attrs(attrs: dict, stale_days: int = 3) -> dict:
    """作品の属性（game_attribute。取得元ごとの値）から、画面の値を作る。取得元の名前で分けない。
    jp: {ui, sub, voice}（true / false。属性がなければ null = 未確認）、jp_at: 取得の時刻。
    dev: [{n: 開発元, c: [国・地域]（記載がなければ null = 未確認）, ref: 出典の URL}]。国の記載のある取得元の値を先に使い、推定しない。"""
    out: dict = {"jp": None, "dev": [], **price_of(attrs, stale_days)}
    ja = (attrs.get("ja") or [None])[0]
    if ja:
        v = ja["value"]
        out["jp"] = {"ui": bool(v.get("ui")), "sub": bool(v.get("subtitles")), "voice": bool(v.get("audio"))}
        out["jp_at"] = ja["fetched_at"][:10]
    import re
    named = lambda n: bool(n) and not re.fullmatch(r"Q\d+", str(n))   # 名前（日本語・英語）の記載がない開発元は、識別子を名前として出さない
    with_country = [d for d in next((x["value"] for x in attrs.get("developer_countries") or [] if x.get("value")), []) if named(d.get("developer"))]
    if with_country:
        out["dev"] = [{"n": d["developer"], "c": d.get("countries") or None, "ref": d.get("ref"),   # 英語の名前（n_en・c_en。英語の表示。#2）
                       **({"n_en": d["developer_en"]} if d.get("developer_en") else {}), **({"c_en": d["countries_en"]} if d.get("countries_en") else {})}
                      for d in with_country]
    else:
        names = next((x["value"] for x in attrs.get("developers") or [] if x.get("value")), [])
        out["dev"] = [{"n": n, "c": None} for n in names if named(n)]
    return out


def price_of(attrs: dict, stale_days: int, now=None) -> dict:
    """作品の価格（属性 price のいちばん新しい値）→ 画面の値 price: {s: paid / free / coming_soon / unknown, cc: 国, cur: 通貨, ini: 通常価格, fin: 現在価格,
    off: 割引率（割引中だけ）, at: 確かめた日, url: ストアの作品のページ}。属性がない・確かめてから stale_days 日を超えた値は出さない（price なし = 画面は未確認）。
    0 円・架空の値は作らない（無料はストアが無料と示した作品だけ）。"""
    from datetime import datetime, timedelta, timezone
    x = next((x for x in attrs.get("price") or [] if isinstance(x.get("value"), dict) and x["value"].get("status")), None)
    if not x:
        return {}
    v, at = x["value"], datetime.fromisoformat(x["fetched_at"])
    if (now or datetime.now(timezone.utc)) - at > timedelta(days=stale_days):
        return {}
    out = {"s": v["status"], "cc": v.get("country"), "at": at.astimezone(timezone(timedelta(hours=9))).date().isoformat(), "url": v.get("url")}
    if v["status"] == "paid":
        out.update(cur=v["currency"], fin=v["final"], **({"ini": v["initial"], "off": v["discount"]} if v.get("discount") else {}))
    return {"price": out}


def rating_of(attrs: dict, stale_days: int, now=None) -> dict:
    """作品のユーザー評価（属性 rating のいちばん新しい値）→ 画面の値 rating: {all: {n, pct, score, label}, lang: {…, code}, at: 確かめた日, url: ストアのレビューの場所}。
    ストアの集計そのまま（換算・推定なし）。属性がない・stale_days 日を超えた値は出さない（rating なし = 画面は評価の欄を出さない）。"""
    from datetime import datetime, timedelta, timezone
    x = next((x for x in attrs.get("rating") or [] if isinstance(x.get("value"), dict) and x["value"].get("all")), None)
    if not x:
        return {}
    at = datetime.fromisoformat(x["fetched_at"])
    if (now or datetime.now(timezone.utc)) - at > timedelta(days=stale_days):
        return {}
    v = x["value"]
    return {"rating": {"all": v["all"], **({"lang": v["lang"]} if v.get("lang") else {}), "url": v.get("url"),
                       "at": at.astimezone(timezone(timedelta(hours=9))).date().isoformat()}}


def display_names(conn, work_ids: list[int]) -> dict[int, dict]:
    """work_id → {ja, en}（Anime の display_names と同じ形。日本語はストアの日本語の表示、英語は英語の題名〔なければ日本語の表示〕）。"""
    from game_signal_scout.repositories import catalog
    rows = catalog.names_images(conn, [str(i) for i in work_ids])
    conn.rollback()
    return {int(a): {"ja": t, "en": en or t} for a, (t, en, _) in rows.items()}
