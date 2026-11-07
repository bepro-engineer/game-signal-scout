"""投稿の言語のヒント（Bluesky の受信が使う。本番で使う）。本格的な Language Area の判定器ではない。

結果は言語コード / und / uncertain。und・uncertain は Language Area として数えない（INV-009）。
"""
from __future__ import annotations

import re


_KANA = re.compile(r"[぀-ヿ]")
_HANGUL = re.compile(r"[가-힯ᄀ-ᇿ]")
_HAN = re.compile(r"[一-鿿]")
_LETTER = re.compile(r"\w", re.UNICODE)
_URL = re.compile(r"https?://\S+|\S+\.\S+/\S*")
_TAG = re.compile(r"[#＃]\S+|@\S+")


def detect(text: str, min_prob: float = 0.8, hint: str | None = None) -> tuple[str, float, str]:
    """(言語, 確信度, 方法) を返す。方法は script / langid / hint / none。
    hint = 文脈の言語（同じコメント欄の主な言語など）。短くて確信度が足りない文でも、判定器の第 1 候補が hint と一致するときだけ hint を採る
    （一致しなければ uncertain のまま。文脈だけで決めない）。"""
    t = _TAG.sub(" ", _URL.sub(" ", text)).strip()
    if not _LETTER.search(t):
        return ("und", 0.0, "none")
    if _KANA.search(t):
        return ("ja", 1.0, "script")
    if _HANGUL.search(t):
        return ("ko", 1.0, "script")
    lang, prob = _classify(t)
    if _HAN.search(t) and lang not in ("zh", "ja"):
        return ("uncertain", prob, "langid")
    if prob < min_prob:
        return (hint, prob, "hint") if hint and lang == hint else ("uncertain", prob, "langid")
    return (lang, prob, "langid")


_ident = None


def _classify(t: str) -> tuple[str, float]:
    global _ident
    if _ident is None:
        from py3langid.langid import MODEL_DIR, MODEL_FILE, LanguageIdentifier

        _ident = LanguageIdentifier.from_modelpath(MODEL_DIR / MODEL_FILE, norm_probs=True)
    lang, prob = _ident.classify(t)
    return lang, float(prob)
