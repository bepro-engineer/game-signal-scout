"""Work 単位時系列レイヤーと、新しい価値ページ 4 つの判定（docs/NEW-PAGES-DESIGN.md §2.1・§2.2・§3）。

3 ページ（再燃・放送終了後・言語圏の広がり）の共通の正本。ページごとに別の履歴処理を作らない。

- DB は読まない。入力の時系列（WorkSeries）は、全取得元の共通の観測の集計（sources/observations が表 obs_work_lang_day・obs_day_state から作る）。
  表示のための集計を保存しない（要求ごとに計算し、process の中で memo する）。
- 日の単位は放送日（JST 03:00〜翌 03:00。days.day_range）。観測の状態: complete（complete な窓 4）/ partial（1〜3）/ none（0）。
  none の日は「未観測」で、基準・静かな期間・比較の期間のどれにも数えない（0 人として扱わない。ADR 0025）。
  partial の日の投稿者数は実数として扱うが、「静か」や「0 件」の証拠にはしない。
  同じ投稿に複数の extractor_version の行があれば created_at が最新の 1 行だけを使う。
- 独立性・アニメとの結びつき・急増の比・新しい言語圏の閾値は signal_cards.toml（[independence]・[anchor]・[change]・[spread]）を参照する。
  ページの閾値は config/pages.toml（値をコードに書かない）。
- 人気の順位を作らない。どの判定もその Work 自身の過去と現在を比べる。説明できない独自スコアは作らない。
"""
from __future__ import annotations

import statistics
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta

from game_signal_scout import config
from game_signal_scout.days import broadcast_day

PAGES = ("revival", "post_air", "language_spread")
WINDOW_HOURS = 6
WINDOWS_PER_DAY = 24 // WINDOW_HOURS


def load_pages() -> dict:
    return config.load_toml("pages.toml")


# ---------------------------------------------------------------- 集まり
@dataclass
class Agg:
    """投稿の集まり（日・言語・期間）。投稿者・投稿数・独立性・アニメとの結びつきを数える。"""
    posts_by_author: Counter = field(default_factory=Counter)
    heads: set = field(default_factory=set)
    anime_authors: set = field(default_factory=set)

    def add(self, author: str, head: str | None, anime: bool) -> None:
        self.posts_by_author[author] += 1
        if head:
            self.heads.add(head)
        if anime:
            self.anime_authors.add(author)

    @property
    def authors(self) -> int:
        return len(self.posts_by_author)

    @property
    def posts(self) -> int:
        return sum(self.posts_by_author.values())

    def independent(self, ind: dict) -> bool:
        """同じ人・同じ文の繰り返しで人数が増えていない（signal_cards.detect の独立性と同じ式）。"""
        if not self.posts:
            return False
        top_share = self.posts_by_author.most_common(1)[0][1] / self.posts
        return top_share <= ind["max_top_author_share"] and len(self.heads) >= ind["min_distinct_texts"]

    def anime_share(self) -> float:
        return len(self.anime_authors) / self.authors if self.authors else 0.0

    @staticmethod
    def merge(aggs) -> "Agg":
        out = Agg()
        for a in aggs:
            out.posts_by_author.update(a.posts_by_author)
            out.heads |= a.heads
            out.anime_authors |= a.anime_authors
        return out


@dataclass
class Day:
    day: date
    windows_complete: int
    observed: str                                    # complete / partial / none
    total: Agg = field(default_factory=Agg)
    langs: dict = field(default_factory=dict)        # 言語 → Agg（languages.NOT_LANGUAGE を除く）
    linked_posts: int = 0                            # Work に結び付いた投稿（Observation の coverage の分母）

    @property
    def authors(self) -> int:
        return self.total.authors


@dataclass
class WorkSeries:
    work_id: int
    level: str | None
    parent_id: int | None
    days: list = field(default_factory=list)         # Day の連続（投稿のない日も行がある）
    windows: dict = field(default_factory=dict)      # complete な 6 時間窓の開始 → 投稿者の set

    def __post_init__(self):
        self._index = {d.day: d for d in self.days}

    def at(self, d: date) -> Day | None:
        return self._index.get(d)


