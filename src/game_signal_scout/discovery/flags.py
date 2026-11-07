"""宣伝・自動投稿などの印（Anime の discovery/flags を移植し、語をゲームに替えた）。削除はしない。印だけを付ける。

検証T（Issue #1 6706259238）で固定した宣伝の除外の規則と同じ語を含む: 広告の印、リンクだけの投稿、配信の告知。
"""
from __future__ import annotations

import re

from game_signal_scout.discovery.text import PostText

_AFFILIATE = re.compile(r"(#ad\b|amzn\.to|amazon\.[a-z.]+/(dp|gp)/|a\.r10\.to|tag=|affiliate|paidlink|アフィリエイト)", re.I)
_PROMO = re.compile(r"(【PR】|#PR\b|sponsored|giveaway|プレゼントキャンペーン|wishlist now|ウィッシュリスト登録)", re.I)
_NEWS = re.compile(r"(📰|breaking:|news:|#gamingnews|#ゲームニュース|速報)", re.I)
_STREAM = re.compile(r"(live now|going live|twitch\.tv/|youtube\.com/live|配信中|配信開始|配信します)", re.I)
_ADULT = re.compile(r"(hentai|nsfw|porn|rule34|lewd|ecchi|dlsite|r18|r-18)", re.I)
_PIRACY = re.compile(r"(\broms?\b|\bnsp\b|\bxci\b|free download|repack|cracked)", re.I)   # 2026-11-07 の実データで、海賊版の配布の投稿が作品に数えられた
_AUTOPOST = re.compile(r"(自動投稿|auto[- ]?post|#bot\b|new post:|new video:|now playing|tune in now|#trending)", re.I)


def flags_for(pt: PostText) -> list[str]:
    f = []
    text = pt.text + " " + pt.link_title
    if _AFFILIATE.search(text):
        f.append("affiliate")
    if _PROMO.search(text):
        f.append("promo")
    if _NEWS.search(text):
        f.append("news")
    if _STREAM.search(text):
        f.append("stream")
    if _PIRACY.search(text):
        f.append("piracy")
    if _AUTOPOST.search(text):
        f.append("autopost")
    if _ADULT.search(text + " " + " ".join(pt.tags)):
        f.append("adult")
    if len(pt.tags) >= 6:
        f.append("many_hashtags")
    if pt.has_link and len(pt.text.strip()) <= len(pt.link_title.strip()) + 5 and pt.link_title:
        f.append("link_only")
    return f
