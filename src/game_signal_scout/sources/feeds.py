"""プレイヤーの声の取得元（共通の読み方 2 つ）。サイトは記述（config/sources.toml の feeds・sites）に足すだけで増やせる。

- FeedForum: 掲示板・コメントの RSS / Atom（XenForo・Invision・Discuz・WordPress のコメント・PTT など）。1 件 = フィードの 1 項目（題名＋本文の抜粋）。
- Discourse: Discourse の掲示板の公開 JSON（/posts.json = サイト全体の新しい投稿）。1 件 = 1 投稿（本文の全文）。
どちらも、作品の掲示板（作品が決まる）には記述の appid、総合の掲示板は本文から同定する（normalize.voices・game_only）。
言語は記述の lang、なければ本文から推定する。投稿者の名前は持たない（sha256 の先頭 16 桁）。前回より新しい項目だけを保存する（続きの位置 = 各フィード・サイトの最新の時刻）。
"""
from __future__ import annotations

import hashlib
import html
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from game_signal_scout.languages_detect import detect
from game_signal_scout.sources.contract import Batch, SourceItem, SourceReader

NS = {"atom": "http://www.w3.org/2005/Atom", "dc": "http://purl.org/dc/elements/1.1/", "content": "http://purl.org/rss/1.0/modules/content/",
      "rss1": "http://purl.org/rss/1.0/"}


def plain(raw: str | None) -> str:
    t = re.sub(r"(?is)<(script|style|blockquote)[^>]*>.*?</\1>", " ", raw or "")
    t = re.sub(r"(?i)<br\s*/?>|</p>", "\n", t)
    t = html.unescape(re.sub(r"<[^>]+>", "", t)).replace(" ", " ")
    return re.sub(r"[ \t]+", " ", re.sub(r"\n{3,}", "\n\n", t)).strip()


def actor(site: str, name: str | None) -> str:
    return hashlib.sha256(f"{site}:{name or ''}".encode()).hexdigest()[:16]


def when(s: str | None) -> datetime | None:
    if not s:
        return None
    s = s.strip()
    try:
        d = parsedate_to_datetime(s)
    except (TypeError, ValueError):
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def parse_feed(body: str) -> list[dict]:
    """RSS 2.0・RSS 1.0（RDF）・Atom の項目: id・時刻・投稿者・題名・本文・URL。"""
    root = ET.fromstring(body.encode() if isinstance(body, str) else body)
    out = []
    for it in root.iter("item"):
        g = lambda tag: (it.findtext(tag, namespaces=NS) or "")
        out.append({"id": g("guid") or g("link"), "at": when(g("pubDate") or g("dc:date")), "author": g("dc:creator") or g("author"),
                    "title": g("title"), "body": g("content:encoded") or g("description"), "url": g("link")})
    for it in root.iter("{http://purl.org/rss/1.0/}item"):            # RSS 1.0（RDF）
        g = lambda tag: (it.findtext(tag, namespaces=NS) or "")
        out.append({"id": it.get("{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about") or g("rss1:link"), "at": when(g("dc:date")),
                    "author": g("dc:creator"), "title": g("rss1:title"), "body": g("content:encoded") or g("rss1:description"), "url": g("rss1:link")})
    for it in root.iter("{http://www.w3.org/2005/Atom}entry"):
        g = lambda tag: (it.findtext(tag, namespaces=NS) or "")
        link = it.find("atom:link", NS)
        out.append({"id": g("atom:id") or (link.get("href") if link is not None else ""), "at": when(g("atom:updated") or g("atom:published")),
                    "author": it.findtext("atom:author/atom:name", namespaces=NS), "title": g("atom:title"),
                    "body": g("atom:content") or g("atom:summary"), "url": link.get("href") if link is not None else None})
    return [x for x in out if x["id"] and x["at"]]


