"""最初に届く HTML に入れる、文だけの要約（View）。
画面は JavaScript が接続口から読んで描くので、JavaScript を動かさない読み手（ページを読みに来る AI など）には題名しか見えなかった。
公開した文書（public_document）の内容から、今日の兆し・目立った作品・作品の紹介を文にして、<main> の最後に置く。
JavaScript が動くブラウザでは、画面の部品（boot.js）がこの要素を消すので、見た目は変わらない。集計・判定はしない（文書にある文を並べるだけ）。"""
from __future__ import annotations

import json

from markupsafe import Markup

from game_signal_scout.web.services import public_content

LIST_MAX = 20
SYNOPSIS_MAX = 600


def _ja(x) -> str:
    if isinstance(x, dict):
        return str(x.get("ja") or x.get("en") or "")
    return str(x or "")


def _link(w: dict) -> Markup:
    return Markup('<a href="work.html?id={}">{}</a>').format(w.get("id", ""), _ja(w.get("name")))


def _day(conn) -> dict | None:
    days = json.loads(public_content.get_days(conn))
    latest = (days.get("built") or [None])[-1]
    return json.loads(public_content.get_day(conn, latest)) if latest else None


def day_summary(conn) -> str:
    d = _day(conn)
    db = (d or {}).get("dashboard") or {}
    if not db:
        return ""
    out = [Markup("<h2>{}の兆し</h2>").format(_ja(db.get("label")))]
    lead = (db.get("lead") or {}).get("ja") or {}
    if lead.get("head"):
        out.append(Markup("<p>{}</p>").format(lead["head"]))
        out += [Markup("<p>{}</p>").format(b) for b in lead.get("body") or []]
    s = db.get("summary") or {}
    for k in ("head", "lede"):
        if _ja(s.get(k)):
            out.append(Markup("<p>{}</p>").format(_ja(s.get(k))))
    checks = [c for c in db.get("checks") or [] if _ja(c.get("line"))][:LIST_MAX]
    if checks:
        out.append(Markup("<h3>目立って動いた作品</h3><ul>"))
        out += [Markup("<li>{}（{}）: {}</li>").format(_link(c), _ja(c.get("label")), _ja(c.get("line"))) for c in checks]
        out.append(Markup("</ul>"))
    top = (db.get("top") or [])[:LIST_MAX]
    if top:
        out.append(Markup("<h3>話題の多かった作品（人数は取得元ごとの独立した投稿者）</h3><ol>"))
        out += [Markup("<li>{}: {}人</li>").format(_link(w), w.get("n", "")) for w in top]
        out.append(Markup("</ol>"))
    return Markup("").join(out)


def work_summary(conn, work: str) -> str:
    w = json.loads(public_content.get_work(conn, work))
    out = [Markup("<h2>{}</h2>").format(_ja(w.get("name")))]
    if w.get("genres"):
        out.append(Markup("<p>ジャンル: {}</p>").format("・".join(_ja(g) for g in w["genres"])))
    if w.get("start"):
        out.append(Markup("<p>発売日: {}</p>").format(w["start"]))
    syn = _ja(w.get("synopsis")).strip()
    if syn:
        cut = syn[:SYNOPSIS_MAX] + ("…" if len(syn) > SYNOPSIS_MAX else "")
        out.append(Markup("<h3>ゲーム内容</h3>"))
        out += [Markup("<p>{}</p>").format(p) for p in cut.split("\n") if p.strip()]
    lead = w.get("lead") or {}
    lj = lead.get("ja") if isinstance(lead, dict) else None
    if isinstance(lj, dict) and lj.get("head"):
        out.append(Markup("<h3>プレイヤーの声から</h3><p>{}</p>").format(lj["head"]))
        out += [Markup("<p>{}</p>").format(b) for b in lj.get("body") or []]
    return Markup("").join(out)


def block(conn, name: str, work: str | None = None) -> Markup:
    """ページに入れる要約の要素。作れないとき（未公開・形の違い）は空（ページは今までどおり出す）。"""
    try:
        body = work_summary(conn, work) if name == "work" and work else day_summary(conn)
    except (public_content.NotPublishedError, ValueError, KeyError, TypeError, AttributeError):
        return Markup("")
    if not body:
        return Markup("")
    return Markup('<div class="plain" id="plain">{}</div>').format(body)

