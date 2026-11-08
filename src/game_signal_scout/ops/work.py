"""Anime の ops/work.publishable_works の Game 版: 作品として見せてよい作品 = 作品の情報（game_profile）のある Steam の作品のうち、ゲームであるもの。

ゲームでないソフト（Steam のジャンルがユーティリティ・映像や音声の制作・デザインなどのもの。例: Wallpaper Engine）は出さない
（Game の対象は PC・家庭用のゲーム。2026-11-08: 今日の兆しに壁紙のソフトが選ばれた）。"""
from __future__ import annotations


NOT_GAME = ["ユーティリティ", "ビデオ制作", "オーディオ制作", "デザイン & イラストレーション", "写真編集", "アニメーション & モデリング", "トレーニング",
            "ソフトウェアトレーニング", "Web 公開", "会計", "教育", "Utilities", "Video Production", "Audio Production", "Design & Illustration",
            "Photo Editing", "Animation & Modeling", "Software Training", "Web Publishing", "Accounting", "Education"]


def publishable_works(conn, work_ids) -> set[int]:
    ids = sorted({int(w) for w in work_ids if w is not None})
    if not ids:
        return set()
    out = {int(a) for (a,) in conn.execute("SELECT appid FROM game_profile WHERE appid = ANY(%s) AND NOT (genres ?| %s)", ([str(i) for i in ids], NOT_GAME))}
    conn.rollback()
    return out