class FeedForum(SourceReader):
    """記述の feeds = [{url, appid?, lang?}]。"""

    def read(self, cursor: dict | None) -> Iterator[Batch]:
        state = dict(cursor or {})
        for f in self.settings.get("feeds") or []:
            body = self.http.get_text(self.name, f["url"])
            if body is None:
                continue
            try:
                entries = parse_feed(body)
            except ET.ParseError:
                continue                                       # フィードでない応答（障害の頁など）。次の回に読み直す
            since = state.get(f["url"])
            items = []
            for e in entries:
                if since and e["at"].isoformat() <= since:
                    continue
                text = (plain(e["title"]) + "\n" + plain(e["body"])).strip()[:4000]
                pid = hashlib.sha256(e["id"].encode()).hexdigest()[:24]
                items.append(SourceItem(self.name, pid, e["at"], {"text": text, "author": actor(f["url"], e["author"]), "url": e["url"],
                                                                  "lang": f.get("lang") or detect(text), **({"appid": str(f["appid"])} if f.get("appid") else {}),
                                                                  "feed": f["url"]}, None))
            if entries:
                state[f["url"]] = max([e["at"].isoformat() for e in entries] + ([since] if since else []))
            yield Batch(items, dict(state))


class Discourse(SourceReader):
    """記述の sites = [{base, appid?, lang?}]。/posts.json（新しい投稿 約 50 件）を読み、前回より新しい投稿を保存する。"""

    def read(self, cursor: dict | None) -> Iterator[Batch]:
        state = dict(cursor or {})
        for s in self.settings.get("sites") or []:
            base = s["base"].rstrip("/")
            body = self.http.get_json(self.name, base + "/posts.json")
            posts = (body or {}).get("latest_posts") or []
            since = int(state.get(base, 0))
            items = []
            for p in posts:
                if int(p.get("id") or 0) <= since or p.get("hidden") or p.get("user_deleted"):
                    continue
                at = when(p.get("created_at"))
                text = (plain(p.get("topic_title")) + "\n" + plain(p.get("cooked"))).strip()[:4000]
                if not at or not text:
                    continue
                items.append(SourceItem(self.name, f"{base}#{p['id']}", at, {"text": text, "author": actor(base, p.get("username")),
                                                                             "url": f"{base}/t/{p.get('topic_slug')}/{p.get('topic_id')}/{p.get('post_number')}",
                                                                             "lang": s.get("lang") or detect(text), **({"appid": str(s["appid"])} if s.get("appid") else {})}, None))
            if posts:
                state[base] = max([int(p.get("id") or 0) for p in posts] + [since])
            yield Batch(items, dict(state))


class Lemmy(SourceReader):
    """Lemmy の公開 API（キー不要）。記述の communities = [{base, name, appid?}]。話題（post）と返信（comment）の新しいもの 50 件ずつ。
    続きの位置 = コミュニティごとの最大の ID（post・comment 別）。投稿者は actor_id の sha256。bot のアカウントの投稿は採らない。"""

    def read(self, cursor: dict | None) -> Iterator[Batch]:
        state = dict(cursor or {})
        for c in self.settings.get("communities") or []:
            base, name = c["base"].rstrip("/"), c["name"]
            items = []
            for kind in ("post", "comment"):
                key = f"{base}/c/{name}#{kind}"
                body = self.http.get_json(self.name, f"{base}/api/v3/{kind}/list?community_name={name}&sort=New&limit=50&type_=All")
                rows = (body or {}).get(f"{kind}s") or []
                since = int(state.get(key, 0))
                for r in rows:
                    o, cr = r.get(kind) or {}, r.get("creator") or {}
                    if int(o.get("id") or 0) <= since or o.get("deleted") or o.get("removed") or cr.get("bot_account"):
                        continue
                    text = plain((o.get("name") or "") + "\n" + (o.get("body") or "") if kind == "post" else o.get("content")).strip()[:4000]
                    at = when(o.get("published"))
                    if not text or not at:
                        continue
                    items.append(SourceItem(self.name, o.get("ap_id") or f"{base}/{kind}/{o['id']}", at,
                                            {"text": text, "author": actor(base, cr.get("actor_id")), "url": o.get("ap_id"), "lang": detect(text),
                                             "kind": kind, **({"appid": str(c["appid"])} if c.get("appid") else {})}, None))
                if rows:
                    state[key] = max([int((r.get(kind) or {}).get("id") or 0) for r in rows] + [since])
            yield Batch(items, dict(state))


