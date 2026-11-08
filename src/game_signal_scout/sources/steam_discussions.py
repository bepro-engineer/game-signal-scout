"""プレイヤーの声の取得元: Steam コミュニティの作品ごとの掲示板（steamcommunity.com/app/<appid>/discussions/0/ の総合の掲示板。キー不要・HTML）。

作品は掲示板で決まる（matched_by = source）。1 件 = 話題の最初の投稿、または返信。言語は掲示板が示さないので本文から推定する（languages_detect）。
- 対象の作品: 遊ばれている・話題の多い作品（catalog.active_apps の max_games）と、これから発売の作品（最新の一覧の上位 upcoming_games）。
- 一覧の list_pages ページを読み、最後の投稿の時刻が前回より新しい話題だけを開く（作品ごとの続きの位置 = 前回見た最後の投稿の時刻）。
- 話題は最初のページ（最初の投稿と最初の返信）と、返信が多いときは最後のページ（新しい返信）を読む。
- 成人向けの内容を含む作品の掲示板は、年齢確認の画面になり読めない（その作品は 0 件。年齢確認を越える取得はしない。2026-11-08 オーナーの判断事項）。
- 投稿者の Steam のプロフィールの番号は持たない（sha256 の先頭 16 桁）。プロフィールの URL・名前・画像も持たない。
"""
from __future__ import annotations

import hashlib
import html
import re
from collections.abc import Iterator
from datetime import datetime, timezone

from game_signal_scout.languages_detect import detect
from game_signal_scout.sources.contract import Batch, SourceItem, SourceReader

BASE = "https://steamcommunity.com/app/{appid}/discussions/0/"
TOPIC = re.compile(r'<a class="forum_topic_overlay" href="(https://steamcommunity\.com/app/\d+/discussions/0/(\d+)/)"')
LASTPOST = re.compile(r'class="forum_topic_lastpost"[^>]*data-timestamp="(\d+)"')
OP = re.compile(r'(?s)id="forum_op_(\d+)".*?data-miniprofile="(\d+)".*?class="date commentthread_comment_timestamp"[^>]*data-timestamp="(\d+)"'
                r'.*?class="topic" id="forum_op_topic_\d+">(.*?)</div>\s*<div class="content" id="forum_op_content_\d+">(.*?)</div>\s*<div class="forum_op_footer">')
COMMENT = re.compile(r'(?s)class="commentthread_comment [^"]*" id="comment_(\d+)".*?commentthread_author_link[^>]*data-miniprofile="(\d+)"'
                     r'.*?class="commentthread_comment_timestamp"[^>]*data-timestamp="(\d+)".*?id="comment_content_\d+">(.*?)</div>\s*<div class="comment_footer_ctn">')
PAGES = re.compile(r"[?&]ctp=(\d+)")
QUOTE = re.compile(r'(?is)<blockquote.*?</blockquote>')


def text(raw: str) -> str:
    t = QUOTE.sub(" ", raw)                                          # 引用した他人の文は数えない
    t = re.sub(r"(?i)<br\s*/?>", "\n", t)
    t = html.unescape(re.sub(r"<[^>]+>", "", t)).replace(" ", " ")
    return re.sub(r"[ \t]+", " ", re.sub(r"\n{3,}", "\n\n", t)).strip()


def actor(miniprofile: str) -> str:
    return hashlib.sha256(f"steamcommunity:{miniprofile}".encode()).hexdigest()[:16]


def parse_list(page: str) -> list[tuple[str, str, int]]:
    """一覧の話題: (URL, 話題の ID, 最後の投稿の時刻)。"""
    topics, lasts = TOPIC.findall(page), [int(x) for x in LASTPOST.findall(page)]
    return [(u, tid, ts) for (u, tid), ts in zip(topics, lasts)]


def parse_topic(page: str) -> tuple[list[dict], int]:
    """話題のページの投稿（最初の投稿は題名も本文に含める）と、ページの数。"""
    out = []
    if m := OP.search(page):
        tid, mp, ts, title, body = m.groups()
        out.append({"id": tid, "author": actor(mp), "at": int(ts), "text": (text(title) + "\n" + text(body)).strip(), "op": True})
    for cid, mp, ts, body in COMMENT.findall(page):
        out.append({"id": cid, "author": actor(mp), "at": int(ts), "text": text(body), "op": False})
    return out, max([int(x) for x in PAGES.findall(page)] or [1])


class SteamDiscussions(SourceReader):
    conn = None     # 収集の Service が渡す（対象の作品を引く）

    def targets(self) -> list[str]:
        if self.settings.get("appids"):
            return [str(a) for a in self.settings["appids"]]
        if self.conn is None:
            return []
        from game_signal_scout.repositories import catalog
        s = self.settings
        apps = [a for a, _ in catalog.active_apps(self.conn, int(s.get("active_days", 90)), int(s.get("max_games", 60)))]
        up = [a for (a,) in self.conn.execute("SELECT appid FROM game_upcoming WHERE day = (SELECT max(day) FROM game_upcoming) ORDER BY rank LIMIT %s",
                                              (int(s.get("upcoming_games", 30)),))]
        return apps + [a for a in up if a not in apps]

    def read(self, cursor: dict | None) -> Iterator[Batch]:
        state = dict(cursor or {})
        s = self.settings
        for appid in self.targets():
            since = int(state.get(appid, 0))
            newest = since
            items: list[SourceItem] = []
            for p in range(1, int(s.get("list_pages", 2)) + 1):
                page = self.http.get_text(self.name, BASE.format(appid=appid) + (f"?fp={p}" if p > 1 else ""))
                if page is None:
                    break
                topics = parse_list(page)
                fresh = [t for t in topics if t[2] > since]
                for url, tid, last in fresh[: int(s.get("max_topics", 20))]:
                    items += self.topic(appid, url, tid)
                    newest = max(newest, last)
                if len(fresh) < len(topics) or not topics:          # 前回より古い話題に届いた
                    break
            state[appid] = newest
            yield Batch(items, dict(state))

    def topic(self, appid: str, url: str, tid: str) -> list[SourceItem]:
        page = self.http.get_text(self.name, url)
        if page is None:
            return []
        posts, pages = parse_topic(page)
        if pages > 1:
            last = self.http.get_text(self.name, f"{url}?ctp={pages}")
            if last:
                posts += [p for p in parse_topic(last)[0] if not p["op"]]
        out = {}
        for p in posts:
            if not p["text"]:
                continue
            at = datetime.fromtimestamp(p["at"], timezone.utc)
            out[p["id"]] = SourceItem(self.name, p["id"], at, {"appid": appid, "topic": tid, "author": p["author"], "text": p["text"][:4000],
                                                                 "lang": detect(p["text"]), "op": p["op"], "url": url}, None)
        return list(out.values())