@dataclass
class SeriesSet:
    """全 Work の系列と、全体の観測の状態（Work に依らない）。"""
    as_of: date
    first: date
    days: list                                       # [(放送日, complete な窓の数, observed)]
    works: dict                                      # work_id → WorkSeries

    @property
    def observed_days(self) -> list[date]:
        return [d for d, _, st in self.days if st != "none"]


# ---------------------------------------------------------------- 系列を作る


# ---------------------------------------------------------------- 共通の判定部品（§2.2）
def coverage(observed_posts: int, linked_posts: int) -> float:
    if linked_posts <= 0:
        return 1.0 if observed_posts else 0.0
    return min(observed_posts / linked_posts, 1.0)


def enough(agg: Agg, min_authors: int, rules: dict) -> tuple[bool, str | None]:
    """母数の検査: 投稿者 min_authors 人以上・独立・アニメとの結びつき（signal_cards.toml の値）。理由は small / not_independent / weak_anchor。"""
    if agg.authors < min_authors:
        return False, "small"
    if not agg.independent(rules["independence"]):
        return False, "not_independent"
    if agg.anime_share() < rules["anchor"]["min_anime_author_share"]:
        return False, "weak_anchor"
    return True, None


def lang_authors(days, min_authors: int) -> dict[str, int]:
    """期間の言語ごとの投稿者（異なり数）。min_authors 人以上の言語だけ。"""
    merged: dict[str, list] = {}
    for d in days:
        for lg, a in d.langs.items():
            merged.setdefault(lg, []).append(a)
    out = {lg: Agg.merge(aggs).authors for lg, aggs in merged.items()}
    return dict(sorted(((lg, n) for lg, n in out.items() if n >= min_authors), key=lambda x: (-x[1], x[0])))


def observed(days) -> list[Day]:
    return [d for d in days if d.observed != "none"]


def series_tail(ws: WorkSeries, end: date, n: int, value=lambda d: d.authors, start: date | None = None) -> dict:
    """カードの推移の棒（直近 n 日。c = complete / p = partial / n = none）。未観測の日の値は None。"""
    if start is None:
        start = end - timedelta(days=n - 1)
    ds = [start + timedelta(days=i) for i in range(n) if start + timedelta(days=i) <= end]
    vals, marks = [], ""
    for d in ds:
        day = ws.at(d)
        st = day.observed if day else "none"
        marks += st[0]
        v = value(day) if day else None
        vals.append(None if (st == "none" or v is None) else v)
    return {"from": ds[0].isoformat() if ds else None, "authors": vals, "observed": marks}


def _verdict(shown: bool, reason: str | None = None, evidence: dict | None = None, **extra) -> dict:
    return {"shown": shown, "reason": reason, "evidence": evidence or {}, **extra}


# ---------------------------------------------------------------- 1 再燃（§3.1）


def _status_after(after: list[Day], ok, min_after_days: int) -> str:
    if len(after) < min_after_days:
        return "unknown"
    return "continuing" if ok(after[-1]) else "faded"


def _cont_run(after: list[Day], ok) -> int:
    """後の観測した日の先頭から、条件を満たす日が続いた日数。"""
    n = 0
    for d in after:
        if not ok(d):
            break
        n += 1
    return n


