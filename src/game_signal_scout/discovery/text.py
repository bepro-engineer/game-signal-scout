"""投稿レコードから、照合に使う文字列を取り出す。

投稿者本人の本文・ハッシュタグ・リンクカードの題名を区別して返す（REQ-TXT-003）。

投稿の record は投稿者が書く JSON で、lexicon の形どおりとは限らない（Jetstream は形を検査しない）。
2026-10-04 15:13 UTC に embed が配列の投稿が届き、ここで例外になって取り込みが止まり続けた。
- 照合に欠かせない部分（record が object・text が文字列）の形の違反は MalformedRecordError（その投稿だけ飛ばして数える）。
- 任意の部分（embed・facets・langs・リンクカードの題名）の形の違いは「ない」ものとして扱い、投稿は残す。
- 文字列は DB に書ける形（NUL・対のない surrogate を除く）にする。
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

_HASHTAG_RE = re.compile(r"(?:^|\s)[#＃]([^\s#＃.,!?、。！？]+)")


class MalformedRecordError(ValueError):
    """投稿の record が、照合に欠かせない部分で想定の形と違う（入力データの問題。プログラムの不具合ではない）。"""


def clean(s) -> str:
    """DB に書ける文字列にする（PostgreSQL の text は NUL を持てない。対のない surrogate は UTF-8 にできない）。文字列でなければ空。"""
    if not isinstance(s, str):
        return ""
    if "\x00" in s:
        s = s.replace("\x00", "")
    try:
        s.encode("utf-8")
    except UnicodeEncodeError:
        s = s.encode("utf-8", "replace").decode("utf-8")
    return s


def _dict(x) -> dict:
    return x if isinstance(x, dict) else {}


def _list(x) -> list:
    return x if isinstance(x, list) else []


def normalize(s: str) -> str:
    """照合のための正規化（NFKC と casefold）。位置の記録には使わない。"""
    return unicodedata.normalize("NFKC", s).casefold()


@dataclass
class PostText:
    text: str = ""
    tags: list[str] = field(default_factory=list)
    link_title: str = ""
    langs: list[str] = field(default_factory=list)
    has_link: bool = False
    has_media: bool = False


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
