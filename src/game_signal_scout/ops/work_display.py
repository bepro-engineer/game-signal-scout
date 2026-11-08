"""Anime の ops/work_display.work_meta の Game 版: 作品の名前と画像（作品の情報 game_profile。画像は Steam の配信元の URL）。"""
from __future__ import annotations


def work_meta(conn, work_ids: list[int]) -> dict[int, dict]:
    ids = list(work_ids)
    if not ids:
        return {}
    rows = conn.execute("SELECT appid, title, image_url FROM game_profile WHERE appid = ANY(%s)", ([str(i) for i in ids],)).fetchall()
    conn.rollback()
    return {int(a): {"id": f"w{a}", "name": {"ja": t, "en": t}, "cover": img, "banner": img} for a, t, img in rows}


def display_names(conn, work_ids: list[int]) -> dict[int, dict]:
    """work_id → {ja, en}（Anime の display_names と同じ形。Game は作品の情報の題名。日英は同じ）。"""
    rows = conn.execute("SELECT appid, title FROM game_profile WHERE appid = ANY(%s)", ([str(i) for i in work_ids],)).fetchall()
    conn.rollback()
    return {int(a): {"ja": t, "en": t} for a, t in rows}