class MastodonTags(SourceReader):
    """Mastodon のハッシュタグの公開の流れ（キー不要）。記述の base と tags。前回より新しい投稿だけ（続きの位置 = タグごとの最大の ID）。
    宣伝の自動投稿が多いので、bot のアカウントと、本文が URL だけの投稿は採らない。"""

    def read(self, cursor: dict | None) -> Iterator[Batch]:
        import urllib.parse
        state = dict(cursor or {})
        base = self.settings["base"].rstrip("/")
        for tag in self.settings.get("tags") or []:
            key = f"{base}#{tag}"
            since = state.get(key)
            q = f"{base}/api/v1/timelines/tag/{urllib.parse.quote(tag)}?limit=40" + (f"&since_id={since}" if since else "")
            rows = self.http.get_json(self.name, q) or []
            items = []
            for r in rows if isinstance(rows, list) else []:
                acc = r.get("account") or {}
                text = plain(r.get("content"))
                if acc.get("bot") or len(re.sub(r"https?://\S+|#\S+", "", text).strip()) < 15:
                    continue
                items.append(SourceItem(self.name, r["id"] if "/" not in str(r["id"]) else hashlib.sha256(r["id"].encode()).hexdigest()[:24],
                                        when(r.get("created_at")) or datetime.now(timezone.utc),
                                        {"text": text[:4000], "author": actor(base, acc.get("url") or acc.get("id")), "url": r.get("url"),
                                         "lang": (r.get("language") or detect(text))}, None))
            if isinstance(rows, list) and rows:
                state[key] = max((str(r["id"]) for r in rows), key=lambda x: (len(x), x))
            yield Batch(items, dict(state))


class HatenaComments(SourceReader):
    """はてなブックマークのコメント（公式のエントリー情報取得 API /entry/json/。キー不要。robots の Crawl-delay: 5 を守る。台帳の hatena_bookmark_comments）。
    ゲームの記事は記述の feeds（各誌の RSS）から見つけて覚え、記事の時刻から recheck_hours（例: 12・72 時間）の時点で 1 回ずつコメントを読む。
    1 件 = コメントのあるブックマーク 1 つ（言語 ja）。同定には記事の題名を添える（link_title）。利用者名は持たない（sha256 の先頭 16 桁）。"""
    _last = 0.0

    def _wait(self) -> None:
        import time
        left = float(self.settings.get("crawl_delay", 5)) - (time.monotonic() - self._last)
        if left > 0:
            time.sleep(left)
        self._last = time.monotonic()

    def read(self, cursor: dict | None) -> Iterator[Batch]:
        import time
        import urllib.parse
        state = dict(cursor or {})
        arts: dict = dict(state.get("articles") or {})
        for f in self.settings.get("feeds") or []:
            body = self.http.get_text(self.name, f)
            try:
                for e in parse_feed(body or "<x/>"):
                    if e["url"] and e["url"] not in arts:
                        arts[e["url"]] = {"title": plain(e["title"]), "at": e["at"].timestamp(), "done": 0}
            except ET.ParseError:
                continue
        hours = [float(h) for h in self.settings.get("recheck_hours", [12, 72])]
        now = time.time()
        items: list[SourceItem] = []
        for url, a in list(arts.items()):
            age = (now - a["at"]) / 3600
            if a["done"] >= len(hours) or age < hours[a["done"]]:
                continue
            self._wait()
            d = self.http.get_json(self.name, "https://b.hatena.ne.jp/entry/json/?url=" + urllib.parse.quote(url, safe=""))
            a["done"] = sum(1 for h in hours if age >= h)
            for b in (d or {}).get("bookmarks") or []:
                c = (b.get("comment") or "").strip()
                at = None
                try:
                    at = datetime.strptime(b.get("timestamp") or "", "%Y/%m/%d %H:%M").replace(tzinfo=timezone(timedelta(hours=9)))
                except ValueError:
                    pass
                if c and at:
                    uid = hashlib.sha256(f"hatena:{b.get('user')}".encode()).hexdigest()[:16]
                    items.append(SourceItem(self.name, hashlib.sha256(f"{url}#{b.get('user')}".encode()).hexdigest()[:24], at,
                                            {"text": c[:2000], "link_title": a["title"], "author": uid, "lang": "ja", "url": url}, None))
        keep = {u: a for u, a in arts.items() if now - a["at"] < 10 * 86400}     # 10 日より古い記事は忘れる
        yield Batch(items, {"articles": keep})
