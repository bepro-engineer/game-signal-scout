"""Anime の catalog/profile の Game 版: 作品情報（作品詳細・一覧の補足）。Game の作品情報は game_profile。放送の状況（brief）はない。"""
from __future__ import annotations

import re


class CatalogView:
    def __init__(self, conn, provider: str):
        self.conn = conn


def work_profile(conn, work_id: int, level: str, as_of, view: CatalogView | None = None) -> dict:
    from game_signal_scout.repositories import catalog
    p = catalog.profile_of(conn, str(work_id))
    if not p:
        return {}
    m = re.search(r"(\d{4})", p.get("released") or "")
    # 作品詳細が読む形（Anime の profile の current）。あらすじの代わりにゲーム内容（Steam のストアの「このゲームについて」。日本語・英語の原文）
    p["current"] = {"title": p["title"], "genres": p.get("genres") or [], "year": int(m.group(1)) if m else None,
                    "about": {"ja": p.get("about_ja") or (p.get("summary") if re.search(r"[\u3040-\u30ff]", p.get("summary") or "") else None), "en": p.get("about_en")}}
    return p


def brief(profile: dict) -> dict | None:
    """一覧・探すページの作品の概要（Anime の brief と同じ鍵: genres・year。status は Game にない）。Game だけの鍵: modes（遊び方）。"""
    if not profile:
        return None
    m = re.search(r"(\d{4})", profile.get("released") or "")
    return {"genres": profile.get("genres") or [], "year": int(m.group(1)) if m else None, "status": None, "format": None, "season": None,
            "modes": profile.get("modes") or []}
