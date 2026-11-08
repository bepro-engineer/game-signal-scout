"""公開用の文書の中身を作る（Game 固有。Anime の publication/content にあたる）。SQL は repositories、置き換えと記録は publication/publishing。

文書の鍵:
- overview: 取得元の鮮度、段の最後の結果、検出した変化の一覧
- game/<appid>: 変化のある作品ごとの、変化・週ごとの報告の推移・変化の根拠の報告（プレイヤーの記述）

値は JSON にそのまま入る形（時刻は ISO の文字列）にする。audit が、許した項目だけが入っていることを確かめる。
"""
from __future__ import annotations

from datetime import timedelta

from game_signal_scout import config
from game_signal_scout.ops.status import status
from game_signal_scout.publication.themes import label_notes, themes
from game_signal_scout.repositories import post, report

WEEKS = 26          # 作品の推移を見る週の数（分析の範囲の 184 日に合わせる）
NOTE_CHARS = 400    # 根拠の記述を画面に出す長さの上限
SPEECH_DAYS = 7     # 発言の多い作品を数える期間（最新の発言から遡る）
POSTS_SHOWN = 10    # 作品の画面に出す発言の数
RECENT_DAYS = 60     # 一覧で「最近の変化」として上に出す範囲（最新の報告から遡る）。それより前はたたむ
NOT_GAMES = {"1675200"}   # Steam Deck（機械）。ストアのリンクで発言が結び付くが、作品ではない
EVENT_KEYS = {"side", "appid", "title", "window_start", "n_key", "n_window", "share_prev", "share_window", "n_prev", "reports",
              "themes", "after", "summary", "recent"}
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
    newest = post.newest_at(conn)
    speech = [{**a, "since": _iso(newest - timedelta(days=SPEECH_DAYS))} for a in post.top_apps(conn, newest - timedelta(days=SPEECH_DAYS), 20)
              if a["appid"] not in NOT_GAMES] if newest else []
    return {"version": version, "sources": sources, "jobs": jobs, "events": events, "speech": speech,
            "counts": {side: sum(e["side"] == side for e in events) for side in ("fail", "fix")}}


def game(conn, version: str, appid: str, speech_title: str | None = None) -> dict | None:
    title = report.app_title(conn, appid)
    if title is None and speech_title is None:
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
        since = newest - timedelta(days=SPEECH_DAYS)
        authors, n = post.count_for_app(conn, appid, since)
        if n:
            posts = {"since": _iso(since), "authors": authors, "posts": n,
                     "recent": [{"at": _iso(r["at"]), "lang": r["lang"], "matched_by": r["matched_by"], "text": _clip(r["text"])}
                                for r in post.for_app(conn, appid, since, POSTS_SHOWN)]}
    return {"appid": appid, "title": title or speech_title, "version": version, "events": events, "weeks": weeks, "posts": posts}


def build(conn, version: str) -> dict[str, dict]:
    docs = {"overview": overview(conn, version)}
    titles = {a["appid"]: a["title"] or a["appid"] for a in docs["overview"]["speech"]}
    for appid in dict.fromkeys([e["appid"] for e in docs["overview"]["events"]] + list(titles)):
        g = game(conn, version, appid, titles.get(appid))
        if g is not None:
            docs[f"game/{appid}"] = g
    return docs


def audit(docs: dict[str, dict]) -> list[str]:
    """公開の前の検査: 許した項目だけ・一覧の作品には作品の文書がある・記述は上限の長さ以内。問題の一覧（空なら通る）。"""
    problems = []
    ov = docs.get("overview", {})
    for e in ov.get("events", []) + ov.get("speech", []):
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


def _clip(s: str | None) -> str:
    s = (s or "").strip()
    return s if len(s) <= NOTE_CHARS else s[:NOTE_CHARS] + "…"
