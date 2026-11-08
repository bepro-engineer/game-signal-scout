"""Anime の publication/publishing.build_documents の Game 版（流用）: Anime と同じ鍵・同じ形の公開用の文書を作る。
day/<日>（dashboard・spread）・pages・search・soon・work/w<app ID>・days。中身は signal/content（Anime の content.py を流用）。
Anime の schemas（公開してよい項目の検査）は、content.audit_public の検査を使う。"""
from __future__ import annotations

import time


def build_documents(conn, cfg: dict) -> tuple[dict[str, object], dict]:
    from game_signal_scout.signal import content
    t0 = time.perf_counter()
    ctx = content.Ctx(conn, cfg, None)
    docs: dict[str, object] = {}
    for d in ctx.pdays:
        docs[f"day/{d.isoformat()}"] = {"dashboard": content.dashboard(ctx, d), "spread": content.spread(ctx, d)}
    pg = content.pages(ctx)
    docs["pages"] = pg
    docs["search"] = content.search(ctx, pg)
    from game_signal_scout.signal import upcoming
    docs["soon"] = upcoming.soon(conn, ctx.latest, set(ctx.works))     # これから発売の作品（Anime の「まもなく放送」に当たる）
    pg_on: dict[str, list[str]] = {}
    for page, lists in (("language_spread", ["items"]), ("post_air", ["ended", "soon"]), ("revival", ["items", "watch"])):
        for name in lists:
            for x in pg[page][name]:
                pg_on.setdefault(x["id"], []).append(page)
    hist = content.history_window(ctx)
    for w in ctx.works:
        docs[f"work/w{w}"] = content.work_detail(ctx, w, hist, pg_on)
    docs["days"] = {"days": [d.isoformat() for d in ctx.pdays], "built": [d.isoformat() for d in ctx.pdays], "latest": ctx.latest.isoformat(),
                    "labels": {d.isoformat(): content.dlabel(d) for d in ctx.pdays}}
    conn.rollback()
    audit = [x for path, body in docs.items() for x in content.audit_public(body, path)]
    return docs, {"seconds": round(time.perf_counter() - t0, 1), "days": len(ctx.pdays), "works": len(ctx.works), "audit": audit[:10]}
