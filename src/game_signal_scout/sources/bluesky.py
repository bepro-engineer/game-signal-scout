"""Bluesky（Jetstream）の取得元。Anime の sources/bluesky を移植した。

Anime からそのまま: 再開位置の規則（resume_cursor）、フレームの解釈（parse_frame）、1 周期の受信（Stream: 重複の抑止・削除・更新で
対象外になった投稿・アカウントの停止と、その人の投稿の除外・形の違反の 1 件飛ばし）、endpoint の切り替えと時刻の巻き戻し、
本文の取り出し（discovery/text）、投稿者の HMAC（actor_key）。
Game で替えた所: 保存する投稿の条件（anime の文脈 → ゲームの文脈。GameContext）と、Game の取得元の契約（read(cursor) → Batch）。
作品の同定・宣伝などの印・言語は、取り込みではせず、正規化（services/normalize.voices。どの取得元も同じ処理）で行う。

保存（source_item）: 投稿 1 件 = 項目 1 件。payload に本文・投稿者が付けた言語のタグ・投稿者の HMAC（author。did は持たない）・リンクとその題名・
返信と引用の相手。項目の ID は at:// URI（did を含む。Anime と同じ）。
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone

from game_signal_scout.discovery.text import PostText, _dict, _list, clean, normalize, normalize
from game_signal_scout.sources.contract import Batch, SourceItem, SourceReader

SOURCE = "bluesky"
POST = "app.bsky.feed.post"
STEAM_APP = re.compile(r"store\.steampowered\.com/app/(\d{1,10})")


def bsky_url(uri: str, web: str) -> str:
    """at://<did>/app.bsky.feed.post/<rkey> → <web>/profile/<did>/post/<rkey>。投稿の URI でなければそのまま。"""
    m = re.match(r"^at://([^/]+)/app\.bsky\.feed\.post/([^/]+)$", uri or "")
    return f"{web.rstrip('/')}/profile/{m.group(1)}/post/{m.group(2)}" if m else uri


def _reply_refs(record: dict) -> dict:
    """返信の根・返信の相手・引用した投稿（会話の構造）。形が違えば持たない。"""
    out = {}
    rep = record.get("reply") if isinstance(record, dict) else None
    if isinstance(rep, dict):
        for k in ("root", "parent"):
            u = (rep.get(k) or {}).get("uri") if isinstance(rep.get(k), dict) else None
            if isinstance(u, str) and u.startswith("at://"):
                out[f"reply_{k}"] = u
    emb = record.get("embed") if isinstance(record, dict) else None
    if isinstance(emb, dict):
        rec = emb.get("record") if emb.get("$type") in ("app.bsky.embed.record", "app.bsky.embed.recordWithMedia") else None
        if isinstance(rec, dict) and isinstance(rec.get("record"), dict):
            rec = rec["record"]
        u = rec.get("uri") if isinstance(rec, dict) else None
        if isinstance(u, str) and u.startswith("at://"):
            out["quote_of"] = u
    return out


def _external_uri(record: dict) -> str:
    emb = record.get("embed") if isinstance(record, dict) else None
    if isinstance(emb, dict):
        ext = emb.get("external") or ((emb.get("media") or {}).get("external") if isinstance(emb.get("media"), dict) else None)
        if isinstance(ext, dict) and isinstance(ext.get("uri"), str):
            return ext["uri"]
    return ""


def build_url(endpoint: str, collections: list[str], cursor: int | None) -> str:
    from urllib.parse import urlencode
    q: list[tuple[str, str]] = [("collections", c) for c in collections]
    if cursor is not None:
        q.append(("cursor", str(cursor)))
    return endpoint + ("?" + urlencode(q) if q else "")


def resume_cursor(target: str, cursor_endpoint: str | None, last_seq: int | None, last_time_us: int | None,
                  rewind_seconds: float, force_time: bool = False) -> tuple[int | None, str]:
    """再接続の再開位置（Anime と同じ）。(cursor, 方式)。cursor は inclusive・at-least-once。
    - 同じ endpoint: seq（"seq"）/ 別の endpoint・seq が古すぎた: 時刻 − rewind（"time"）/ 時刻の記録がない: seq（"seq_unverified"）/
      再開位置がない: live tail の先頭（"live"）"""
    if last_seq is None and last_time_us is None:
        return None, "live"
    if not force_time and last_seq is not None and cursor_endpoint in (None, target):
        return last_seq, "seq"
    if last_time_us is not None:
        return last_time_us - int(rewind_seconds * 1_000_000), "time"
    if force_time:
        return None, "live"
    return last_seq, "seq_unverified"


