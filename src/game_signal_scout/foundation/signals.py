"""共通層の上の Signal 発見（ADR 0051 の M5）。

系列の鍵 = 次元の値（Source の中）。次元は Source を知らない:
  work            … 作品（今の作品のカード: 急増・出現・新しい言語・その後）
  behavior        … 発言の分類（作品を横断する感情・行動・需要: 続編の要望・不満・視聴の開始 …）
  work_behavior   … 作品 × 発言の分類（作品の中で語られ方が変わった）
  info_work       … 作品の情報の発信（ニュースのまとめ・配信の告知・同じ文の宣伝の投稿者。ファンの声の数には入れず、別の意味の Signal として残す）
同じ検出（signal_cards.detect: 基準の窓・急増の比・独立性・アニメとの結びつき・新しい言語・その後）を、どの次元・どの Source にも同じ値で当てる。
人数は Source の中で数え、Source をまたいで足さない。本文を読まない・持たない Source は書き出しの検査ができないので行わない（unknown）。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from game_signal_scout import signal_cards
from game_signal_scout.candidate_registry import window_start
from game_signal_scout.repositories import foundation as foundation_repo, source_item

WH = 6
DIMENSIONS = ("work", "behavior", "work_behavior", "info_work")


@dataclass
class Row:
    uid: str
    work: int
    actor: str
    t: datetime
    lang: str | None
    head: str | None
    anime: bool
    counted: bool
    behavior: str | None      # 数えてよい発言の分類（なければ None）
    role: str | None
    actor_role: str | None = None   # 投稿者の振る舞いから見た役割（foundation/account.py）


def load(dst, source: str, first: date, as_of: date) -> list[Row]:
    """共通層の発言（同定された・削除されていない）と、その判定の契約の値。"""
    from game_signal_scout.foundation.normalize import descriptors
    pol = (descriptors().get(source) or {}).get("counting", "none")   # 数え方は Source の記述（sources/observations.read_foundation と同じ）
    rows = foundation_repo.list_judged_utterances(dst, source, first, as_of)
    dst.rollback()
    out = []
    info = set(info_roles())
    for uid, wid, actor, t, lang, head, anime, about, beh, role, arole in rows:
        counted = pol == "identified" or (pol == "about_work" and about == "yes")
        out.append(Row(uid, wid, actor, t, lang, head, anime == "yes", counted and arole not in info, beh, role, arole))
    return out


def info_roles() -> list[str]:
    """ファンの声の数に入れず、情報の発信として扱う投稿者の役割（config/foundation_rules.toml [counting]）。"""
    from game_signal_scout import config
    return list((config.load_toml("foundation_rules.toml").get("counting") or {}).get("info_actor_roles", []))


def keys_of(r: Row, dims=DIMENSIONS, info: set | None = None) -> list[str]:
    """info = 情報の発信の役割（info_roles）。build は 1 回だけ読んで渡す（投稿ごとに設定を読み直さない。#18）。"""
    out = []
    if "info_work" in dims and r.actor_role in (info if info is not None else set(info_roles())):
        out.append(f"info_work:{r.work}")
    if "work" in dims and r.counted:
        out.append(f"work:{r.work}")
    if r.behavior and r.counted:
        if "behavior" in dims:
            out.append(f"behavior:{r.behavior}")
        if "work_behavior" in dims:
            out.append(f"work_behavior:{r.work}:{r.behavior}")
    return out


def build(rows: list[Row], dims=DIMENSIONS) -> dict[str, signal_cards.Series]:
    """次元の鍵ごとの系列（同じ発言は鍵の中で 1 回。作品を横断する鍵では、同じ発言が複数の作品に同定されていても 1 回）。"""
    out: dict[str, signal_cards.Series] = {}
    seen: set = set()
    info = set(info_roles())
    for r in rows:
        for k in keys_of(r, dims, info):
            if (k, r.uid) in seen:
                continue
            seen.add((k, r.uid))
            s = out.get(k) or out.setdefault(k, signal_cards.Series(k))
            s.variants[k] += 1
            s.methods.add("foundation")
            s.by_window[window_start(r.t, WH)].append(signal_cards.Post(k, k, "foundation", r.actor, r.t, r.lang, None, r.uid, r.anime, r.head))
    return out


def covered_days(dst, source: str, first: date, as_of: date, partial: bool = False) -> list[date]:
    """その Source が日を通して観測した日（共通層の変換が記録した観測の範囲。全 Source で同じ規則）。partial なら一部だけ観測した日も。"""
    states = ["complete", "partial"] if partial else ["complete"]
    out = foundation_repo.list_covered_days(dst, source, first, as_of, states)
    dst.rollback()
    return out