def judge_revival(ws: WorkSeries, th: dict, rules: dict, as_of: date) -> dict:
    """活動 → 一定期間の沈静 → 再び増加（放送日の単位）。前日比ではない。"""
    days = observed(ws.days)
    ch = rules["change"]
    events: list[dict] = []
    active: tuple[int, date] | None = None                # (最大の投稿者, その日)。直前の事象（または始め）からの活動
    quiet_run: list[Day] = []
    had_active = False
    max_quiet = 0
    fail_reason = None
    for d in days:
        quiet_like = d.authors <= th["quiet_max_authors"]
        if quiet_like:
            if active is not None and d.observed == "complete":
                quiet_run.append(d)
                max_quiet = max(max_quiet, len(quiet_run))
            continue                                        # partial の静かな日は数えず、連続も切らない
        # 投稿者が quiet_max_authors を超えた日
        if active is not None and len(quiet_run) >= th["quiet_min_days"]:
            base = statistics.mean(q.authors for q in quiet_run)
            ok, why = enough(d.total, th["revive_min_authors"], rules)
            if ok and d.authors >= ch["surge_ratio"] * max(base, ch["baseline_floor"]):
                events.append({"before_day": active[1], "before_peak": active[0], "quiet_from": quiet_run[0].day, "quiet_to": quiet_run[-1].day,
                               "quiet_days": len(quiet_run), "revived_day": d.day, "revive_authors": d.authors, "baseline_quiet": base,
                               "ratio": d.authors / max(base, ch["baseline_floor"])})
                active, quiet_run = (d.authors, d.day), []
                continue
            fail_reason = why or "no_revive"
        quiet_run = []
        ok, _ = enough(d.total, th["active_min_authors"], rules)
        if ok:
            had_active = True
            if active is None or d.authors >= active[0]:
                active = (d.authors, d.day)
    if not events:
        reason = "no_active" if not had_active else ("no_quiet" if max_quiet < th["quiet_min_days"] else (fail_reason or "no_revive"))
        return _verdict(False, reason)
    cont_ok = lambda x: x.authors >= th["cont_min_authors"]  # noqa: E731
    for i, e in enumerate(events):
        nxt = events[i + 1]["quiet_from"] if i + 1 < len(events) else as_of + timedelta(days=1)
        after = [d for d in days if e["revived_day"] < d.day < nxt]
        e["cont_days"] = _cont_run(after, cont_ok)
        e["status"] = _status_after(after, cont_ok, th["cont_min_after_days"])
    main = events[-1]
    if main["revived_day"] < as_of - timedelta(days=th["recent_days"] - 1):
        return _verdict(False, "too_old")
    wins = [(w, len(a)) for w, a in ws.windows.items() if broadcast_day(w) == main["revived_day"]]
    langs_days = [d for d in days if d.day >= main["revived_day"]]
    ev = {**{k: (v.isoformat() if isinstance(v, date) else round(v, 3) if isinstance(v, float) else v) for k, v in main.items()},
          "revive_window": max(wins, key=lambda x: (x[1], x[0]))[0].isoformat() if wins else None,
          "events_count": len(events), "events": [e["revived_day"].isoformat() for e in events],
          "langs_after": lang_authors(langs_days, load_pages()["common"]["min_lang_authors"])}
    return _verdict(True, None, ev, sort={"revive_authors": main["revive_authors"], "quiet_days": main["quiet_days"], "cont_days": main["cont_days"],
                                          "revived_day": main["revived_day"].isoformat()},
                    event_day=main["revived_day"], langs=ev["langs_after"])


# ---------------------------------------------------------------- 2 放送終了後（§3.2）
def _end_date(brief: dict | None) -> date | None:
    e = (brief or {}).get("end") or {}
    try:
        return date(int(e["y"]), int(e["m"]), int(e["d"])) if e.get("y") and e.get("m") and e.get("d") else None
    except (TypeError, ValueError):
        return None