@dataclass
class Event:
    kind: str            # commit / account / identity / sync / info / other
    seq: int | None
    did: str
    time: str
    operation: str = ""
    collection: str = ""
    rkey: str = ""
    cid: str = ""
    record: dict | None = None
    account: dict | None = None
    witnessed_at: str = ""

    @property
    def time_us(self) -> int | None:
        return time_to_us(self.witnessed_at or self.time)

    @property
    def uri(self) -> str:
        return f"at://{self.did}/{self.collection}/{self.rkey}"


def parse_frame(frame: str | bytes) -> Event | None:
    env = json.loads(frame)
    if env.get("$type") != "message":
        return None
    p = env.get("payload") or {}
    ptype = p.get("$type", "")
    kind = ptype.rsplit("#", 1)[-1] if "#" in ptype else "other"
    if kind not in ("commit", "account", "identity", "sync", "info"):
        kind = "other"
    return Event(kind=kind, seq=p.get("seq"), did=p.get("did", ""), time=p.get("time", ""), operation=p.get("operation", ""),
                 collection=p.get("collection", ""), rkey=p.get("rkey", ""), cid=p.get("cid", ""), record=p.get("record"),
                 account=p.get("account"), witnessed_at=p.get("witnessedAt") or "")


def time_to_us(s: str | None) -> int | None:
    d = parse_created_at(s)
    return None if d is None else int(d.timestamp()) * 1_000_000 + d.microsecond


def occurred_at(row: dict) -> datetime:
    """発言の時刻: 投稿者の申告（createdAt）と受信の時刻の早いほう（Bluesky の AppView の sortAt と同じ考え方）。
    申告は端末の時計の値で、未来の時刻もある（2026-11-08 の本番の受信で 11,628 件中 23 件が受信より 5 分以上先）。未来の発言を「最新」に数えない。
    過去の日付の申告（取り込み）はそのまま過去に置き、最近の発言に数えない。"""
    c, r = row.get("created_at"), row["received_at"]
    return min(c, r) if c else r


def parse_created_at(s: str | None) -> datetime | None:
    if not s or not isinstance(s, str):
        return None
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _identity(ev: Event) -> tuple:
    if ev.kind == "commit":
        return ("commit", ev.did, ev.collection, ev.rkey, ev.operation, ev.cid)
    return (ev.kind, ev.did, ev.witnessed_at or ev.time)


class GameContext:
    """ゲームの文脈の判定（Game 固有。Anime の ContextFilter の代わり）。Steam のストアのリンク、またはゲームの語（config/sources.toml
    [bluesky] context_words。検証S・T と同じ語）があれば保存する。作品を名指ししているかは、ここでは見ない（正規化で同定する）。"""

    def __init__(self, words: list[str]):
        ascii_words = [re.escape(normalize(w)) for w in words if w.isascii()]
        self.cjk = [normalize(w) for w in words if not w.isascii()]
        self.re = re.compile(r"(?<![\w])(" + "|".join(ascii_words) + r")(?![\w])") if ascii_words else None

    def match(self, pt: PostText, link: str) -> bool:
        if STEAM_APP.search(pt.text) or STEAM_APP.search(link):
            return True
        t = normalize(" ".join((pt.text, pt.link_title, " ".join(pt.tags))))
        return bool((self.re and self.re.search(t)) or any(w in t for w in self.cjk))


