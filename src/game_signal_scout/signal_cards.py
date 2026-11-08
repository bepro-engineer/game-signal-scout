"""利用者に見せる「変化のカード」（ADR 0023）。

候補の登録簿（candidate_registry）は、作品の候補の Evidence を集める。このカードは、その上で
「その候補自身の過去と比べて動いたもの」だけを、1 日分のカードにする。変化していないもの
（大きく安定した作品・一般のタグ・一人の連投・転載・アニメとの結びつきの弱い話題）は利用者に見せない。

- 数は Buffer の投稿から機械で数える。AI の解釈を数に混ぜない（INV-006）。
- 量で順位を付けない（INV-020）。カードは変化の種類と時刻で並べる。
- 作品の identity を確定しない。同じ投稿で一緒に使われた表記を 1 枚にまとめるだけ（INV-028）。
"""
from __future__ import annotations

import re
import statistics
import tomllib
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from game_signal_scout import config
from game_signal_scout.candidate_registry import candidate_key, window_start
from game_signal_scout.languages import NOT_LANGUAGE


def load_rules() -> dict:
    return tomllib.loads((config.CONFIG / "signal_cards.toml").read_text())


def load_generic() -> dict[str, str]:
    """一般の語（作品の変化として見せない語）と作品ではない候補（放送局・会社・一般句。自動の品質 Gate）→ 種類。"""
    out = {}
    for f in ("generic_terms.toml", "non_work_terms.toml"):
        d = tomllib.loads((config.CONFIG / f).read_text())
        out.update({candidate_key(t): kind for kind, terms in d["terms"].items() for t in terms})
    return out


@dataclass
class Post:
    key: str
    term: str
    method: str
    author: str
    t: datetime
    lang: str | None
    text: str | None
    uri: str
    anime: bool = False  # アニメに固有の手がかりを含む
    head: str | None = None       # 文の書き出し（text_head）。恒久履歴から読んだ投稿は本文がないのでこれを使う
    received: datetime | None = None


@dataclass
class Series:
    key: str
    variants: Counter = field(default_factory=Counter)
    methods: set = field(default_factory=set)
    by_window: dict = field(default_factory=lambda: defaultdict(list))  # window → [Post]
    agg: dict = field(default_factory=dict)       # 投稿を持たない窓の集計 window → {authors, posts, langs}（上限つきの読み込み。2026-10-10）
    stat: dict | None = None                      # 日より前の全期間の要約（history_key_stat）。None なら投稿から数える

    def authors(self, w0) -> set:
        return {p.author for p in self.by_window.get(w0, [])}

    def has(self, w0) -> bool:
        return bool(self.by_window.get(w0)) or self.agg.get(w0, {}).get("posts", 0) > 0

    def n_authors(self, w0) -> int:
        ps = self.by_window.get(w0)
        return len({p.author for p in ps}) if ps else self.agg.get(w0, {}).get("authors", 0)


    def seen_before(self, w0, windows: list) -> bool:
        if any(self.has(w) for w in windows if w < w0):
            return True
        st = self.stat
        return bool(st and st.get("first_posted_at") and st["first_posted_at"] < w0)

    def max_authors_before(self, windows: list) -> int:
        m = max((self.n_authors(w) for w in windows), default=0)
        st = self.stat
        return max(m, int(st.get("max_window_authors") or 0)) if st else m

    def before_day(self, day_start, windows: list) -> tuple[int, set, dict]:
        """日より前（観測のそろった窓）の: 言語の分かる投稿者の異なり数、言語の集合、言語ごとの投稿数。"""
        st = self.stat
        if st is not None:
            lp = {lg: n for lg, n in (st.get("before_lang_posts") or {}).items() if lg != "und"}
            return int(st.get("before_known_authors") or 0), set(lp), lp
        before = [p for w in windows if w < day_start for p in self.by_window.get(w, [])]
        return (len({p.author for p in before if _lang(p) != "und"}), {_lang(p) for p in before} - {"und"},
                dict(Counter(_lang(p) for p in before if _lang(p) != "und")))


def top_variants(s: Series, n: int) -> list[tuple[str, int]]:
    """表記を多い順に n 個（同数なら表記の文字列順。読み込みの順に依らず決定的。2026-10-10）。"""
    return sorted(s.variants.items(), key=lambda x: (-x[1], x[0]))[:n]


def post_head(p: Post) -> str:
    return p.head if p.head is not None else text_head(p.text)


def text_head(text: str | None) -> str:
    """転載・定型文を見分けるための文の書き出し（URL・記号・空白を除いた先頭 30 文字）。"""
    t = unicodedata.normalize("NFKC", text or "").casefold()
    t = re.sub(r"https?://\S+|\S+\.(com|jp|net|org|app|moe)/\S*", "", t)
    t = re.sub(r"[\s\W_]+", "", t)
    return t[:30]


def _lang(p: Post) -> str:
    return p.lang if p.lang not in NOT_LANGUAGE else "und"


def _langs(posts: list[Post]) -> dict[str, set]:
    by: dict[str, set] = defaultdict(set)
    for p in posts:
        by[_lang(p)].add(p.author)
    return by


def _anime_share(posts: list[Post]) -> float:
    authors = {p.author for p in posts}
    return len({p.author for p in posts if p.anime}) / len(authors) if authors else 0.0