def judge_post_air(ws: WorkSeries, th: dict, rules: dict, as_of: date, brief: dict | None, first_observed: date | None) -> dict:
    """表示している期の終了日と、その Work 自身の終了前の基準・終了後の反応を比べる。観測開始前に終了した作品は基準がないので出さない。
    通らなかった作品も、そこまでに分かった終了前後の数を evidence に持つ（画面が作品ごとの状態と根拠を示す。#26。閾値は変えない）。"""
    if not brief or brief.get("status") != "finished":
        return _verdict(False, "not_finished")
    end = _end_date(brief)
    if end is None:
        return _verdict(False, "no_end_date")
    ev: dict = {"end": end.isoformat(), "days_since_end": (as_of - end).days}
    if first_observed is None or end < first_observed:
        return _verdict(False, "no_baseline", ev)
    before = [d for d in observed(ws.days) if end - timedelta(days=th["before_days"]) <= d.day <= end - timedelta(days=1)]
    ev["baseline_days"] = len(before)
    if len(before) < th["before_min_days"]:
        return _verdict(False, "few_baseline_days", ev)
    baseline = statistics.median(d.authors for d in before)
    ev["baseline"] = baseline
    after_from = end + timedelta(days=th["settle_days"] + 1)
    after = [d for d in observed(ws.days) if after_from <= d.day <= as_of][-th["after_days"]:]
    ev["after_days"] = len(after)
    if after:   # 比べられない作品でも、終了後の 1 日の人数は示す（判定には使わない）
        ev["after_median"] = statistics.median(d.authors for d in after)
    if baseline < th["baseline_min_authors"]:
        return _verdict(False, "weak_baseline", ev)
    if as_of < after_from:
        return _verdict(False, "in_settle", ev)
    if len(after) < th["after_min_days"]:
        return _verdict(False, "few_after_days", ev)
    after_median = statistics.median(d.authors for d in after)
    agg = Agg.merge(d.total for d in after)
    ev.update(after_median=after_median, after_total_authors=agg.authors, ratio=round(after_median / baseline, 3))
    if not (after_median >= th["keep_ratio"] * baseline and after_median >= th["min_after_authors"]
            and agg.authors >= th["after_min_total_authors"]):
        return _verdict(False, "faded", ev)
    ok, why = enough(agg, th["min_after_authors"], rules)
    if not ok:
        return _verdict(False, why, ev)
    # 続いている日数: 直近から遡って、min_after_authors 人以上の日（partial の少ない日は連続を切らない・数えない）
    cont = 0
    for d in reversed(after):
        if d.authors >= th["min_after_authors"]:
            cont += 1
        elif d.observed == "partial":
            continue
        else:
            break
    ev = {"end": end.isoformat(), "days_since_end": (as_of - end).days, "baseline": baseline, "baseline_days": len(before),
          "after_from": after[0].day.isoformat(), "after_to": after[-1].day.isoformat(), "after_days": len(after), "after_median": after_median,
          "after_total_authors": agg.authors, "ratio": round(after_median / baseline, 3), "cont_days": cont,
          "status": "continuing" if cont >= 1 else "faded", "settle_days": th["settle_days"]}
    return _verdict(True, None, ev, sort={"after_median": after_median, "ratio": ev["ratio"], "days_since_end": ev["days_since_end"],
                                          "cont_days": cont}, event_day=end,
                    langs=lang_authors(after, load_pages()["common"]["min_lang_authors"]))


