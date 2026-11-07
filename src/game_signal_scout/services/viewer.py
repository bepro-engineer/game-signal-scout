"""Viewer の Service: 画面に出す形を作る（読むだけ。SQL は repositories、HTML は web）。

- overview: 取得元の鮮度と段の結果（ops/status）と、検出した変化の一覧
- game: 作品ごとの変化・週ごとの報告の推移・変化の根拠の報告（プレイヤーの記述）
"""
from __future__ import annotations

from game_signal_scout.ops.status import status
from game_signal_scout.repositories import report

WEEKS = 26          # 作品の推移を見る週の数（分析の範囲の 184 日に合わせる）
NOTE_CHARS = 400    # 根拠の記述を画面に出す長さの上限


def overview(conn, version: str, limit: int = 200) -> dict:
    events = report.recent_events(conn, version, limit)
    return {"status": status(conn), "version": version, "events": events,
            "counts": {s: sum(e["side"] == s for e in events) for s in ("fail", "fix")}}


def game(conn, version: str, appid: str) -> dict | None:
    title = report.app_title(conn, appid)
    if title is None:
        return None
    events = report.app_events(conn, version, appid)
    for e in events:
        e["reports"] = [{**r, "notes": _clip(r["notes"])} for r in report.reports_by_ids(conn, e.pop("item_ids"))]
    weeks = report.app_weekly(conn, appid, WEEKS)
    for w in weeks:
        w["share"] = w["failed"] / w["reports"] if w["reports"] else 0.0
    return {"appid": appid, "title": title, "version": version, "events": events, "weeks": weeks}


def _clip(s: str | None) -> str:
    s = (s or "").strip()
    return s if len(s) <= NOTE_CHARS else s[:NOTE_CHARS] + "…"
