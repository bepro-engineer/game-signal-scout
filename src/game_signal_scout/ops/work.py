"""Anime の ops/work.publishable_works の Game 版: 作品として見せてよい作品 = 作品の情報（game_profile）のある Steam の作品。"""
from __future__ import annotations


def publishable_works(conn, work_ids) -> set[int]:
    ids = sorted({int(w) for w in work_ids if w is not None})
    if not ids:
        return set()
    out = {int(a) for (a,) in conn.execute("SELECT appid FROM game_profile WHERE appid = ANY(%s)", ([str(i) for i in ids],))}
    conn.rollback()
    return out
