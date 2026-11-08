"""ダッシュボードの「アニメの動きをもっと見る」の Q1・Q2 の分析（2026-10-16 のユーザーの指示「数値を並べる画面ではなく、発見を届ける画面に」）。

入力は全 Source 共通の基盤だけ（ADR 0051）: Source ごとの作品の系列（品質判定済みのファンの人数。publication/content.src_series）と、
共通の Signal 発見（foundation/signals.run: 作品自身の普段の窓と比べた急増・初めての出現・新しい言語圏、情報の発信 announcement）。
Source の名前で分岐しない。人数は Source の中で数え、Source をまたいで足さない（作品は最初に変化を見つけた Source の 1 つ）。

Q1「いつもと何が違った？」: その日の作品の動きを、作品自身の普段と比べて分ける。
  surge（普段より急に増えた）/ emergence（初めて話題に）/ new_language（新しい言語圏でも）/ continuing（数日続いている）/ steady（普段どおりの定番）。
  注目する作品は人数ではなく「普段との違い」と「続いているか」で選ぶ。定番は参考に分けて示す。変化の数も直近の日と比べる（大きな変化がない日はそう伝える）。
Q2「新しく話題になった作品は、何が新しい？」: 前日は話題でなかった作品（前日も観測した Source の中で）を、データで確かめられる理由で分ける。
  放送が始まった（作品情報の開始日）/ 発表・告知のあと（情報の発信の Signal）/ 再び（7 日以上の観測で話題がなかった後）/ 初めて話題に（観測 7 日以上）/
  いつもの出入り（直近にも話題。話題の境目を日々出入りしている作品。数だけを示す）/ それ以外。
文は作らない（画面が、この事実から日英の文を組む）。LLM を使わない。
"""
from __future__ import annotations

import statistics
from datetime import date, timedelta

TOPIC = 2                 # 話題 = 独立したファン 2 人以上（地図・一覧と同じ）
BASE_DAYS = 14            # 普段 = 直近の観測した日（最大 14 日）の人数の中央値
COMPARE_DAYS = 7          # 変化の数を比べる直近の日
STEADY_MIN = 5            # 定番 = 普段も今日も 5 人以上で、普段の 2/3〜1.5 倍
QUIET_DAYS = 7            # 「再び」= 最後に話題になってから 7 日以上の観測で話題がなかった
FIRST_DAYS = 7            # 「初めて話題に」= 7 日以上の観測で、一度も話題にならなかった
CONT_DAYS = 3             # 続いている = 直近 3 日のうちに急増・初出・新しい言語圏があり、今日もその日の人数の半分以上
CHANGE = ("surge", "emergence", "new_language", "continuing")
# 変化の作品の並び（ADR 0010: 総合スコアを作らず、変化の種類ごとに分けて、変化が始まった時の新しい順）。種類の順は、それまで静かだった状態から
# どれだけ新しい動きか: 初めて話題に → 新しい言語圏 → 普段より急に増えた → 前の日に始まった変化が続いている
ORDER = ("emergence", "new_language", "surge", "continuing")


def _observed(ws, x: date) -> bool:
    day = ws.at(x)
    return bool(day and day.observed != "none")


def _n(ws, x: date) -> int:
    day = ws.at(x)
    return day.authors if day else 0


def _base(ws, d: date) -> tuple[float | None, int]:
    vals = [_n(ws, x.day) for x in ws.days if x.day < d and x.observed != "none"][-BASE_DAYS:]
    return (statistics.median(vals) if vals else None), len(vals)


def _langs(ws, d: date, prof: dict) -> list[str]:
    from game_signal_scout.signal import area_input
    day = ws.at(d)
    out = []
    for lg, a in (day.langs.items() if day else []):
        if a.authors >= TOPIC:
            area = area_input._area(prof, lg)[0] if prof else lg
            if area not in out:
                out.append(area)
    return out


def _spark(ws, d: date) -> dict:
    ds = [d - timedelta(days=i) for i in range(BASE_DAYS - 1, -1, -1)]
    return {"from": ds[0].isoformat(), "n": [(_n(ws, x) if _observed(ws, x) else None) for x in ds]}