# ---------------------------------------------------------------- 3 言語圏（§3.3）
def judge_language_spread(ws: WorkSeries, th: dict, rules: dict, as_of: date, recorded_days: set | None = None) -> dict:
    """既存の新しい言語圏 Signal の規則（signal_cards.toml [spread]）を日単位の系列に当てる。
    「なかった・非常に少なかった言語圏」= 過去 lookback_days 日で日最大 prior_max_authors 人以下（2026-10-05 ユーザー決定）。
    過去 lookback_days 日の集計（言語の分かる投稿者・言語ごとの日最大）は、日ごとに足し引きして持ち回す（1 年分でも各日を 1 回ずつ数える）。"""
    from collections import deque
    sp = rules["spread"]
    days = observed(ws.days)
    lookback = timedelta(days=th["lookback_days"])
    events: list[dict] = []
    reason = None
    best_partial = 0
    win: deque = deque()                       # 過去 lookback_days 日の観測した日
    known_cnt: Counter = Counter()             # その期間の言語の分かる投稿者（言語 × 日の出現の数）
    lang_win: dict[str, deque] = {}            # 言語 → [(日, 投稿者数)]（期間の中）
    evicted_max: dict[str, int] = {}           # 期間より前の、言語ごとの日最大（再出現の判定）
    for i, d in enumerate(days):
        lo = d.day - lookback
        while win and win[0].day < lo:
            old = win.popleft()
            for lg, a in old.langs.items():
                for au in a.posts_by_author:
                    known_cnt[au] -= 1
                    if known_cnt[au] <= 0:
                        del known_cnt[au]
        for lg, q in lang_win.items():
            while q and q[0][0] < lo:
                evicted_max[lg] = max(evicted_max.get(lg, 0), q.popleft()[1])
        # 新しい言語圏になりうる言語（その日に min_new_language_authors 人以上）がない日は判定しない
        cand = [lg for lg, a in d.langs.items() if a.authors >= sp["min_new_language_authors"]]
        if not cand:
            for lg, a in d.langs.items():   # 未判定の理由: 既存でない言語に 1〜2 人だけ出た（few_new_authors）
                q = lang_win.get(lg)
                if (max(n for _, n in q) if q else 0) <= th["prior_max_authors"]:
                    best_partial = max(best_partial, a.authors)
        elif len(win) < th["prior_min_days"] or len(known_cnt) < sp["min_before_authors"]:
            reason = reason or "no_prior"
        else:
            prior_max = {lg: max(n for _, n in q) for lg, q in lang_win.items() if q}
            new = {}
            for lg, a in d.langs.items():
                if prior_max.get(lg, 0) > th["prior_max_authors"]:
                    continue                                # 既存の言語圏
                if a.authors < sp["min_new_language_authors"]:
                    if a.authors > 0:
                        best_partial = max(best_partial, a.authors)
                    continue
                if d.authors < sp["min_day_authors"]:
                    reason = "small"
                    continue
                ok, why = enough(a, sp["min_new_language_authors"], rules)
                if not ok:
                    reason = why
                    continue
                new[lg] = {"code": lg, "authors": a.authors, "reappeared": evicted_max.get(lg, 0) > th["prior_max_authors"]}
            if new:
                existing = {lg: n for lg, n in prior_max.items() if n > th["prior_max_authors"]}
                events.append({"day": d.day, "index": i, "new": new, "prior_langs": dict(sorted(existing.items(), key=lambda x: (-x[1], x[0]))),
                               "prior_known_authors": len(known_cnt), "day_authors": d.authors,
                               # 「それまで」に実際に使えた観測の日数と最初の日（lookback_days より短いことがある。画面で示す。判定には使わない）
                               "prior_observed_days": len(win), "prior_from": win[0].day.isoformat()})
        win.append(d)
        for lg, a in d.langs.items():
            for au in a.posts_by_author:
                known_cnt[au] += 1
            lang_win.setdefault(lg, deque()).append((d.day, a.authors))
    if not events:
        return _verdict(False, reason if reason in ("small", "not_independent", "weak_anchor") else
                        ("few_new_authors" if best_partial else (reason or "no_new_lang")))
    main = events[-1]
    after = days[main["index"] + 1:]
    for lg, x in main["new"].items():
        ok = lambda dd, lg=lg: dd.langs.get(lg) is not None and dd.langs[lg].authors >= th["cont_min_authors"]  # noqa: E731
        x["cont_days"] = sum(1 for dd in after if ok(dd))
        x["status"] = _status_after(after, ok, th["cont_min_after_days"])
    new_langs = sorted(main["new"].values(), key=lambda x: (-x["authors"], x["code"]))
    status = new_langs[0]["status"]
    if not th["show_faded"] and all(x["status"] == "faded" for x in new_langs):
        return _verdict(False, "faded")
    if main["day"] < as_of - timedelta(days=th["recent_days"] - 1):
        return _verdict(False, "too_old")
    new_agg = Agg.merge(ws.at(main["day"]).langs[x["code"]] for x in new_langs)
    ev = {"first_day": main["day"].isoformat(), "new_langs": new_langs, "prior_langs": main["prior_langs"],
          "prior_known_authors": main["prior_known_authors"], "day_authors": main["day_authors"], "new_authors": new_agg.authors,
          "status": status, "signal_recorded": bool(recorded_days and main["day"] in recorded_days), "events_count": len(events),
          "prior_observed_days": main["prior_observed_days"], "prior_from": main["prior_from"]}
    top = new_langs[0]["code"]
    return _verdict(True, None, ev, sort={"new_authors": new_agg.authors, "first_day": ev["first_day"], "cont_days": new_langs[0]["cont_days"],
                                          "new_lang_count": len(new_langs)},
                    event_day=main["day"], langs=lang_authors([d for d in days if d.day >= main["day"]], load_pages()["common"]["min_lang_authors"]),
                    spark_value=lambda dd, lg=top: (dd.langs[lg].authors if dd.langs.get(lg) else 0))


# ---------------------------------------------------------------- memo（process の中だけ。保存しない）
_MEMO: dict = {}
MEMO_TTL_SECONDS = 600


