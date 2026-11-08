"""プレイヤーの声の取得元: Pantip（タイ語の掲示板）のゲームのタグの話題とコメント（HTML の埋め込み JSON と、ページ自身が呼ぶ render_comments の JSON）。

Anime の sources/pantip（アニメの部屋）の読み方を流用し、ゲームのタグ（เกม・เกมคอมพิวเตอร์ など）の一覧から読む。ログインしない（robots は /ads.php 以外を許可）。
render_comments にはページの JavaScript と同じ X-Requested-With と Referer を付ける（Anime と同じ。認証の回避ではない）。
- 1 件 = 話題（題名）または コメント・返信（本文）。コメントの同定には話題の題名を添える（link_title）。言語は th。
- 前回より新しい話題と、コメントの数が増えた話題だけを読む（続きの位置 = 話題ごとのコメントの数）。投稿者の番号は持たない（sha256 の先頭 16 桁）。
"""
from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

from game_signal_scout.sources.contract import Batch, SourceItem, SourceReader

BASE = "https://pantip.com"
TH = timezone(timedelta(hours=7))
_NEXT = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)


def actor(mid) -> str:
    from game_signal_scout.actor_key import keyed
    return keyed(hashlib.sha256(f"pantip:{mid}".encode()).hexdigest()[:16])


def parse_listing(page: str) -> list[dict]:
    m = _NEXT.search(page or "")
    if not m:
        return []
    try:
        rows = json.loads(m.group(1))["props"]["initialProps"]["pageProps"]["topics"]["data"] or []
    except (ValueError, KeyError, TypeError):
        return []
    return [{"id": str(t["topic_id"]), "title": (t.get("title") or "").strip(), "type": int(t.get("topic_type") or 1),
             "at": datetime.fromisoformat(t["created_time"].replace("Z", "+00:00")), "author": (t.get("author") or {}).get("id"),
             "comments": int(t.get("comments_count") or 0), "tags": [g.get("name") for g in t.get("tags") or [] if g.get("name")]}
            for t in rows if t.get("topic_id") and t.get("created_time")]


def _when(x: dict) -> datetime | None:
    if str(x.get("created_time") or "").isdigit():
        return datetime.fromtimestamp(int(x["created_time"]), timezone.utc)
    try:
        return datetime.strptime(x.get("data_utime") or "", "%m/%d/%Y %H:%M:%S").replace(tzinfo=TH).astimezone(timezone.utc)
    except ValueError:
        return None


def parse_comments(raw: str) -> tuple[list[dict], int]:
    try:
        d = json.loads((raw or "").lstrip("﻿"))
    except ValueError:
        return [], -1
    cs = d.get("comments") or []
    out = []
    for c in cs:
        for kind, x in [("c", c)] + [("r", y) for y in c.get("replies") or []]:
            cid = x.get("_id") if kind == "c" else x.get("reply_id")
            mid = (x.get("user") or {}).get("mid") or x.get("member_id")
            at = _when(x)
            text = re.sub(r"<[^>]+>", " ", x.get("message") or "").strip()
            if cid and mid and at and text:
                out.append({"id": f"{kind}:{cid}", "mid": str(mid), "at": at, "text": text})
    return out, len(cs)


class Pantip(SourceReader):
    def read(self, cursor: dict | None) -> Iterator[Batch]:
        seen = dict((cursor or {}).get("comments") or {})
        topics: dict[str, dict] = {}
        for tag in self.settings.get("tags") or []:
            for t in parse_listing(self.http.get_text(self.name, f"{BASE}/tag/{urllib.parse.quote(tag)}") or ""):
                topics.setdefault(t["id"], t)
        for t in sorted(topics.values(), key=lambda x: x["at"]):
            prev = seen.get(t["id"])
            if prev is not None and t["comments"] <= prev:
                continue
            items = []
            if prev is None:
                items.append(SourceItem(self.name, f"t:{t['id']}", t["at"], {"text": t["title"], "lang": "th", "author": actor(t["author"]),
                                                                           "url": f"{BASE}/topic/{t['id']}", "tags": t["tags"]}, None))
            if t["comments"]:
                for page in range(1, int(self.settings.get("max_comment_pages", 3)) + 1):
                    raw = self.http.get_text(self.name, f"{BASE}/forum/topic/render_comments?tid={t['id']}&param=page{page}&type={t['type']}&page={page}&parent=2&expand=1",
                                             headers={"X-Requested-With": "XMLHttpRequest", "Referer": f"{BASE}/topic/{t['id']}"})
                    rows, n = parse_comments(raw or "")
                    items += [SourceItem(self.name, r["id"], r["at"], {"text": r["text"][:4000], "link_title": t["title"], "tags": t["tags"], "lang": "th",
                                                                       "author": actor(r["mid"]), "url": f"{BASE}/topic/{t['id']}"}, None) for r in rows]
                    if n < 100:
                        break
            seen[t["id"]] = t["comments"]
            yield Batch(items, {"comments": seen})
        yield Batch([], {"comments": dict(list(seen.items())[-2000:])})
