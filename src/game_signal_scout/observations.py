"""全 Source 共通の観測の集計の確定（Anime の sources/observations.py をそのまま流用。違いは読み取り元だけ: Game の共通の発言 player_post）。

Anime の説明（流用元）:
全 Source 共通の観測の集計の確定（ADR 0050・0051）。

流れ（すべての Source で同じ 1 本）:
  原文の表 → 共通層（foundation/normalize: 発言・同定・判定の契約・観測の範囲）→ 投稿者の役割（foundation/account）
    → ここ: 共通層を読む（read_foundation）→ 共通の集計（放送日 × 作品 × 言語の独立した投稿者）
    → 共通の確定（そろったら置き換え、そろわないうちは前の確定を残す。消さない）→ 表 obs_work_lang_day・obs_post・obs_day_state
    → 地図・言語ページ・作品詳細・変化のページは、この表だけを読む。
数えるかどうかは Source の記述の数え方（config/source_descriptors.toml）と、情報の発信の投稿者を数えない規則（config/foundation_rules.toml）。
人数は Source の中で数え、Source をまたいで足さない（ADR 0035）。Source の登録（表示）は config/map_sources.toml。
"""
from __future__ import annotations

from game_signal_scout import config
from game_signal_scout.languages import NOT_LANGUAGE

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from game_signal_scout.repositories import observation as observation_repo

AGG_VERSION = "obs-v3"   # 保存した集計の版の名前（記録の出所なので変えない）。今の規則: すべての言語の合計の行（'*'）を持ち、同じ本文を出した別の人を 1 つの発信元と数える
TOTAL = "*"            # すべての言語の合計の行（obs_work_lang_day.lang）
SAME_TEXT_MIN_CHARS = 20   # 同じ本文を 1 つの発信元とまとめる本文の長さ（書き出しの派生の文字数）。短い決めぜりふを同時に書いたファンはまとめない
PROVISIONAL = "provisional"   # 判定待ち・取得の途中で、判定済みの記録だけの途中の値（画面は「一部集計中」と示す）
PROVISIONAL_REASONS = {"judgments_pending", "fetch_hours"}
NOT_COVERED = "not_covered"   # その日は Source の観測の範囲外（観測を始める前）。画面では、その日にその Source がないのと同じ


@dataclass
class Obs:
    """共通の観測の記録（1 つの発言・投稿）。status: counted（数える）/ excluded（品質の判定で数えない）/ pending（判定待ち）。"""
    unit: str
    actor: str | None
    day: date
    lang: str | None
    work_id: int | None
    status: str
    head: str | None = None        # 文の書き出し（独立性の検査。signal_cards.text_head と同じ派生。本文ではない）
    anime: bool = True             # アニメとの結びつき（Bluesky = 取り込みの判定、判定の工程を持つ Source = 作品について書いたと判定済み）
    at: datetime | None = None     # 投稿の時刻（6 時間の窓。分からなければ None）
    same_text: str | None = None   # 同じ本文の印（自分の言葉が十分にある本文のハッシュ）。別の人が同じ本文を出したら 1 つの発信元と数える


@dataclass
class DayResult:
    """その日の読み取りの結果。complete = 判定待ちがなく、取得がその日を通してある。"""
    obs: list[Obs]
    complete: bool
    reason: str | None
    version: str
    detail: dict


