"""公開用の文書の中身を作る（Game 固有。Anime の publication/content にあたる）。SQL は repositories、置き換えと記録は publication/publishing。

文書の鍵（利用者の判断から決める。取得元の名前・形では分けない。Issue #2）:
- overview: 作品のカードの一覧（catalog: 画像・説明・ジャンル・遊び方・機種・日本語・遊ばれている規模・プレイヤーの声の数・買う前の注意）、
  遊び方ごとの数（modes）、買う前に知っておきたい動作の変化（events）、取得元の鮮度と段の結果（このサイトについて）
- game/<appid>: 作品の情報（profile）・遊ばれている規模（activity）・最近の動作の報告（compat）・プレイヤーの声（posts）・
  動作の変化と根拠（events）・週ごとの推移（weeks）・まだ分からないこと（missing）

値は JSON にそのまま入る形（時刻は ISO の文字列）にする。audit が、許した項目だけが入っていることを確かめる。
"""
from __future__ import annotations

from datetime import timedelta

from game_signal_scout import config
from game_signal_scout.ops.status import status
from game_signal_scout.publication.themes import label_notes, themes
from game_signal_scout.repositories import catalog, post, report

WEEKS = 26          # 作品の推移を見る週の数（分析の範囲の 184 日に合わせる）
NOTE_CHARS = 400    # 根拠の記述を画面に出す長さの上限
POSTS_SHOWN = 10    # 作品の画面に出す発言の数
RECENT_DAYS = 60     # 一覧で「最近の変化」として上に出す範囲（最新の報告から遡る）。それより前はたたむ
NOT_GAMES = {"1675200"}   # Steam Deck（機械）。ストアのリンクで発言が結び付くが、作品ではない
CATALOG_SIZE = 120  # トップと「ゲームを探す」に出す作品の数（プレイヤーの報告・発言・遊ばれている規模の多い順）
VOICE_DAYS = 30     # プレイヤーの声を数える期間
COMPAT_DAYS = 90    # 動作の報告の割合を見る期間（最新の報告から遡る）
SUMMARY_CHARS = 90  # カードの説明の長さ
CARD_KEYS = {"appid", "title", "image", "genres", "modes", "platforms", "ja_text", "ja_voice", "released", "summary", "rank", "prev_rank",
             "peak_players", "voices", "compat", "caution"}
MISSING = ["クリアまでの時間", "プレイヤーの満足度・評価", "向いている人・向いていない人"]   # 今の取得元では根拠を出せない（作らない）
EVENT_KEYS = {"side", "appid", "title", "window_start", "n_key", "n_window", "share_prev", "share_window", "n_prev", "reports",
              "themes", "after", "summary", "recent", "image"}
THEME_KEYS = {"key", "label", "n"}
REPORT_KEYS = {"at", "failed", "proton", "notes"}          # item_id・機材構成の hash は出さない
POST_KEYS = {"at", "lang", "matched_by", "text"}           # 投稿者の HMAC・投稿の URI は出さない


def _iso(x):
    return x.isoformat() if hasattr(x, "isoformat") else x


def _pct(x: float) -> str:
    return f"{round(x * 100)}%"


def describe(conn, e: dict, window_days: int, newest) -> dict:
    """変化の 1 件に「何が・いつから・どれだけ・その後」を足す（日本語の 1 文と、根拠を数えた内容。言い切らず、件数をそのまま出す）。"""
    notes = report.notes_by_ids(conn, e["item_ids"])
    th = themes(notes, e["side"])
    end = e["window_start"] + timedelta(days=window_days)
    aft = report.after(conn, e["appid"], end)
    start = e["window_start"]
    what = "「遊べない」という報告が増えた" if e["side"] == "fail" else "「遊べる」という報告に変わった"
    text = (f"{start.month}月{start.day}日ごろから、Linux（Proton）で{what}。遊べない割合は、直前 60 日の {_pct(e['share_prev'])}（{e['n_prev']} 件）"
            f"から、続く {window_days} 日で {_pct(e['share_window'])}（{e['n_window']} 件）になった。")   # 途中の窓は「続く 14 日」のうち報告のある分
    if newest and end > newest:
        text += f"この {window_days} 日はまだ途中（最新の報告は {newest.month}月{newest.day}日）。"
    elif aft["n"]:
        text += f"その後（{end.month}月{end.day}日から）の報告は {aft['n']} 件で、うち遊べないは {aft['failed']} 件。"
    else:
        text += "その後の報告はまだない。"
    return {"themes": [{"key": t["key"], "label": t["label"], "n": t["n"]} for t in th], "after": {**aft, "since": _iso(end)}, "summary": text,
            "recent": bool(newest and start >= newest - timedelta(days=RECENT_DAYS))}


