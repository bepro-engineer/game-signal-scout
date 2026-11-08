"""発言の文字列の共通の部品（どの取得元にも使う）: 照合用の正規化（normalize）、DB に書ける形（clean）、発言の文字列の形（PostText: 本文・タグ・リンクの題名）。
取得元ごとの投稿の形の読み方は、その取得元の読み方（sources/）に置く。"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field



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