def signals_by_day(ctx, src: str, days: list[date]) -> dict[date, dict[int, dict]]:
    """共通の Signal 発見（作品の次元と情報の発信）の結果を、日 → 作品 → 変化に。Source ごとに、公開した日の全期間を 1 回だけ計算して使い回す。"""
    cache = ctx.__dict__.setdefault("_mv_sig", {})
    if src not in cache:
        first = min(min(ctx.pdays), min(days)) - timedelta(days=COMPARE_DAYS + CONT_DAYS)
        span = [first + timedelta(days=i) for i in range((ctx.latest - first).days + 1)]
        cache[src] = _signals(ctx, src, span)
    return {d: cache[src].get(d, {}) for d in days}


def _signals(ctx, src: str, days: list[date]) -> dict[date, dict[int, dict]]:
    from game_signal_scout.foundation import signals
    try:
        res = signals.run(ctx.conn, ctx.conn, src, days, dims=("work", "info_work"))
    finally:
        ctx.conn.rollback()
    out: dict[date, dict[int, dict]] = {}
    for d, cs in res.items():
        m: dict[int, dict] = {}
        for c in cs:
            dim, _, rest = c["key"].partition(":")
            w = int(rest)
            if dim == "info_work":
                m.setdefault(w, {})["announcement"] = c
            elif dim == "work":
                m.setdefault(w, {})["change"] = c
        out[d] = m
    return out


def classify(ws, w: int, d: date, sig: dict[date, dict[int, dict]]) -> dict | None:
    """作品のその日の動き（作品自身の普段と比べる）。話題でない日は None。"""
    n = _n(ws, d)
    if n < TOPIC:
        return None
    base, base_n = _base(ws, d)
    ratio = round(n / max(base or 0, 0.5), 1) if base is not None else None
    ch = (sig.get(d, {}).get(w) or {}).get("change")
    kind, streak, since = None, 0, None
    if ch and ch["kind"] in ("surge", "emergence", "new_language"):
        kind, since = ch["kind"], ch.get("since")
    else:
        for i in range(1, CONT_DAYS + 1):
            p = (sig.get(d - timedelta(days=i), {}).get(w) or {}).get("change")
            if p and p["kind"] in ("surge", "emergence", "new_language") and n >= max(TOPIC, 0.5 * p["day_authors"]):
                kind, streak, since = "continuing", i + 1, p.get("since")
                break
    if kind is None and base is not None and base >= STEADY_MIN and n >= STEADY_MIN and 0.67 <= n / base <= 1.5:
        kind = "steady"
    return {"kind": kind, "n": n, "base": base, "base_days": base_n, "ratio": ratio, "streak": streak,
            "new_langs": sorted((ch or {}).get("langs") or {}) if kind == "new_language" else [], "prev": _n(ws, d - timedelta(days=1)), "since": since}


def may_turn(ws, w: int, d: date, sig: dict[date, dict[int, dict]], kinds) -> bool:
    """作品詳細の転換点になりうる日か（classify・entry を呼ぶ前の絞り込み。結果は変えない。全期間を見ても日ごとに系列をなめ直さないため。#52）:
    その日の変化が kinds のどれか、または前の日を観測して話題でなく、この日に話題（entry の対象）。"""
    if ((sig.get(d, {}).get(w) or {}).get("change") or {}).get("kind") in kinds:
        return True
    return _n(ws, d) >= TOPIC and _observed(ws, d - timedelta(days=1)) and _n(ws, d - timedelta(days=1)) < TOPIC


def entry(ctx, ws, w: int, d: date, sig: dict[date, dict[int, dict]]) -> dict | None:
    """前日は話題でなかった作品が、この日に話題になった理由（データで確かめられるものだけ）。前日を観測していない・前日も話題・今日も話題でない作品は None。"""
    if _n(ws, d) < TOPIC or not _observed(ws, d - timedelta(days=1)) or _n(ws, d - timedelta(days=1)) >= TOPIC:
        return None
    before = [x.day for x in ws.days if x.day < d - timedelta(days=1) and x.authors >= TOPIC]
    last = max(before) if before else None
    quiet = sum(1 for x in ws.days if last and last < x.day < d and x.observed != "none")   # 最後に話題になった日から、話題でなかった観測した日の数
    seen = sum(1 for x in ws.days if x.day < d and x.observed != "none")
    ann = [k for k in (d, d - timedelta(days=1)) if (sig.get(k, {}).get(w) or {}).get("announcement")]
    st = _start(ctx.briefs.get(w))
    if st and d - timedelta(days=1) <= st <= d:
        reason = "premiere"
    elif ann:
        reason = "announcement"
    elif last and quiet >= QUIET_DAYS:
        reason = "again"            # しばらく（7 日以上の観測で）話題がなかった後に戻ってきた
    elif last:
        reason = "flicker"          # 直近にも話題になっていた（話題の境目を日々出入りしている。いつもの出入り）
    elif seen >= FIRST_DAYS:
        reason = "first"
    else:
        reason = "other"
    return {"entry": reason, "n": _n(ws, d), "prev": _n(ws, d - timedelta(days=1)), "last_topic": last.isoformat() if last else None, "quiet": quiet,
            "announce_accounts": max((sig[k][w]["announcement"]["day_authors"] for k in ann), default=None), "start": st.isoformat() if st else None}


