"""プレイヤーの声の取得元: GOG のユーザーレビュー（reviews.gog.com の公開 JSON。キー不要。台帳 config/source_candidates.toml の gog_reviews）。

Steam のレビューと同じ種類（作品ごとのレビュー・言語・星 1〜5）で、DRM フリーの層の声。作品は取得元で決まる（matched_by = source）。
- 対象: 遊ばれている・話題の多い作品（catalog.active_apps の max_games）。GOG の商品 ID は GOG の公開カタログの検索（題名の完全一致・種類 game、なければ pack）で決め、
  続きの位置に覚える（見つからない作品は refresh_days の後に探し直す）。
- 新しい順に読み、max_age_days より古いレビュー、または前回読んだ最新のレビューに届いたら、その作品を終える。
- 投稿者の GOG の番号・名前・画像は持たない（sha256 の先頭 16 桁）。
"""
from __future__ import annotations

import hashlib
import html
import re
import time
import urllib.parse
from collections.abc import Iterator
from datetime import datetime

from game_signal_scout.actor_key import keyed
from game_signal_scout.sources.contract import Batch, SourceItem, SourceReader

CATALOG = "https://catalog.gog.com/v1/catalog?query=like:{q}&limit=5&locale=en-US"
REVIEWS = "https://reviews.gog.com/v1/products/{pid}/reviews?limit=50&order=desc:date&page={page}"


def norm(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", re.sub(r"[™®©]", "", (t or "").casefold())).strip()


def lang(code: str | None) -> str | None:
    c = (code or "").split("-")[0].lower() or None
    return {"zh": "zh-Hans" if (code or "").lower() in ("zh-cn", "zh-hans") else "zh-Hant"}.get(c, c) if c else None


class GogReviews(SourceReader):
    conn = None

    @staticmethod
    def voice(item_id: str, payload: dict) -> dict:
        """対象はこのサイトの作品（catalog.active_apps）なので、payload の appid はこのサイトの作品の番号（引かずに使う: work_id）。"""
        p = {k: v for k, v in payload.items() if k != "appid"}
        return {**p, "work_id": payload.get("work_id") or payload.get("appid")} if payload.get("work_id") or payload.get("appid") else p

    def titles(self) -> list[tuple[str, str]]:
        """(appid, 英語の題名)。"""
        if self.settings.get("apps"):
            return [(str(a), t) for a, t in self.settings["apps"]]
        if self.conn is None:
            return []
        from game_signal_scout.repositories import catalog
        s = self.settings
        apps = [a for a, _ in catalog.active_apps(self.conn, int(s.get("active_days", 90)), int(s.get("max_games", 60)))]
        rows = catalog.names_images(self.conn, apps)
        return [(a, rows[a][1] or rows[a][0]) for a in apps if a in rows]

    def product(self, title: str) -> str:
        body = self.http.get_json(self.name, CATALOG.format(q=urllib.parse.quote(title)))
        same = [p for p in (body or {}).get("products") or [] if norm(p.get("title")) == norm(title) and p.get("productType") in ("game", "pack")]
        same.sort(key=lambda p: p.get("productType") != "game")         # 題名の同じ「game」を先に。なければ同じ題名の「pack」（本編の束）
        return str(same[0]["id"]) if same else ""

    def read(self, cursor: dict | None) -> Iterator[Batch]:
        state = dict(cursor or {})
        mp, seen, tried = dict(state.get("map") or {}), dict(state.get("last") or {}), dict(state.get("tried") or {})
        age = int(self.settings.get("max_age_days", 28))
        refresh = int(self.settings.get("refresh_days", 7)) * 86400
        for appid, title in self.titles():
            if appid not in mp or (not mp[appid] and time.time() - float(tried.get(appid, 0)) > refresh):
                mp[appid], tried[appid] = self.product(title), time.time()
            pid = mp.get(appid)
            if not pid:
                yield Batch([], {"map": mp, "last": seen, "tried": tried})
                continue
            items, newest = [], seen.get(appid)
            for page in range(1, int(self.settings.get("max_pages_per_app", 20)) + 1):
                body = self.http.get_json(self.name, REVIEWS.format(pid=pid, page=page))
                rows = ((body or {}).get("_embedded") or {}).get("items") or []
                stop = not rows
                for r in rows:
                    at = datetime.fromisoformat(r.get("creationDate") or r["date"])
                    if (seen.get(appid) and r["id"] == seen[appid]) or at.timestamp() < time.time() - age * 86400:
                        stop = True
                        break
                    c = r.get("content") or {}
                    text = html.unescape(((c.get("title") or "") + "\n" + (c.get("description") or "")).strip())
                    if text:
                        items.append(SourceItem(self.name, r["id"], at, {"appid": appid, "text": text[:4000], "lang": lang(c.get("language")),
                                                                         "rating": (r.get("rating") or {}).get("value"),
                                                                         "author": keyed(hashlib.sha256(f"gog:{(r.get('reviewer') or {}).get('id')}".encode()).hexdigest()[:16])},
                                                str(r.get("internalUpdateDate") or r.get("date"))))
                newest = newest if page > 1 or not rows else rows[0]["id"]
                if stop or page >= int((body or {}).get("pages") or 1):
                    break
            seen[appid] = newest
            yield Batch(items, {"map": mp, "last": seen, "tried": tried})