@dataclass
class Stream:
    """受信した event を、保存する投稿（rows）・削除（gone）・アカウントの停止（actors_gone）に分ける（Anime の Stream と同じ手順。DB には書かない）。"""
    context: GameContext
    last_seq: int | None = None
    last_time_us: int | None = None
    endpoint: str | None = None
    recent_seconds: float = 180.0
    rows: dict = field(default_factory=dict)
    gone: list = field(default_factory=list)
    actors_gone: list = field(default_factory=list)
    malformed: list = field(default_factory=list)

    def __post_init__(self) -> None:
        self._dedup_seq = self.last_seq
        self._recent: dict[tuple, int] = {}
        self._inactive: set[str] = set()

    def handle(self, ev: Event, now: float | None = None, endpoint: str | None = None) -> str:
        now = time.time() if now is None else now
        if ev.kind == "info":
            return "info"
        if endpoint is not None and endpoint != self.endpoint:
            if self.endpoint is not None:
                self._dedup_seq = None
            self.endpoint = endpoint
        if ev.seq is not None and self._dedup_seq is not None and ev.seq <= self._dedup_seq:
            return "duplicate"
        tus, ident = ev.time_us, _identity(ev)
        if ident in self._recent:
            self._advance(ev.seq, tus)
            return "duplicate"
        if tus is not None:
            self._recent[ident] = tus
            if len(self._recent) > 2000 and len(self._recent) % 1000 == 0:
                floor = tus - int(self.recent_seconds * 1_000_000)
                self._recent = {k: v for k, v in self._recent.items() if v >= floor}
        self._advance(ev.seq, tus)
        if ev.kind == "account":
            acct = ev.account or {}
            if acct.get("active") is False:
                self._inactive.add(ev.did)
                for uri in [u for u, row in self.rows.items() if row["did"] == ev.did]:
                    del self.rows[uri]
                self.actors_gone.append((ev.did, f"account_{acct.get('status', 'inactive')}"))
            elif acct.get("active") is True:
                self._inactive.discard(ev.did)
            return "account"
        if ev.kind != "commit":
            return ev.kind
        if ev.collection != POST:
            return "other_commit"
        if ev.did in self._inactive:
            return "inactive_account"
        if ev.operation == "delete":
            self._erase(ev.uri, "deleted")
            return "delete"
        if not ev.record:
            return ev.operation or "create"
        is_update = ev.operation == "update"
        try:
            pt = extract_post_text(ev.record)
        except MalformedRecordError as e:
            self.malformed.append({"seq": ev.seq, "uri": ev.uri, "error": f"{type(e).__name__}: {e}"[:200]})
            if is_update:
                self._erase(ev.uri, "update_malformed")
            return "malformed"
        link = clean(_external_uri(ev.record))
        if not self.context.match(pt, link):
            if is_update:
                self._erase(ev.uri, "update_unmatched")
            return "unmatched"
        self.rows[ev.uri] = {
            "did": ev.did, "cid": ev.cid, "seq": ev.seq or 0, "received_at": datetime.fromtimestamp(now, tz=timezone.utc),
            "created_at": parse_created_at(ev.record.get("createdAt")), "text": pt.text, "tags": pt.tags, "link_title": pt.link_title or None,
            "link": link or None, "langs_tag": pt.langs,
            "text_hash": hashlib.sha256(pt.text.encode()).hexdigest(), "refs": _reply_refs(ev.record)}
        return "buffered"

    def forget_seq(self) -> None:
        self._dedup_seq = None

    def _erase(self, uri: str, reason: str) -> None:
        self.rows.pop(uri, None)
        self.gone.append((uri, reason))

    def _advance(self, seq: int | None, tus: int | None) -> None:
        if seq is not None:
            self.last_seq = self._dedup_seq = seq
        if tus is not None:
            self.last_time_us = tus


class ForeignCursorError(Exception):
    """seq の再開位置がこの instance の番号でない。時刻の cursor で読み直す。"""


class Bluesky(SourceReader):
    """1 回の read で batch_seconds の間だけ受信し、束を 1 つ返す（Anime の discover の 1 周期と同じ）。"""

    def __init__(self, settings: dict, http):
        super().__init__(settings, http)
        self.endpoints = list(settings["endpoints"])
        self.subprotocol = settings.get("subprotocol", "xrpc.v1.json")
        self.collections = list(settings.get("collections") or [POST])
        self.batch_seconds = float(settings.get("batch_seconds", 30))
        self.idle_seconds = float(settings.get("idle_seconds", 20))
        self.rewind = float(settings.get("switch_rewind_seconds", 60))
        self.context = GameContext(list(settings.get("context_words") or []))
        self.log: list[dict] = []

    def _connect(self, url: str):
        from websockets.sync.client import connect
        return connect(url, subprotocols=[self.subprotocol], max_size=None, open_timeout=15)

    def read(self, cursor: dict | None) -> Iterator[Batch]:
        from game_signal_scout.actor_key import author_hash
        cur = dict(cursor or {})
        st = Stream(self.context, last_seq=cur.get("last_seq"), last_time_us=cur.get("last_time_us"), endpoint=cur.get("endpoint"),
                    recent_seconds=max(180.0, self.rewind * 3))
        start = cur.get("endpoint") if cur.get("endpoint") in self.endpoints else self.endpoints[0]
        order = self.endpoints[self.endpoints.index(start):] + self.endpoints[:self.endpoints.index(start)]
        force_time, t0, n_frames, used, last_error = bool(cur.get("force_time")), time.time(), 0, None, None
        for ep in order:
            c, how = resume_cursor(ep, cur.get("endpoint"), cur.get("last_seq"), cur.get("last_time_us"), self.rewind, force_time)
            if how in ("time", "live"):
                st.forget_seq()
            try:
                with self._connect(build_url(ep, self.collections, c)) as ws:
                    used = ep
                    while time.time() - t0 < self.batch_seconds:
                        try:
                            frame = ws.recv(timeout=min(self.idle_seconds, max(0.1, self.batch_seconds - (time.time() - t0))))
                        except TimeoutError:
                            break
                        ev = parse_frame(frame)
                        n_frames += 1
                        if ev is not None:
                            if how in ("seq", "seq_unverified") and ev.seq is not None and ev.seq < c:
                                raise ForeignCursorError(f"seq {ev.seq} < cursor {c}")
                            st.handle(ev, time.time(), endpoint=ep)
                self._log(ep, 200, True, t0, None)
                break
            except Exception as e:  # noqa: BLE001 — 保持範囲より古い seq（HTTP 400）は時刻の cursor に、ほかは次の endpoint に
                status = getattr(getattr(e, "response", None), "status_code", None)
                self._log(ep, status, False, t0, f"{type(e).__name__}: {str(e)[:120]}")
                last_error = e
                if isinstance(e, ForeignCursorError) or (status == 400 and how in ("seq", "seq_unverified")):
                    force_time, used = True, None
                    cur = {**cur, "force_time": True}
                continue
        if used is None:
            if force_time and not (cursor or {}).get("force_time"):
                yield Batch([], {**cur, "force_time": True})   # 別の instance の seq だった: 次の回は時刻の cursor で読む（Anime と同じ）
                return
            raise ConnectionError(f"どの endpoint にも接続できなかった: {last_error}")
        items = [SourceItem(SOURCE, uri, occurred_at(row), _payload(row, author_hash(row["did"])), row["cid"] or None)
                 for uri, row in st.rows.items()]
        nxt = {"endpoint": st.endpoint or used, "last_seq": st.last_seq, "last_time_us": st.last_time_us,
               "frames": n_frames, "malformed": len(st.malformed)}
        yield Batch(items, nxt, gone=[u for u, _ in st.gone], actors_gone=[author_hash(d) for d, _ in st.actors_gone])

    def _log(self, ep: str, status, ok: bool, t0: float, err) -> None:
        from urllib.parse import urlsplit
        self.log.append({"ts": datetime.now(timezone.utc), "source": SOURCE, "host": urlsplit(ep).netloc, "endpoint": urlsplit(ep).path, "status": status,
                         "ok": ok, "ms": int((time.time() - t0) * 1000), "bytes": None, "error": err})