def work_changes(ctx, d: date) -> dict[int, dict]:
    """作品ごとの、その日の動き（作品自身の普段と比べた変化）。今日の兆し（dd・sd）の発見の評価と Q1・Q2 が同じ分析を使う（ADR 0052）。
    入力は全 Source 共通の基盤だけ。作品の変化は、最初に変化を見つけた Source の系列の値（Source をまたいで人数を足さない）。
    sources = その日にその作品を 2 人以上が話題にした Source。by_source = Source ごとの変化（今日の兆しは声と同じ Source の値で書く: 出どころの違う数字を
    1 つの文章に混ぜない）。entry = 前日は話題でなかった作品の理由（Q2 と同じ）。"""
    from game_signal_scout.signal.content import src_series
    days = [d - timedelta(days=i) for i in range(COMPARE_DAYS + CONT_DAYS, -1, -1)]
    out: dict[int, dict] = {}
    for src, prof, works in src_series(ctx):
        if src is None:
            continue
        sig = signals_by_day(ctx, src, days)
        for w, ws in works.items():
            c = classify(ws, w, d, sig)
            if not c:
                continue
            x = out.setdefault(w, {**c, "src": src, "sources": [], "entry": None, "by_source": {}})
            x["sources"].append(src)
            e = entry(ctx, ws, w, d, sig)
            x["by_source"][src] = {**c, "entry": e["entry"] if e else None}
            if x["kind"] not in CHANGE and c["kind"] in CHANGE:   # 変化を見つけた Source の値を使う（定番・変化なしより変化を優先）
                out[w] = x = {**c, "src": src, "sources": x["sources"], "entry": x["entry"], "by_source": x["by_source"]}
            if e and not x["entry"]:
                x["entry"] = e["entry"]
    return out


def order(w: int, x: dict) -> tuple:
    """変化の作品の並びの鍵（ADR 0010）: 変化の種類（ORDER）→ 変化が始まった時間の窓の新しい順 → 作品の ID（同じ窓の作品を毎回同じ順にするだけ）。
    人数・比・重みは使わない（量の大きさで並べない）。始まりの窓が分からない変化は、その種類の最後。"""
    t = x.get("since")
    return ORDER.index(x["kind"]), t is None, -(t.timestamp() if t else 0), w


def _start(brief: dict | None) -> date | None:
    s = (brief or {}).get("start") or {}
    try:
        return date(int(s["y"]), int(s["m"]), int(s["d"])) if s.get("y") and s.get("m") and s.get("d") else None
    except (TypeError, ValueError):
        return None


