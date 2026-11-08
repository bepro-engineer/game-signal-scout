"""今日の兆しの抜粋と原文の照合（DB も LLM も使わない純粋な関数）。LLM が返した抜粋が原文の一字一句か、文として完結しているかを確かめ、
少しの写し間違いは原文の言葉に直す（ADR 0045・0046。docs/TODAYS-SIGNAL-PAGES.md §0.6）。ops/dashboard_digest の段 3 が使う。"""
from __future__ import annotations

import re


EXCERPT_MAX = 45                    # 画面に出す抜粋の上限（日本語・中国語・韓国語など。ADR 0044 決定 4）
EXCERPT_MAX_LATIN = 80              # ラテン文字の抜粋の上限（ADR 0046: 英語の 45 字は約 8 語で主張を運べない。2026-10-14 の実測で、的確な 66 字の抜粋が上限で落ちた）


def max_excerpt_length(t: str) -> int:
    """抜粋の上限（文字の半分以上がラテン文字なら EXCERPT_MAX_LATIN）。"""
    latin = sum(1 for ch in t if ch.isascii() and ch.isalpha())
    letters = sum(1 for ch in t if ch.isalpha())
    return EXCERPT_MAX_LATIN if letters and latin * 2 >= letters else EXCERPT_MAX
EXCERPT_MIN_CONTENT = 8             # 抜粋の中身の文字数（記号・「……」を除く）。「何なんだろうなあ……」のような中身のない抜粋を根拠にしない
def normalize(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def content_length(s: str) -> int:
    """抜粋の中身の文字数（文字と数字だけ。記号・空白・「……」・絵文字を数えない。日本語の文末の「なあ」「ね」などの間投詞も数えない）。"""
    t = re.sub(r"(なあ|なぁ|ね|よ|わ)+$", "", re.sub(r"[^\w]", "", s or ""))
    return len(t)


def strip_brackets(s: str) -> str:
    return s.replace("「", "『").replace("」", "』")


def verbatim_span(claimed: str, text: str) -> str | None:
    """抜粋を原文の一字一句の部分にする。そのまま含まれていればそのまま、写し損ね（1〜2 字の違い・省略記号）なら、原文の中で最も長く一致する部分
    （中身 EXCERPT_MIN_CONTENT 字以上・EXCERPT_MAX 字以内）を返す。見つからなければ None（捨てる）。原文にない言葉は作らない。"""
    c = (claimed or "").strip().strip("「」\"“”…").strip()
    if not c:
        return None
    if c in text:
        return with_sentence_end(c, text)
    from difflib import SequenceMatcher
    m = SequenceMatcher(None, text, c, autojunk=False).find_longest_match(0, len(text), 0, len(c))
    cand = text[m.a:m.a + m.size].strip(" 、。,.!！?？")
    return with_sentence_end(cand, text) if m.size >= len(c) * 0.6 and content_length(cand) >= EXCERPT_MIN_CONTENT else None


END_PUNCT = "…‥・.。?？!！"
SENT_END = re.compile(r"[。．.!！?？…‥♪]$|[\U0001F300-\U0001FAFF\u2600-\u27BF]$")


def _boundary(text: str, j: int) -> bool:
    """原文の j の位置が文の切れ目か（文末・改行・ハッシュタグ・リンクの前・空白で区切られた日本語の文の終わり）。"""
    if j >= len(text):
        return True
    rest = text[j:]
    if rest[0] in "。．.!！?？…‥\n♪":
        return rest[0] != "." or not rest[1:2].isalnum()
    if re.match(r"\s*(#|https?://|$)", rest):
        return True
    cjk = re.search(r"[\u3040-\u30ff\u4e00-\u9fff\uac00-\ud7af]", text[max(0, j - 3):j])
    return bool(cjk and rest[0] in " \u3000")


def _starts(text: str, i: int) -> bool:
    """原文の i の位置が文・節の始まりか（原文の先頭・改行の後・文末の記号・読点・閉じ括弧の後・空白で区切られた日本語の文の後）。
    節の途中（「白娘娘|もそれが」の「も」）からは始めない。"""
    if i <= 0 or text[i - 1] == "\n":
        return True
    before = text[:i].rstrip(" \t\u3000")
    if not before or before[-1] in "。．!！?？…‥♪」』）)、，;；：\n":
        return True
    if before[-1] in ".,:" and text[i - 1] in " \t":   # ラテン文字の句読点は後ろに空白があるときだけ（「26,2026」「3.5」の途中から始めない）
        return True
    cjk = re.search(r"[\u3040-\u30ff\u4e00-\u9fff\uac00-\ud7af]$", before)
    return bool(cjk and text[i - 1] in " \u3000")


def with_sentence_end(c: str, text: str) -> str | None:
    """抜粋を文の始まりから文の切れ目まで含める（ADR 0052: 途中で切れた引用を完成した声として出さない。2026-10-12「夕焼けに染まるプールサイドで、」）。
    抜粋の直後が文の切れ目ならそのまま（直後の文末の記号「？」「…」は含める: 問いかけが否定に読めないように）。切れ目でなければ、上限の長さの中で
    次の切れ目まで伸ばす。抜粋が文の途中から始まるときは、上限の長さの中で文の始まりまで遡る（#62: 2026-10-31「もそれが判っているから、…」は
    主語の「白娘娘」を落とした切り出しで、何の話か読めなかった）。届かなければ None（使わない）。原文にない言葉は足さない。"""
    i = text.find(c)
    if i < 0:
        return None
    j = i + len(c)
    if not _starts(text, i):   # 途中から始まる抜粋が改行をまたぐなら、改行の後の行から（10/26「…26,2026⏎⏎It was …」の日付の切れ端を引用にしない）
        nl = text.rfind("\n", i, j)
        if nl >= 0 and content_length(text[nl + 1:j]) >= EXCERPT_MIN_CONTENT:
            i = nl + 1
    if not _starts(text, i):
        k = i - 1
        while k > 0 and not _starts(text, k) and j - k < max_excerpt_length(c):
            k -= 1
        if not _starts(text, k) or j - k > max_excerpt_length(c):
            return None
        i = k
    while j < len(text) and text[j] in END_PUNCT and j - i < max_excerpt_length(c):
        j += 1
    out = text[i:j]
    if out.rstrip()[-1:] in "、，,:：;；" or not (SENT_END.search(out.rstrip()) or _boundary(text, j)):
        k = j
        while k < len(text) and k - i < max_excerpt_length(out) and not _boundary(text, k):
            k += 1
        while k < len(text) and text[k] in END_PUNCT and k - i < max_excerpt_length(out):
            k += 1
        out = text[i:k].rstrip()
        if not (SENT_END.search(out) or _boundary(text, k)) or out[-1:] in "、，,:：;；":
            return None
    return out if len(out) <= max_excerpt_length(out) else None