def _payload(row: dict, author: str) -> dict:
    """保存する形（did は持たない。時刻は ISO の文字列）。"""
    out = {k: v for k, v in row.items() if k not in ("did", "received_at", "created_at", "seq")}
    out["author"] = author
    out["created_at"] = row["created_at"].isoformat() if row["created_at"] else None
    out["received_at"] = row["received_at"].isoformat()
    return out


# ---- この取得元の投稿の形（record）の読み方（共通の部品から移した。取得元ごとの読み方は sources/ に置く）
# record は投稿者が書く JSON で、形どおりとは限らない。照合に欠かせない部分（record が object・text が文字列）の違反は MalformedRecordError（その投稿だけ飛ばす）。
# 任意の部分（embed・facets・langs・リンクの題名）の形の違いは「ない」ものとして扱う。
_HASHTAG_RE = re.compile(r"(?:^|\s)[#＃]([^\s#＃.,!?、。！？]+)")


class MalformedRecordError(ValueError):
    """投稿の record が、照合に欠かせない部分で想定の形と違う（入力データの問題。プログラムの不具合ではない）。"""


def extract_post_text(record: dict) -> PostText:
    if not isinstance(record, dict):
        raise MalformedRecordError(f"record が object ではない（{type(record).__name__}）")
    raw = record.get("text")
    if raw is not None and not isinstance(raw, str):
        raise MalformedRecordError(f"text が文字列ではない（{type(raw).__name__}）")
    text = clean(raw)
    tags: list[str] = []
    for facet in _list(record.get("facets")):
        for feat in _list(_dict(facet).get("features")):
            feat = _dict(feat)
            tag = clean(feat.get("tag"))
            if feat.get("$type") == "app.bsky.richtext.facet#tag" and tag:
                tags.append(tag)
    for m in _HASHTAG_RE.finditer(text):
        tags.append(m.group(1))
    # embed は lexicon では 1 つの object。配列など形の違うものは「埋め込みなし」として扱う
    embed = _dict(record.get("embed"))
    etype = embed.get("$type", "")
    etype = etype if isinstance(etype, str) else ""
    link_title = ""
    has_link = False
    if etype == "app.bsky.embed.external":
        has_link = True
        link_title = clean(_dict(embed.get("external")).get("title"))
    elif etype == "app.bsky.embed.recordWithMedia":
        media = _dict(embed.get("media"))
        if media.get("$type") == "app.bsky.embed.external":
            has_link = True
            link_title = clean(_dict(media.get("external")).get("title"))
    has_media = etype in ("app.bsky.embed.images", "app.bsky.embed.video") or (
        etype == "app.bsky.embed.recordWithMedia"
    )
    seen: set[str] = set()
    uniq_tags = []
    for t in tags:
        n = normalize(t)
        if n not in seen:
            seen.add(n)
            uniq_tags.append(t)
    return PostText(
        text=text,
        tags=uniq_tags,
        link_title=link_title,
        langs=[clean(x) for x in _list(record.get("langs")) if isinstance(x, str)],
        has_link=has_link,
        has_media=has_media,
    )