def analyze(ctx, d: date) -> dict:
    """「いつもより話題が増えた作品」の分析の結果（画面の入力。作品それぞれの普段と比べた変化）。"""
    from game_signal_scout.signal.content import _src_tag, src_series
    days = [d - timedelta(days=i) for i in range(COMPARE_DAYS + CONT_DAYS, -1, -1)]
    moves: dict[date, dict[int, tuple]] = {x: {} for x in days}
    for src, prof, works in src_series(ctx):
        if src is None:
            continue
        sig = signals_by_day(ctx, src, days)
        for x in days:
            for w, ws in works.items():
                c = classify(ws, w, x, sig)
                if c and w not in moves[x]:
                    moves[x][w] = (c, src, prof, ws)
    today = moves[d]
    feat = sorted(((w, c) for w, c in today.items() if c[0]["kind"] in CHANGE), key=lambda x: order(x[0], x[1][0]))
    steady = sorted(((w, c) for w, c in today.items() if c[0]["kind"] == "steady"), key=lambda x: (-x[1][0]["n"], x[0]))

    def item(w, c):
        x, src, prof, ws = c
        return ctx.ref(w, **{k: v for k, v in x.items() if k != "since"}, langs=_langs(ws, d, prof), spark=_spark(ws, d), **_src_tag(ctx, src, prof))
    counts = {x.isoformat(): sum(1 for c in moves[x].values() if c[0]["kind"] in CHANGE) for x in days if x < d}
    recent = [counts[k] for k in sorted(counts)[-COMPARE_DAYS:]]
    n_today = len(feat)
    usual = statistics.median(recent) if recent else None
    level = None if usual is None else ("more" if n_today >= max(usual * 1.5, usual + 2) else ("fewer" if n_today <= usual * 0.5 and usual - n_today >= 2 else "usual"))
    by_kind = {k: sum(1 for _, c in feat if c[0]["kind"] == k) for k in CHANGE}
    # 一覧は全件を持つ（画面が初めの数件を出し、残りは「もっと見る」で開く。#24）
    return {"q1": {"changes": n_today, "usual": usual, "vs_usual": level, "by_kind": by_kind,
                   "featured": [item(w, c) for w, c in feat],
                   "steady": [ctx.ref(w, n=c[0]["n"], base=c[0]["base"]) for w, c in steady[:3]]}}


def _fact(x: dict, loc: str) -> str:
    """作品 1 つの、普段と比べた変化の事実の文（日英）。数は分析の値だけ。"""
    nm = x["name"][loc]
    b = x.get("base")
    if x["kind"] == "emergence":
        return f"『{nm}』が、これまでの観測で初めて話題に（{x['n']}人）" if loc == "ja" else f"{nm} was talked about for the first time in what we observed ({x['n']} people)"
    if x["kind"] == "new_language":
        return f"『{nm}』が新しい言語圏でも話題に（{x['n']}人）" if loc == "ja" else f"{nm} reached a new language area ({x['n']} people)"
    if x["kind"] == "continuing":
        return f"『{nm}』は、急に増えてから{x['streak']}日目も{x['n']}人が話題に" if loc == "ja" else f"{nm} is still talked about by {x['n']} people, day {x['streak']} after its rise"
    if b is not None and b < 1:
        return f"普段はほとんど話題にならない『{nm}』に、{x['n']}人" if loc == "ja" else f"{nm}, usually barely talked about, drew {x['n']} people"
    bs = f"{round(b, 1):g}" if b is not None else "?"
    return f"『{nm}』の話題が、普段の1日{bs}人前後から{x['n']}人に" if loc == "ja" else f"{nm} went from about {bs} {'person' if bs == '1' else 'people'} a day to {x['n']}"


def headline(mv: dict | None) -> dict | None:
    """集計の見出し（仕様 §0.3: 文章がない日に出す既存の規則の文）。どの日にも当てはまる文（「さまざまなアニメが話題に」）ではなく、
    作品それぞれの普段と比べた変化の分析の結果から組む。大きな変化がない日はそう書く。"""
    if not mv:
        return None
    q = mv["q1"]
    f = q["featured"]
    if not f:
        return {"head": {"ja": "この日は、作品それぞれの普段から目立って変わった動きは見つかりませんでした。", "en": "No title moved notably away from its usual level on this day."},
                "lede": {"ja": "話題になった作品は、どれも普段と同じくらいの人数でした。", "en": "The titles talked about drew about their usual numbers."}}
    rest = q["changes"] - 1
    cmp_ja = {"more": "直近の日より多い", "fewer": "直近の日より少ない", "usual": "直近の日と同じくらい"}.get(q.get("vs_usual"), "")
    cmp_en = {"more": "more than recent days", "fewer": "fewer than recent days", "usual": "about the same as recent days"}.get(q.get("vs_usual"), "")
    lede_ja = (f"ほかにも、作品それぞれの普段と比べて目立って動いた作品が{rest}作品ありました" + (f"（{cmp_ja}）" if cmp_ja else "") + "。") if rest else "この日、普段と比べて目立って動いたのはこの作品だけでした。"
    lede_en = (f"{rest} other titles also moved notably from their usual level" + (f" ({cmp_en})" if cmp_en else "") + ".") if rest else "This was the only title that moved notably from its usual level."
    return {"head": {"ja": _fact(f[0], "ja") + "。", "en": _fact(f[0], "en") + "."}, "lede": {"ja": lede_ja, "en": lede_en}, "work": f[0].get("id")}