def overview(conn, version: str, limit: int = 200) -> dict:
    s = status(conn)
    wd, newest_report = int(config.load_daily_config()["analysis"]["window_days"]), report.newest_report_at(conn)
    events = []
    for e in report.recent_events(conn, version, limit):
        d = describe(conn, e, wd, newest_report)
        events.append({**{k: _iso(v) for k, v in e.items() if k != "item_ids"}, **d})
    sources = {name: {"items": src.get("items") or 0, "newest_occurred_at": _iso(src.get("newest_occurred_at")),
                      "last_ok_at": _iso(src.get("last_ok_at")), "last_error_type": src.get("last_error_type")}
               for name, src in s["sources"].items()}
    jobs = {name: {"status": j.get("status"), "finished_at": _iso(j.get("finished_at"))}
            for name, j in s["jobs"].items() if name != "publish"}       # 作っている最中の自分の段は出さない
    cards = catalog_cards(conn, events)
    imgs = catalog.profiles(conn, [e["appid"] for e in events])
    for e in events:
        e["image"] = (imgs.get(e["appid"]) or {}).get("image_url")
    modes: dict[str, int] = {}
    genres: dict[str, int] = {}
    for c in cards:
        for m in c["modes"]:
            modes[m] = modes.get(m, 0) + 1
        for g in c["genres"]:
            genres[g] = genres.get(g, 0) + 1
    return {"version": version, "sources": sources, "jobs": jobs, "events": events, "catalog": cards, "modes": modes, "genres": genres, "missing": MISSING,
            "counts": {side: sum(e["side"] == side for e in events) for side in ("fail", "fix")}}


def catalog_cards(conn, events: list[dict]) -> list[dict]:
    """作品のカード（作品の情報があるものだけ。画像のない作品をカードにしない）。並びはプレイヤーの報告・発言・遊ばれている規模の多い順。"""
    order = [a for a, _ in catalog.active_apps(conn, VOICE_DAYS * 3, CATALOG_SIZE * 2) if a not in NOT_GAMES]
    prof = catalog.profiles(conn, order)
    order = [a for a in order if a in prof][:CATALOG_SIZE]
    act, comp, voices = catalog.latest_activity(conn, order), catalog.recent_reports(conn, order, COMPAT_DAYS), catalog.voice_counts(conn, order, VOICE_DAYS)
    caution = {}
    for e in events:                                   # 新しい順。作品ごとに最新の「最近の」変化だけ
        if e["recent"] and e["appid"] not in caution:
            caution[e["appid"]] = {"side": e["side"], "since": e["window_start"]}
    out = []
    for a in order:
        p, ac = prof[a], act.get(a) or {}
        out.append({"appid": a, "title": p["title"], "image": p["image_url"], "genres": p["genres"][:3], "modes": p["modes"], "platforms": p["platforms"],
                    "ja_text": p["ja_text"], "ja_voice": p["ja_voice"], "released": p["released"], "summary": _clip(p["summary"], SUMMARY_CHARS),
                    "rank": ac.get("rank"), "prev_rank": ac.get("prev_rank"), "peak_players": ac.get("peak_players"),
                    "voices": voices.get(a, 0), "compat": comp.get(a), "caution": caution.get(a)})
    return out