# ---------------------------------------------------------------- 読み取り（全 Source 共通のデータ基盤から。ADR 0051。Source ごとの読み方はない）
def window_start(t: datetime, hours: int) -> datetime:
    """Anime の candidate_registry.window_start と同じ。"""
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    step = hours * 3600
    return epoch + timedelta(seconds=int((t - epoch).total_seconds()) // step * step)


def read_foundation(conn, source: str, day: date, prof: dict) -> DayResult:
    """Game の共通の発言（player_post）を読む（Anime の read_foundation の Game 版。取得元の名前で分けない）。
    数える: 作品（app ID）に結び付き、宣伝などの印がない発言。投稿者は取得元の中の参照（author）。
    そろったか: その日が終わって落ち着いている（日次の既定の対象日以前）なら complete（取得元は日次で取りに行く）。"""
    from game_signal_scout.days import day_range, default_day
    from game_signal_scout.repositories.post import EXCLUDE
    import hashlib
    start, end = day_range(day)
    rows = conn.execute("SELECT item_id, author, lang, left(text, 30), at, appid, CASE WHEN length(text) >= %s THEN md5(text) END, flags ?| %s "
                        "FROM player_post WHERE source = %s AND at >= %s AND at < %s", (SAME_TEXT_MIN_CHARS, EXCLUDE, source, start, end)).fetchall()
    conn.rollback()
    obs = []
    for uid, actor, lang, head, at, appid, same, flagged in rows:
        wid = int(appid) if appid and str(appid).isdigit() else None
        obs.append(Obs(uid, actor, day, lang, wid, "excluded" if flagged or wid is None else "counted", head, True, at, same))
    done = day <= default_day()
    return DayResult(obs, done, None if done else "fetch_hours", f"{AGG_VERSION}|player_post", {"units": len(rows)})


READERS = {"foundation": read_foundation}


# ---------------------------------------------------------------- 共通の集計と確定（すべての Source で同じ）
def aggregate(r: DayResult) -> dict[tuple[int, str], dict]:
    """（作品・言語）→ 独立した投稿者（数える記録の異なる投稿者）と記録の数。作品のない記録は数えない。言語でない言語コードは言語の行に入れず、
    すべての言語の合計の行（'*'）にだけ入れる。"""
    people: dict[tuple[int, str], set] = defaultdict(set)
    posts: dict[tuple[int, str], int] = defaultdict(int)
    texts: dict[tuple[int, str], list] = defaultdict(list)
    for o in r.obs:
        if o.status != "counted" or o.work_id is None or not o.actor:
            continue
        # 言語 '*' = その日のすべての言語（言語を判定できない投稿を含む）の独立した投稿者（作品詳細の日ごとの人数）
        keys = [(o.work_id, TOTAL)] + ([] if o.lang in NOT_LANGUAGE else [(o.work_id, o.lang)])
        for k in keys:
            people[k].add(o.actor)
            posts[k] += 1
            if o.same_text:
                texts[k].append((o.same_text, o.actor))
    return {k: {"persons": _independent(v, texts.get(k, [])), "posts": posts[k]} for k, v in people.items()}


def _independent(actors: set, texts: list[tuple[str, str]]) -> int:
    """独立した発信元の数: 同じ本文を出した別の人たちは 1 つにまとめる（同じ文の拡散・連携した宣伝。全 Source で同じ規則）。"""
    if not texts:
        return len(actors)
    parent = {a: a for a in actors}

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    first: dict[str, str] = {}
    for h, a in texts:
        if h in first:
            parent[find(a)] = find(first[h])
        else:
            first[h] = a
    return len({find(a) for a in actors})


def finalize(conn, source: str, day: date, r: DayResult, now: datetime | None = None) -> dict:
    """その日の値を確定する。そろった（complete）なら置き換える。そろわないうちは、前に確定した値を残す（判定の遅れ・同定の版の変更で
    確定した値を消さない）。前に確定した値がなければ、その日は未確定（画面は 0 ではなく集計中）。"""
    now = now or datetime.now(timezone.utc)
    prev = observation_repo.get_day_state(conn, source, day)
    agg = aggregate(r)
    if r.complete:
        observation_repo.replace_day_counts(conn, source, day, agg, r.version, now)
        observation_repo.replace_day_posts(conn, source, day, [(o.unit, o.work_id, o.lang, o.actor, o.head, o.anime, o.at) for o in r.obs
                                                 if o.status == "counted" and o.work_id is not None and o.actor])
        state = "complete"
    elif prev and prev[0] == "complete":
        state = "complete"   # 前の確定はそのまま（判定の遅れ・同定の版の変更で消さない）
    elif r.reason in PROVISIONAL_REASONS:
        # まだ一度も確定していない日: 数えてよいと判定済みの記録だけの途中の値（人数は少なめ）。確定したら置き換える。変化の判定（obs_post）には使わない
        observation_repo.replace_day_counts(conn, source, day, agg, r.version, now)
        state = PROVISIONAL
    else:
        state = NOT_COVERED if r.reason == NOT_COVERED else "incomplete"   # 観測の範囲外の日は not_covered（集計中にしない）
    observation_repo.upsert_day_state(conn, source, day, state=state, version=r.version if r.complete else (prev[1] if prev else r.version), reason=r.reason,
                        detail={**r.detail, "rows": len(agg)}, attempted_at=now, finalized=r.complete)
    conn.commit()
    return {"source": source, "day": day.isoformat(), "state": state, "updated": r.complete, "reason": r.reason, "rows": len(agg), **r.detail}


def sources(production_only: bool = True) -> dict[str, dict]:
    """登録された Source（config/map_sources.toml）。本番で数えるのは production = true のものだけ。"""
    srcs = config.load_toml("map_sources.toml").get("sources") or {}
    return {k: v for k, v in srcs.items() if v.get("reader") in READERS and (v.get("production") or not production_only)}


def days_to_refresh(conn, day: date, recent: int = 28, keep: int = 28) -> list[date]:
    """日次処理で作り直す日: 対象日と前の recent - 1 日と、keep 日以内でまだそろっていない日（判定の遅れ・取得の不足。前に確定した値を残している日を含む）。
    判定が遅れて追いついた日を確定させる（集計中のまま残さない）。直近 28 日は毎日作り直す（削除の追従。件数ではなく日数で決まる。
    それより古い日は最後に確定した値のまま）。"""
    out = {day - timedelta(days=i) for i in range(recent)}
    try:
        out |= observation_repo.list_unsettled_days(conn, day - timedelta(days=keep), day, except_reason=NOT_COVERED)
    finally:
        conn.rollback()
    return sorted(out)


def run(conn, days: list[date], only: list[str] | None = None) -> list[dict]:
    """登録された本番の Source について、各日を読み取り → 集計 → 確定する。1 つの Source・日の失敗で全体を止めない。"""
    out = []
    for src, prof in sources().items():
        if only and src not in only:
            continue
        for d in days:
            try:
                out.append(finalize(conn, src, d, READERS[prof["reader"]](conn, src, d, prof)))
            except Exception as e:  # noqa: BLE001
                conn.rollback()
                out.append({"source": src, "day": d.isoformat(), "error": f"{type(e).__name__}: {str(e)[:200]}"})
    return out


def rows(conn, day: date) -> tuple[dict[str, list[tuple[int, str, int]]], dict[str, dict]]:
    """画面の入力: Source → [(作品, 言語, 人数)]（確定した値）と、Source → その日の状態。読むだけ。"""
    out: dict[str, list] = defaultdict(list)
    for src, wid, lang, n in observation_repo.list_work_lang_persons(conn, day):
        out[src].append((wid, lang, n))
    return dict(out), observation_repo.list_day_states(conn, day)


# ---------------------------------------------------------------- Source ごとの系列（変化の判定のページの入力。すべての Source で同じ作り）
def series_set(conn, source: str, prof: dict, first: date, as_of: date):
    """Source の確定した記録（obs_post）から、foundation/series と同じ形の系列（SeriesSet）を作る。判定（再燃・放送後も熱い・言語圏の広がり）は
    この系列に同じ関数（foundation/series.judge_*）を当てる（Source をまたいで足さない）。日の観測の状態は共通の確定の状態（complete = 観測した日）。
    6 時間の窓は、取得の記録（source_fetch）で 6 時間ぶん取れている窓（foundation/signals.windows。すべての Source で同じ規則）。"""
    from game_signal_scout.foundation import series
    dates = [first + timedelta(days=i) for i in range((as_of - first).days + 1)]
    st = observation_repo.day_states(conn, first, as_of, source=source)
    gdays = [(d, series.WINDOWS_PER_DAY if st.get(d) == "complete" else 0, "complete" if st.get(d) == "complete" else "none") for d in dates]
    ok_days = {d for d, _, o in gdays if o != "none"}
    complete = set()   # Game は 6 時間の窓の系列を使わない（日単位だけ）
    meta = work_levels(conn)
    raw: dict = {}
    for d, wid, lang, actor, head, anime, at in observation_repo.iter_complete_posts(conn, source, first, as_of):
        if wid not in meta or d not in ok_days:
            continue
        r = raw.setdefault(wid, {"days": {}, "windows": {}})
        rec = r["days"].setdefault(d, {"total": series.Agg(), "langs": {}, "linked": 0})
        rec["total"].add(actor, head, anime)
        rec["linked"] += 1
        if lang not in NOT_LANGUAGE:
            rec["langs"].setdefault(lang, series.Agg()).add(actor, head, anime)
        if at is not None and complete:
            w = window_start(at, series.WINDOW_HOURS)
            if w in complete:
                r["windows"].setdefault(w, set()).add(actor)
    conn.rollback()
    works = {}
    for wid, r in raw.items():
        lv, pid = meta[wid]
        days = []
        for d, n, o in gdays:
            rec = r["days"].get(d)
            days.append(series.Day(d, n, o, rec["total"], rec["langs"], rec["linked"]) if rec else series.Day(d, n, o))
        works[wid] = series.WorkSeries(wid, lv, pid, days, r["windows"])
    return series.SeriesSet(as_of, first, gdays, works)


def common_series(conn, first: date, as_of: date, srcs: dict | None = None):
    """画面の入力の系列: 登録された本番の Source それぞれの系列（series_set）と、それを作品 × 日で合わせた系列。
    人数は Source の中の投稿者の参照（Source の名前空間つき。base.ref）で数えるので、合わせても同じ人を二重に数えない（別の Source の人は別の人）。
    判定（再燃・放送後・言語圏の広がり）は Source ごとの系列に当てる（Source をまたいで足さない）。日の状態: 観測の範囲内のどの Source も
    そろった日は complete、一部だけそろった日は partial、どれもそろわない日は none。Source の名前で分岐しない。"""
    from game_signal_scout.foundation import series
    srcs = sources() if srcs is None else srcs
    per = {src: series_set(conn, src, prof, first, as_of) for src, prof in srcs.items()}
    states: dict[date, list[str]] = defaultdict(list)
    for src in per:
        for d, st in observation_repo.day_states(conn, first, as_of, source=src).items():
            states[d].append(st)
    conn.rollback()
    dates = [first + timedelta(days=i) for i in range((as_of - first).days + 1)]
    gdays = []
    for d in dates:
        st = [s for s in states.get(d, []) if s != NOT_COVERED]
        obs = ("complete" if st and all(s == "complete" for s in st) else "partial" if any(s == "complete" for s in st) else "none")
        gdays.append((d, series.WINDOWS_PER_DAY if obs == "complete" else 0, obs))
    works: dict[int, series.WorkSeries] = {}
    for ss in per.values():
        for wid, ws in ss.works.items():
            works.setdefault(wid, []).append(ws)
    merged = {}
    for wid, wss in works.items():
        days = []
        for d, n, o in gdays:
            xs = [x for x in (ws.at(d) for ws in wss) if x is not None]
            days.append(series.Day(d, n, o, series.Agg.merge(x.total for x in xs),
                              {lg: series.Agg.merge(x.langs[lg] for x in xs if lg in x.langs) for lg in {lg for x in xs for lg in x.langs}},
                              sum(x.linked_posts for x in xs)))
        merged[wid] = series.WorkSeries(wid, wss[0].level, wss[0].parent_id, days, {})
    return series.SeriesSet(as_of, first, gdays, merged), per


def work_levels(conn) -> dict[int, tuple[str, None]]:
    """Anime の work_repo.list_work_levels の Game 版: 作品（作品の情報のある app ID）はすべて 1 段（親なし）。"""
    out = {int(a): ("work", None) for (a,) in conn.execute("SELECT appid FROM game_profile WHERE appid ~ '^[0-9]+$'")}
    conn.rollback()
    return out
