"""これから発売の作品（Anime の「まもなく放送」に当たる。文書 soon・接続口 api/soon・メニューの下の枠）。

材料: Steam の人気の近日発売の一覧（game_upcoming）と作品の情報（game_profile の発売日の文・画像）。
話題の人数は、どの取得元の発言も同じに数える（直近 7 日に、その作品について書いた人。取得元ごとに数えて足さない＝最も多い取得元の人数）。
"""
from __future__ import annotations

import re
from datetime import date, timedelta

Q = {"1": ("1〜3月", "Q1"), "2": ("4〜6月", "Q2"), "3": ("7〜9月", "Q3"), "4": ("10〜12月", "Q4")}


def release(text: str | None) -> dict:
    """Steam のストアの発売日の文（日本語の表示）→ {date: 日付（日まで分かるとき）, ja, en}。"""
    t = (text or "").strip()
    if m := re.fullmatch(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", t):
        d = date(int(m[1]), int(m[2]), int(m[3]))
        return {"date": d.isoformat(), "ja": f"{d.month}/{d.day}", "en": f"{d.month}/{d.day}"}
    if m := re.fullmatch(r"(\d{4})\s*年\s*(\d{1,2})\s*月", t):
        return {"date": None, "ja": f"{m[1]}年{int(m[2])}月", "en": f"{m[1]}-{int(m[2]):02d}"}
    if m := re.search(r"(\d{4})\s*年\s*第\s*(\d)\s*四半期", t):
        return {"date": None, "ja": f"{m[1]}年{Q[m[2]][0]}", "en": f"{Q[m[2]][1]} {m[1]}"}
    if m := re.fullmatch(r"(\d{4})\s*年", t):
        return {"date": None, "ja": f"{m[1]}年", "en": m[1]}
    return {"date": None, "ja": "発売日未定", "en": "TBA"}


def people_7d(conn, appids: list[str], as_of: date) -> dict[str, int]:
    """直近 7 日（as_of まで）に、その作品について書いた人（取得元ごとに数え、いちばん多い取得元の人数。取得元をまたいで足さない）。"""
    from game_signal_scout.days import day_range
    from game_signal_scout.repositories import post
    return post.people_by_appid(conn, appids, day_range(as_of - timedelta(days=6))[0], day_range(as_of)[1])


def soon(conn, as_of: date, works: set[int], limit: int = 60) -> dict:
    """文書 soon: dated（発売日が決まっていて今日から先。日付の順）と picks（ほかの近日発売。Steam の一覧の順）。作品詳細があれば id、なければ Steam のストアの URL。"""
    from game_signal_scout.repositories import catalog
    rows = [r for r in catalog.upcoming(conn) if r.get("title") and r.get("coming_soon") is not False][:limit]
    ppl = people_7d(conn, [r["appid"] for r in rows], as_of) if rows else {}
    dated, picks = [], []
    for r in rows:
        rel = release(r.get("released"))
        x = {"id": f"w{r['appid']}" if int(r["appid"]) in works else None, "store": r.get("store_url"), "name": {"ja": r["title"], "en": r["title"]},
             "cover": r.get("image"), "rank": r["rank"], "release": rel, "people": ppl.get(r["appid"], 0),
             "genres": (r.get("genres") or [])[:2]}
        if rel["date"] and rel["date"] >= as_of.isoformat():
            dated.append(x)
        elif not rel["date"]:
            picks.append(x)
    dated.sort(key=lambda x: (x["release"]["date"], x["rank"]))
    return {"as_of": as_of.isoformat(), "dated": dated, "picks": picks, "items": [], "premieres": []}
