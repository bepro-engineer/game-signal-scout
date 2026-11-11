"""「遊べなくなった・直った」の変化の検出（Issue #1 の検証P で事前に固定した規則）。LLM は使わない。

作品ごとに、各報告の時刻から始まる 14 日の窓を見る。次をすべて満たす窓を事象とする:
  ① 窓の「鍵の報告」（失敗側は失敗の報告、直った側は成功の報告）が 5 件以上
  ② その鍵の報告の機材構成が 5 種類以上
  ③ 窓の失敗の割合が、直前 60 日より 30 ポイント以上高い（直った側は低い）。直前 60 日の報告が 5 件以上の作品に限る
重なる窓（14 日以内に始まる窓）は 1 つにまとめ、鍵の報告の多いほうを残す。
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

DAY = 86400


def detect(rows, start: datetime, end: datetime, p: dict) -> list[dict]:
    """rows: (work_id, 時刻の秒, 失敗か, 機材構成の hash, item_id)。窓の始まりは [start, end) の範囲。"""
    w, prev = p["window_days"] * DAY, p["prev_days"] * DAY
    s, e = start.timestamp(), end.timestamp()
    by = defaultdict(list)
    for app, ts, fail, cfg, iid in rows:
        by[app].append((ts, fail, cfg, iid))
    out = []
    for app, rs in by.items():
        rs.sort()
        for side in ("fail", "fix"):
            found = []
            for t0, f0, _, _ in rs:
                if not (s <= t0 < e) or f0 != (side == "fail"):
                    continue
                win = [r for r in rs if t0 <= r[0] < t0 + w]
                before = [r for r in rs if t0 - prev <= r[0] < t0]
                if len(before) < p["min_prev_reports"]:
                    continue
                key = [r for r in win if r[1] == (side == "fail")]
                if len(key) < p["min_key_reports"] or len({r[2] for r in key}) < p["min_distinct_configs"]:
                    continue
                sw, sp = sum(r[1] for r in win) / len(win), sum(r[1] for r in before) / len(before)
                if (sw - sp if side == "fail" else sp - sw) < p["min_jump"]:
                    continue
                ev = {"side": side, "work_id": app, "start": t0, "n_key": len(key), "n_window": len(win), "share_prev": round(sp, 3),
                      "share_window": round(sw, 3), "n_prev": len(before), "item_ids": [r[3] for r in key]}
                if found and t0 < found[-1]["start"] + w:
                    if ev["n_key"] > found[-1]["n_key"]:
                        found[-1] = ev
                else:
                    found.append(ev)
            out.extend(found)
    for ev in out:
        ev["window_start"] = datetime.fromtimestamp(ev.pop("start"), timezone.utc)
    return sorted(out, key=lambda ev: (-ev["n_key"], ev["work_id"], ev["window_start"]))