def windows(src_ref, dst, source: str, desc: dict, first: date, as_of: date) -> list[datetime]:
    """観測のそろった 6 時間の窓。一部だけ観測した日も確定する Source（記述の finalize_partial）は、取得の記録（source_fetch）で
    6 時間ぶんすべての時間に成功した取得のある窓。ほかは観測した日の 4 つの窓。"""
    from game_signal_scout.days import day_range
    if desc.get("finalize_partial"):
        s0, _ = day_range(first)
        _, e1 = day_range(as_of)
        hours = source_item.list_ok_fetch_hours(src_ref, source, s0, e1)
        src_ref.rollback()
        ws, w = [], s0
        while w < e1:
            if all(w + timedelta(hours=i) in hours for i in range(WH)):
                ws.append(w)
            w += timedelta(hours=WH)
        return ws
    return sorted(day_range(d)[0] + timedelta(hours=WH * i) for d in covered_days(dst, source, first, as_of) for i in range(24 // WH))


EMERGENCE_MIN_DAYS = 7   # 「初めて出た」「前になかった言語」と言えるのは、その Source が前に 7 日以上観測してから（観測を始めた直後の初出は、観測に入っただけ）


def detect_day(series: dict[str, signal_cards.Series], all_ws: list[datetime], day: date, rules: dict, check_texts: bool, observed_before: int = 999) -> list[dict]:
    from game_signal_scout.days import day_range
    ds, de = day_range(day)
    day_ws = [ds + timedelta(hours=WH * i) for i in range(24 // WH)]
    upto = [w for w in all_ws if w < de]
    out = []
    for k, s in series.items():
        if not any(s.by_window.get(w) for w in day_ws):
            continue
        card, why = signal_cards.detect(s, upto, day_ws, rules, {}, observed_end=de, check_texts=check_texts)
        if card:
            kind = card["main"]["kind"]
            if kind == "emergence" and observed_before < EMERGENCE_MIN_DAYS:
                kind = "surge"   # 基準の窓より増えたことは言えるが、初めて出たとは言えない
            if kind == "new_language" and observed_before < EMERGENCE_MIN_DAYS:
                continue         # 前になかった言語とは言えない（観測が短い）。この日のほかの変化は急増・初出として別に判定済み
            out.append({"key": k, "kind": kind, "status": card["status"], "day_authors": card["day_authors"],
                        "window_authors": card["main"].get("authors"), "langs": card["main"].get("langs"), "day_langs": card["day_langs"],
                        "since": card["main"].get("window")})   # 変化が始まった時間の窓（並び順の根拠。ADR 0010）
    return out


def info_events(series: dict[str, signal_cards.Series], day: date, cov: list[date], r: dict) -> list[dict]:
    """情報の発信の Signal（kind = announcement）: その日に、作品について発信した情報の発信の投稿者（まとめ・告知・宣伝）が min_accounts 以上で、
    前の baseline_days 日（観測した日）の 1 日の平均の ratio 倍以上。まとめのアカウントは独立した人の集まりではないので、ファンの急増の規則（窓・独立性）は当てない。"""
    from game_signal_scout.days import day_range
    ds, de = day_range(day)
    prev = [d for d in cov if d < day][-int(r["baseline_days"]):]
    out = []
    for k, s in series.items():
        if not k.startswith("info_work:"):
            continue
        today = {p.author for w, ps in s.by_window.items() if ds <= w < de for p in ps}
        if len(today) < r["min_accounts"]:
            continue
        base = [len({p.author for w, ps in s.by_window.items() if day_range(d)[0] <= w < day_range(d)[1] for p in ps}) for d in prev]
        avg = sum(base) / len(base) if base else 0.0
        if len(today) >= r["ratio"] * max(avg, r["floor"]):
            out.append({"key": k, "kind": "announcement", "status": "unknown", "day_authors": len(today), "window_authors": None, "langs": None,
                        "day_langs": dict(__import__("collections").Counter(p.lang for w, ps in s.by_window.items() if ds <= w < de for p in ps)),
                        "baseline": round(avg, 2)})
    return out


def run(src_ref, dst, source: str, days: list[date], lookback: int = 28, dims=DIMENSIONS) -> dict[date, list[dict]]:
    from game_signal_scout.foundation.normalize import descriptors
    desc = descriptors()[source]
    rules = signal_cards.load_rules()
    first = min(days) - timedelta(days=lookback)
    rows = load(dst, source, first, max(days))
    series = build(rows, dims)
    all_ws = windows(src_ref, dst, source, desc, first, max(days))
    check = desc.get("text") in ("stored", "transient")
    cov = covered_days(dst, source, first - timedelta(days=60), max(days))
    seen = covered_days(dst, source, first - timedelta(days=60), max(days), partial=True)   # 初出かどうかは、一部でも観測していた日で数える
    out = {}
    for d in days:
        if d not in cov and not desc.get("finalize_partial"):
            out[d] = []          # その日を観測していない Source は、その日の Signal を出さない（0 人と比べない）
            continue
        fan = {k: v for k, v in series.items() if not k.startswith("info_work:")}
        out[d] = detect_day(fan, all_ws, d, rules, check, observed_before=sum(1 for x in seen if x < d))
        if "info_work" in dims:
            out[d] += info_events(series, d, seen, info_rule())
    return out


def info_rule() -> dict:
    from game_signal_scout import config
    return config.load_toml("foundation_rules.toml")["info_signal"]
