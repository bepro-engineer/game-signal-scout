"""Anime の ops/work_display.work_meta の Game 版: 作品の名前と画像（作品の情報 game_profile。画像は Steam の配信元の URL）。"""
from __future__ import annotations


def work_meta(conn, work_ids: list[int]) -> dict[int, dict]:
    ids = list(work_ids)
    if not ids:
        return {}
    from game_signal_scout.repositories import catalog
    rows = catalog.names_images(conn, [str(i) for i in ids])
    conn.rollback()
    return {int(a): {"id": f"w{a}", "name": {"ja": t, "en": en or t}, "cover": img, "banner": img} for a, (t, en, img) in rows.items()}


def display_names(conn, work_ids: list[int]) -> dict[int, dict]:
    """work_id → {ja, en}（Anime の display_names と同じ形。日本語はストアの日本語の表示、英語は英語の題名〔なければ日本語の表示〕）。"""
    from game_signal_scout.repositories import catalog
    rows = catalog.names_images(conn, [str(i) for i in work_ids])
    conn.rollback()
    return {int(a): {"ja": t, "en": en or t} for a, (t, en, _) in rows.items()}