def game(conn, version: str, appid: str) -> dict | None:
    prof = catalog.profiles(conn, [appid]).get(appid)
    title = (prof or {}).get("title") or report.app_title(conn, appid)
    if not title:
        return None
    events = []
    wd, newest_report = int(config.load_daily_config()["analysis"]["window_days"]), report.newest_report_at(conn)
    for e in report.app_events(conn, version, appid):
        d = describe(conn, e, wd, newest_report)
        reports = [{"at": _iso(r["at"]), "failed": r["failed"], "proton": r["proton"], "notes": _clip(label_notes(r["notes"]))}
                   for r in report.reports_by_ids(conn, e.pop("item_ids"))]
        events.append({**{k: _iso(v) for k, v in e.items() if k != "title"}, **d, "reports": reports})
    weeks = [{"week": _iso(w["week"]), "reports": w["reports"], "failed": w["failed"], "configs": w["configs"],
              "share": w["failed"] / w["reports"] if w["reports"] else 0.0} for w in report.app_weekly(conn, appid, WEEKS)]
    newest = post.newest_at(conn)
    posts = None
    if newest:
        since = newest - timedelta(days=VOICE_DAYS)
        authors, n = post.count_for_app(conn, appid, since)
        if n:
            posts = {"since": _iso(since), "authors": authors, "posts": n,
                     "recent": [{"at": _iso(r["at"]), "lang": r["lang"], "matched_by": r["matched_by"], "text": _clip(r["text"])}
                                for r in post.for_app(conn, appid, since, POSTS_SHOWN)]}
    profile = None
    if prof:
        profile = {"image": prof["image_url"], "summary": prof["summary"], "genres": prof["genres"], "modes": prof["modes"], "platforms": prof["platforms"],
                   "ja_text": prof["ja_text"], "ja_voice": prof["ja_voice"], "released": prof["released"], "store_url": prof["store_url"]}
    ac = catalog.latest_activity(conn, [appid]).get(appid)
    activity = {"day": _iso(ac["day"]), "rank": ac["rank"], "prev_rank": ac["prev_rank"], "peak_players": ac["peak_players"]} if ac else None
    return {"appid": appid, "title": title, "version": version, "profile": profile, "activity": activity,
            "compat": catalog.recent_reports(conn, [appid], COMPAT_DAYS).get(appid), "compat_days": COMPAT_DAYS,
            "events": events, "weeks": weeks, "posts": posts, "missing": MISSING}


def build(conn, version: str) -> dict[str, dict]:
    docs = {"overview": overview(conn, version)}
    newest = post.newest_at(conn)
    voiced = [a["appid"] for a in post.top_apps(conn, newest - timedelta(days=VOICE_DAYS), 50) if a["appid"] not in NOT_GAMES] if newest else []
    for appid in dict.fromkeys([c["appid"] for c in docs["overview"]["catalog"]] + [e["appid"] for e in docs["overview"]["events"]] + voiced):
        g = game(conn, version, appid)
        if g is not None:
            docs[f"game/{appid}"] = g
    return docs


def audit(docs: dict[str, dict]) -> list[str]:
    """公開の前の検査: 許した項目だけ・一覧の作品には作品の文書がある・記述は上限の長さ以内。問題の一覧（空なら通る）。"""
    problems = []
    ov = docs.get("overview", {})
    for c in ov.get("catalog", []):
        if extra := set(c) - CARD_KEYS:
            problems.append(f"overview: 許していない項目 {sorted(extra)}")
    for e in ov.get("events", []) + ov.get("catalog", []):
        if f"game/{e['appid']}" not in docs:
            problems.append(f"overview: game/{e['appid']} がない")
    for e in ov.get("events", []):
        if extra := set(e) - EVENT_KEYS:
            problems.append(f"overview: 許していない項目 {sorted(extra)}")
        for t in e.get("themes", []):
            if extra := set(t) - THEME_KEYS:
                problems.append(f"overview: 許していない項目 {sorted(extra)}")
    for path, d in docs.items():
        if not path.startswith("game/"):
            continue
        for e in d["events"]:
            if extra := set(e) - EVENT_KEYS:
                problems.append(f"{path}: 許していない項目 {sorted(extra)}")
            for r in e["reports"]:
                if extra := set(r) - REPORT_KEYS:
                    problems.append(f"{path}: 許していない項目 {sorted(extra)}")
                if len(r["notes"]) > NOTE_CHARS + 1:
                    problems.append(f"{path}: 記述が長すぎる")
        for r in (d.get("posts") or {}).get("recent", []):
            if extra := set(r) - POST_KEYS:
                problems.append(f"{path}: 許していない項目 {sorted(extra)}")       # 投稿者・投稿の ID は出さない
    return problems


def _clip(s: str | None, n: int = NOTE_CHARS) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[:n] + "…"