def baseline_prev(w0: datetime, all_windows: list[datetime], rules: dict) -> list[datetime] | None:
    """窓 w0 と比べる直前の観測していた窓（最大 baseline_windows 個）。足りなければ None（比べられない = 基準なし）。
    候補ごとではなく観測の範囲だけで決まる（出ていない窓は 0 人として数えるため）。"""
    ch = rules["change"]
    prev = [w for w in all_windows if w < w0][-ch["baseline_windows"]:]
    return prev if len(prev) >= ch["min_baseline_windows"] else None


def detect(s: Series, all_windows: list[datetime], day_ws: list[datetime], rules: dict,
           generic: dict[str, str], observed_end: datetime | None = None, check_texts: bool = True) -> tuple[dict | None, str]:
    """候補 s が、その日に「動いた」かを判定する。(カード, 理由)。動いていなければカードは None（見せない）。
    check_texts: 文の書き出しで転載を見分ける検査をするか（本文を読まない・持たない Source は判定できないので行わない = unknown。ADR 0051）。"""
    day_posts = [p for w in day_ws for p in s.by_window.get(w, [])]
    if not day_posts:
        return None, "absent"
    if s.key in generic:
        return None, "generic:" + generic[s.key]
    ch, ind, sp, co, an = rules["change"], rules["independence"], rules["spread"], rules["continuation"], rules["anchor"]
    wh = int((day_ws[1] - day_ws[0]).total_seconds() // 3600)
    events, reasons = [], []
    for w0 in day_ws:
        posts = s.by_window.get(w0, [])
        authors = {p.author for p in posts}
        n = len(authors)
        # 比べる基準がない窓は、人数の大小より先に「基準なし」（少人数の窓も判定できない窓として扱う）
        prev = baseline_prev(w0, all_windows, rules)
        if prev is None:
            if posts:
                reasons.append("no_baseline")
            continue
        if n < ch["min_window_authors"]:
            reasons.append("small")
            continue
        base = statistics.mean(s.n_authors(w) for w in prev)
        if n < ch["surge_ratio"] * max(base, ch["baseline_floor"]):
            reasons.append("no_change")
            continue
        top_share = Counter(p.author for p in posts).most_common(1)[0][1] / len(posts)
        heads = {h for p in posts if (h := post_head(p))}
        if top_share > ind["max_top_author_share"] or (check_texts and len(heads) < ind["min_distinct_texts"]):
            reasons.append("not_independent")
            continue
        if _anime_share(posts) < an["min_anime_author_share"]:
            reasons.append("weak_anchor")
            continue
        seen_before = s.seen_before(w0, all_windows)
        rs = rules.get("resurface", {})
        before = [w for w in all_windows if w < w0]
        quiet = rs.get("quiet_windows", 2)
        resurface = (seen_before and len(before) > quiet and all(not s.has(w) for w in before[-quiet:])
                     and s.max_authors_before(before[:-quiet]) >= rs.get("min_before_authors", 2))
        events.append({"kind": "surge" if seen_before else "emergence", "resurface": resurface, "window": w0, "authors": n,
                       "baseline": base, "baseline_windows": len(prev), "quiet_windows": len(prev),
                       "anime_share": _anime_share(posts), "uris": sorted({p.uri for p in posts})})
    # 新しい言語圏（日より前の投稿者・言語は、全件を読んだときも上限つきの読み込みでも同じ値: Series.before_day）
    n_before_known, before_langs, before_lang_posts = s.before_day(day_ws[0], all_windows)
    day_authors = {p.author for p in day_posts}
    new_langs = {lg: a for lg, a in _langs(day_posts).items()
                 if lg != "und" and lg not in before_langs and len(a) >= sp["min_new_language_authors"]}
    if new_langs and n_before_known >= sp["min_before_authors"] and len(day_authors) >= sp["min_day_authors"]:
        lp = [p for p in day_posts if _lang(p) in new_langs]
        if _anime_share(lp) >= an["min_anime_author_share"]:
            first = min(p.t for p in lp)
            events.append({"kind": "new_language", "window": window_start(first, wh),
                           "langs": {lg: len(a) for lg, a in new_langs.items()},
                           "before_langs": before_lang_posts,
                           "anime_share": _anime_share(lp), "uris": sorted({p.uri for p in lp})})
        else:
            reasons.append("weak_anchor")
    if not events:
        order = ["weak_anchor", "not_independent", "no_change", "no_baseline", "small"]
        return None, next((r for r in order if r in reasons), "small")
    main = next((e for e in events if e["kind"] in ("surge", "emergence")), events[0])
    # その後: 最後まで観測できた窓だけ（観測の終わりで切れた窓は数えない）
    after = [w for w in all_windows if w > main["window"] and (observed_end is None or w + timedelta(hours=wh) <= observed_end)]
    after_n = [s.n_authors(w) for w in after]
    if len(after) < co["min_after_windows"]:
        status = "unknown"
    elif main["kind"] == "new_language":
        later = {p.author for w in after for p in s.by_window.get(w, []) if _lang(p) in main["langs"]}
        status = "continuing" if later else "faded"
    else:
        need = max(co["min_after_authors"], co["after_ratio"] * main["baseline"])
        status = "continuing" if statistics.median(after_n) >= need else "faded"
    return {"key": s.key, "events": events, "main": main, "status": status, "after": after_n,
            "day_authors": len(day_authors), "day_langs": {lg: len(a) for lg, a in _langs(day_posts).items()},
            "series": [s.n_authors(w) for w in all_windows], "variants": [v for v, _ in top_variants(s, 4)],
            "methods": sorted(s.methods), "day_uris": sorted({p.uri for p in day_posts})}, "shown"


