"""作品の同定（Game 固有）: 発言 → Steam の app ID。

1. Steam のストアのリンク（store.steampowered.com/app/<id>）があれば、その app ID（複数なら最初のもの）。
2. なければ題名の一致: 作品の辞書（ProtonDB の報告にある作品の題名）を、語の並び（NFKC・casefold の後の \\w+ の列）で照合し、最も長い一致を採る。
   2026-11-07 の実データ（2 分の受信・160 件）で、緩い規則は 65 件を同定し、目視ではほぼすべてが誤り（Back・Door・Pressure など
   1 語の題名、スポーツの "game"・"play"、ラジオの "Now playing"）だった。そのため次をすべて満たすときだけ採る:
   - 題名が 2 語以上で、min_title_chars 以上（1 語の題名は辞書に入れない。Steam のリンクでだけ同定する）
   - 本文の中の大文字・小文字が題名と同じ（題名は固有名詞として書かれる）
   - 題名の部分の外に、ゲームに固有の文脈の語（title_context_words。"play"・"season" のようなスポーツと共通の語は入れない）がある
     （2 回目の測定で "Puzzle Game"・"Football Game" が題名の中の "game" で通ったため）
   - 記述の ambiguous_titles に入っていない
"""
from __future__ import annotations

import re
import unicodedata

from game_signal_scout.discovery.text import normalize

WORD = re.compile(r"\w+")
MAX_WORDS = 12


def words(s: str) -> tuple[str, ...]:
    return tuple(WORD.findall(normalize(s or "")))


def cased_words(s: str) -> tuple[str, ...]:
    return tuple(WORD.findall(unicodedata.normalize("NFKC", s or "")))


CJK = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]")   # かな・漢字・ハングル（語を空白で区切らない言語）
CJK_MIN = 4


class TitleIndex:
    def __init__(self, titles: list[tuple[str, str]], ambiguous: list[str], context_words: list[str], min_chars: int = 8, game_only: bool = False):
        self.by_words: dict[tuple[str, ...], tuple[str, str]] = {}
        self.by_cjk: dict[str, tuple[str, str]] = {}     # 空白で区切らない言語の題名（部分の文字列で照合する）
        self.title_of = {str(a): t for a, t in titles}
        self.game_only = game_only                       # ゲームだけの掲示板・部屋（文脈の語を求めない）
        for appid, title in titles:
            w = words(title)
            if CJK.search(title or ""):
                key = "".join(w)
                if len(key) >= CJK_MIN:
                    self.by_cjk.setdefault(key, (str(appid), title))
                continue
            if 2 <= len(w) <= MAX_WORDS and len(" ".join(w)) >= min_chars:
                self.by_words.setdefault(w, (str(appid), title))
        self.ambiguous = {words(t) for t in ambiguous}
        self.context = {w for t in context_words for w in [words(t)] if w}
        self.cjk_context = [normalize(t) for t in context_words if not t.isascii()]

    def has_context(self, toks: tuple[str, ...], text: str) -> bool:
        """文脈の語があるか（呼ぶ側は、題名の部分を除いた語の列を渡す。"Puzzle Game" の "game" を文脈に数えない）。"""
        n = len(toks)
        for c in self.context:
            k = len(c)
            if any(toks[i:i + k] == c for i in range(n - k + 1)):
                return True
        t = normalize(text)
        return any(w in t for w in self.cjk_context)

    def match_cjk(self, text: str) -> tuple[str, str] | None:
        """空白で区切らない言語の題名: 本文（記号・空白を除いた列）に題名が含まれるか。最も長い題名を採る。"""
        if not self.by_cjk or not CJK.search(text or ""):
            return None
        flat = "".join(words(text))
        best = max((k for k in self.by_cjk if k in flat), key=len, default=None)
        if best is None or best in {"".join(a) for a in self.ambiguous}:
            return None
        if not self.game_only and not self.has_context((), flat.replace(best, " ")):
            return None
        return self.by_cjk[best]

    def match(self, text: str) -> tuple[str, str] | None:
        hit = self.match_word(text)
        return hit or self.match_cjk(text)

    def match_word(self, text: str) -> tuple[str, str] | None:
        toks, cased = words(text), cased_words(text)
        if len(toks) != len(cased):        # casefold で語の数が変わる珍しい文字列は照合しない
            return None
        best = None
        for i in range(len(toks)):
            for k in range(min(MAX_WORDS, len(toks) - i), 1, -1):
                hit = self.by_words.get(toks[i:i + k])
                if hit and cased[i:i + k] == cased_words(hit[1]) and (best is None or k > best[0]):
                    best = (k, toks[i:i + k], hit, i)
                    break
        if best is None:
            return None
        k, w, hit, i = best
        rest = toks[:i] + ("\x00",) + toks[i + k:]
        rest_text = normalize(text).replace(" ".join(w), " ")
        if w in self.ambiguous or (not self.game_only and not self.has_context(rest, rest_text)):
            return None
        return hit


def identify(payload: dict, index: TitleIndex) -> tuple[str | None, str | None, str | None]:
    """(appid, 題名, 方法)。同定できなければ (None, None, None)。"""
    steam = payload.get("steam_appids") or []
    if steam:
        appid = str(steam[0])
        return appid, index.title_of.get(appid), "steam_link"
    text = " ".join(x for x in (payload.get("text"), payload.get("link_title"), " ".join(payload.get("tags") or [])) if x)
    hit = index.match(text)
    return (hit[0], hit[1], "title") if hit else (None, None, None)


def version(titles: list[tuple[str, str]], ambiguous: list[str], context_words: list[str], min_chars: int, game_only: bool) -> str:
    """同定の版: このファイル（規則）・作品の辞書・記述（曖昧な題名・文脈の語・最小の字数・ゲームだけの場か）の指紋。どれかが変われば作り直す。"""
    import hashlib
    from pathlib import Path
    h = hashlib.sha256(Path(__file__).read_bytes())
    for a, t in sorted((str(a), str(t)) for a, t in titles):
        h.update(f"{a}\t{t}\n".encode())
    h.update(repr((sorted(ambiguous), sorted(context_words), min_chars, game_only)).encode())
    return h.hexdigest()[:16]
