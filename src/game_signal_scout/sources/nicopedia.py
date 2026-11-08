"""プレイヤーの声の取得元: ニコニコ大百科の作品の記事の掲示板（dic.nicovideo.jp/b/a/<記事名>/。HTML。キー不要。台帳の nicovideo_dic_bbs）。

日本語で作品ごとに声が集まる公開の場。作品は記事で決まる（matched_by = source）。robots.txt の Crawl-delay: 5 を守る（同じサイトへ 5 秒に 1 回）。
- 対象: 遊ばれている・話題の多い作品（catalog.active_apps の max_games）。記事名は作品の日本語の題名、なければ英語の題名（見つからない作品は refresh_days の後に探し直す）。
- 記事のページから最新のレスのページを知り、前回読んだレスの番号より後のレスだけを読む（1 回に max_pages ページ = 30 件ずつ）。
- 1 件 = 1 レス。時刻は日本時間。投稿者はその日の ID（ID は日ごとに変わるので、人数は日ごとに数える Game の数え方と合う）の sha256。名前は持たない。
"""
from __future__ import annotations

import hashlib
import html
import re
import time
import urllib.parse
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

from game_signal_scout.sources.contract import Batch, SourceItem, SourceReader

SITE = "https://dic.nicovideo.jp"
JST = timezone(timedelta(hours=9))
PAGE = re.compile(r'/b/a/[^"#]+/(\d+)-')
RES = re.compile(r'(?s)<span class="bbs_resInfo_resTime"\s*>(\d{4})/(\d{2})/(\d{2})\(.\) (\d{2}):(\d{2}):(\d{2})</span>.*?'
                 r'<dd class="st-bbs_resbody"[^>]*data-res_no="(\d+)" data-id_hash="([^"]*)"[^>]*>\s*<div class="bbs_resbody_inner"\s*>(.*?)</div>\s*</dd>')


def plain(raw: str) -> str:
    t = re.sub(r'(?is)<a [^>]*class="dic"[^>]*>&gt;&gt;\d+</a>', " ", raw)      # 安価（>>123）は数えない
    t = re.sub(r"(?i)<br\s*/?>", "\n", t)
    return re.sub(r"[ \t]+", " ", html.unescape(re.sub(r"<[^>]+>", "", t))).strip()


def parse(page: str) -> list[dict]:
    out = []
    for y, mo, d, h, mi, s, no, idh, body in RES.findall(page):
        out.append({"no": int(no), "at": datetime(int(y), int(mo), int(d), int(h), int(mi), int(s), tzinfo=JST), "id": idh, "text": plain(body)})
    return out


class Nicopedia(SourceReader):
    conn = None
    _last = 0.0

    def get(self, url: str) -> str | None:
        wait = float(self.settings.get("crawl_delay", 5)) - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        return self.http.get_text(self.name, url)

    def titles(self) -> list[tuple[str, list[str]]]:
        if self.settings.get("apps"):
            return [(str(a), list(t)) for a, t in self.settings["apps"]]
        if self.conn is None:
            return []
        from game_signal_scout.repositories import catalog
        s = self.settings
        apps = [a for a, _ in catalog.active_apps(self.conn, int(s.get("active_days", 90)), int(s.get("max_games", 60)))]
        rows = {a: [t for t in (ja, en) if t] for a, ja, en in
                self.conn.execute("SELECT appid, title, names->>'en' FROM game_profile WHERE appid = ANY(%s)", (apps,)).fetchall()}
        return [(a, list(dict.fromkeys(rows[a]))) for a in apps if rows.get(a)]

    def read(self, cursor: dict | None) -> Iterator[Batch]:
        state = dict(cursor or {})
        art, last, tried = dict(state.get("article") or {}), dict(state.get("last") or {}), dict(state.get("tried") or {})
        refresh = int(self.settings.get("refresh_days", 7)) * 86400
        for appid, names in self.titles():
            page = None
            if appid not in art or (not art[appid] and time.time() - float(tried.get(appid, 0)) > refresh):
                art[appid], tried[appid] = "", time.time()
                for n in names:
                    page = self.get(f"{SITE}/a/{urllib.parse.quote(n)}")
                    if page and PAGE.search(page):
                        art[appid] = n
                        break
                    page = None
            name = art.get(appid)
            if not name:
                yield Batch([], {"article": art, "last": last, "tried": tried})
                continue
            page = page or self.get(f"{SITE}/a/{urllib.parse.quote(name)}")
            starts = sorted({int(x) for x in PAGE.findall(page or "")})
            seen = int(last.get(appid, 0))
            todo = [s for s in starts if s + 29 > seen][-int(self.settings.get("max_pages", 3)):] if starts else []
            items = []
            for st in todo:
                body = self.get(f"{SITE}/b/a/{urllib.parse.quote(name)}/{st}-")
                for r in parse(body or ""):
                    if r["no"] <= seen or not r["text"]:
                        continue
                    items.append(SourceItem(self.name, f"{appid}:{r['no']}", r["at"], {
                        "appid": appid, "text": r["text"][:4000], "lang": "ja", "url": f"{SITE}/b/a/{urllib.parse.quote(name)}/{st}-#{r['no']}",
                        "author": hashlib.sha256(f"nicopedia:{r['at'].date()}:{r['id']}".encode()).hexdigest()[:16]}, None))
            if items:
                last[appid] = max(int(i.item_id.split(":")[1]) for i in items)
            yield Batch(items, {"article": art, "last": last, "tried": tried})
