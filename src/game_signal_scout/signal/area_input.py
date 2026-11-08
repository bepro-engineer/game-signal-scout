"""世界地図・言語ページの共通の入力（ADR 0047）。どの Source も AreaWorkDay の行に変換してから、Source を知らない集計（area_obs）に渡す。

- 「話題になった」は Source の中で判定する（profile の min_persons。共通の下限 2）。言語圏の値は、どれかの Source で話題になった作品を Work ID で重複なく数えた数。
- 人数は Source をまたいで足さない・比べない・並べない（ADR 0035 §5）。作品の人数・前日の人数は、その作品がいちばん先の Source（profile の order）の値。
- 前日比は、両日とも品質の門を通った Source だけで作る（Source を足した日・取得が欠けた日に、偽の「前日はなし」を出さない）。
- 言語圏の状態: topic / zero（観測できた Source があり、話題の作品なし）/ no_source（ゼロとして出さない）。
- 将来「今日の兆し」「世界で広がる作品」も rows() を入力にできる（いまは地図・言語ページだけ。D4）。
入力は全 Source 共通の観測の集計（sources/observations.py・ADR 0050）だけ。Source を足すときは config/map_sources.toml に登録するだけで、ここは変えない。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone


from game_signal_scout.repositories import foundation as foundation_repo, observation as observation_repo, source_item, work as work_repo

from game_signal_scout.languages import NOT_LANGUAGE  # noqa: E402

TOTAL_ROW = "*"   # '*' は共通の集計の「すべての言語の合計」の行（言語圏ではない）


@dataclass(frozen=True)
class AreaWorkDay:
    source: str
    day: date
    area: str            # 言語圏（投稿の言語。国ではない）
    script: str | None   # 文字の区別（Hant / Hans / None）。内部だけに持つ（D2）
    work_id: int
    persons: int         # Source の中の異なる人（Source の定義のまま）
    version: str         # その行を作った版（集計・同定・判定）


def _area(prof: dict, code: str) -> tuple[str, str | None]:
    """投稿の言語コード → (言語圏, 文字)。Source の profile の対応が先、なければ共通の言語圏の対応表（方言のコードをまとめる。ADR 0049）。"""
    m = (prof.get("lang_to_area") or {}).get(code)
    if m:
        return (m[0], m[1] if len(m) > 1 else None)
    from game_signal_scout.signal import language_areas
    return (language_areas.area_of(code), None)


def _to_ctx_work(ctx, w: int | None) -> int | None:
    """Source の Work を、Viewer の作品（ctx.works。作品のページがある単位）に寄せる。同じ作品か、その親（作品群）。"""
    if w is None:
        return None
    if w in ctx.works:
        return w
    p = work_repo.get_parent_id(ctx.conn, w)
    return p if p in ctx.works else None


# ---------------------------------------------------------------- 入力（すべての Source で同じ 1 つの読み方。ADR 0050）
def observed(ctx, d: date, src: str, prof: dict) -> tuple[list[AreaWorkDay], dict]:
    """全 Source 共通の観測の集計（sources/observations.py が確定した obs_work_lang_day）だけを読む。Source ごとの変換はない。
    状態: その日の値が確定していれば ok（判定の遅れ・同定の版の変更の間も前の確定を使う）、一度も確定していなければ incomplete（0 にしない）。"""
    from game_signal_scout import source_terms
    if prof.get("noncommercial_only") and not source_terms.allowed(src):
        return [], {"ok": False, "state": "unavailable", "reason": "operating_mode"}
    from game_signal_scout import observations
    cache = ctx.__dict__.setdefault("_obs_rows", {})
    if d not in cache:
        cache[d] = observations.rows(ctx.conn, d)
        ctx.conn.rollback()
    rows_by_src, states = cache[d]
    st = states.get(src)
    if st and st["state"] == observations.NOT_COVERED:
        return [], {"ok": False, "state": "absent", "reason": observations.NOT_COVERED}   # その日は観測の範囲外: その Source がないのと同じ（集計中・0 にしない）
    partial = bool(st and st["state"] == observations.PROVISIONAL)   # 判定済みの分だけの途中の値（数は少なめ。前日と比べない）
    if not st or st["state"] not in ("complete", observations.PROVISIONAL):
        return [], {"ok": False, "state": "incomplete", "reason": (st or {}).get("reason") or "not_aggregated"}
    out = []
    for wid, lang, n in rows_by_src.get(src, []):
        w = _to_ctx_work(ctx, wid)
        if w is None or lang in NOT_LANGUAGE or lang == TOTAL_ROW:
            continue
        area, script = _area(prof, lang)
        out.append(AreaWorkDay(src, d, area, script, w, n, "obs"))
    return out, {"ok": True, "state": "partial" if partial else "ok", "pending": st.get("reason")}


# ---------------------------------------------------------------- Source を知らない集計
def rows(ctx, d: date, profiles: dict) -> tuple[dict[str, list[AreaWorkDay]], dict[str, dict]]:
    """その日の Source ごとの行と品質の門の結果（日ごとに 1 回だけ作る）。"""
    cache = ctx.__dict__.setdefault("_area_rows", {})
    if d not in cache:
        out, gates = {}, {}
        for src, prof in sorted(profiles["sources"].items(), key=lambda x: x[1].get("order", 99)):
            r, g = observed(ctx, d, src, prof)
            gates[src] = g
            if g.get("ok"):
                out[src] = r
        cache[d] = (out, gates)
    return cache[d]


def _qualified(rs: list[AreaWorkDay], prof: dict) -> dict[tuple[str, int], AreaWorkDay]:
    m = max(2, int(prof.get("min_persons", 2)))   # 下限は下げない
    return {(r.area, r.work_id): r for r in rs if r.persons >= m}


def area_obs(ctx, d: date, profiles: dict, countries: dict, comparable_base: bool) -> dict:
    """lang_obs（地図・言語ページ）を作る。Source が 1 つだけなら、その Source の lang_obs と同じ値になる（取得元の名前で分けない）。"""
    srcs = profiles["sources"]
    today, g_today = rows(ctx, d, profiles)
    prev, g_prev = rows(ctx, d - timedelta(days=1), profiles)
    q = {s: _qualified(rs, srcs[s]) for s, rs in today.items()}
    qp = {s: _qualified(rs, srcs[s]) for s, rs in prev.items()}
    seen = {s: {(r.area, r.work_id): r for r in rs} for s, rs in today.items()}
    seen_p = {s: {(r.area, r.work_id): r for r in rs} for s, rs in prev.items()}
    full = lambda g: g.get("ok") and g.get("state") != "partial"   # noqa: E731 — 途中の値の日は比べない
    cmp_src = {s for s in today if s in prev and full(g_today[s]) and full(g_prev[s])}   # 両日とも確定した Source だけで前日と比べる
    areas: dict[str, dict] = {}
    for s in sorted(q, key=lambda s: srcs[s].get("order", 99)):
        for (area, w), r in q[s].items():
            a = areas.setdefault(area, {"works": {}, "scripts": set(), "sources": set()})
            a["scripts"].add(r.script)
            a["sources"].add(s)
            a["works"].setdefault(w, []).append(s)
    langs = []
    for area, a in areas.items():
        works = []
        for w, ss in a["works"].items():
            by = []
            for s in ss:
                r, rp = q[s][(area, w)], seen_p.get(s, {}).get((area, w))
                by.append({"src": s, "label": srcs[s].get("label") or [s, s], "script": r.script, "n": r.persons, "prev": rp.persons if (rp and s in cmp_src) else 0, "cmp": s in cmp_src})
            works.append((w, by))
        works.sort(key=lambda x: (-len(x[1]), srcs[x[1][0]["src"]].get("order", 99), -x[1][0]["n"], x[0]))
        a_cmp = all(s in cmp_src for s in {s for _, by in works for s in (b["src"] for b in by)})
        prev_n = len({w for s in cmp_src for (ar, w) in qp.get(s, {}) if ar == area})
        scope = {"sources": sorted(a["sources"], key=lambda s: srcs[s].get("order", 99)), "scripts": sorted(x or "unknown" for x in a["scripts"])}
        langs.append({"code": area, "name": _lname(area), "n": len(works), "prev": prev_n, **({} if a_cmp else {"cmp": False}), "scope": scope,
                      "works": [ctx.ref(w, n=by[0]["n"], prev=by[0]["prev"], **({"by_source": by} if len(srcs) > 1 else {})) for w, by in works]})
    # 観測の状態（ADR 0048）: 門で incomplete の Source（収集・集計・判定が未完了）が観測する言語圏は「集計中」、unavailable の Source
    # （運用モードで使えない・設定がない）だけが観測する言語圏は「Source なし」。どちらも 0 作品として出さない・前の結果を流用しない
    def areas_of(s):
        return {v[0] for v in (srcs[s].get("lang_to_area") or {}).values()}
    incomplete = {a for s, g in g_today.items() if not g.get("ok") and g.get("state", "incomplete") == "incomplete" for a in areas_of(s)}
    # 途中の値（判定済みの分だけ）の Source が観測する言語圏も「集計の終わっていない言語圏」: 話題の作品があれば一部集計中として出し、なければ集計中
    incomplete |= {a for s, g in g_today.items() if g.get("ok") and g.get("state") == "partial" for a in areas_of(s)}
    unavailable = {a for s, g in g_today.items() if not g.get("ok") and g.get("state") == "unavailable" for a in areas_of(s)}
    for x in langs:
        if x["code"] in incomplete:
            x["partial"] = True   # 話題の作品はあるが、この言語圏を観測する Source のうち集計の終わっていないものがある（数は少なめ・前日比を出さない）
            x["cmp"] = False
    have = {x["code"] for x in langs}
    # 一覧（langs）は、この日 1 作品以上の言語だけ（地図の色と同じ条件）。観測した Source の集計が終わっているのに条件を満たす作品がなかった言語は
    # zero（「ほかに観測した言語: 話題になった作品はなし」）。前日に作品があった言語も 0 作品の行・前日比（「0 −1」）にしない
    # （観測の条件を満たす作品がなかったことで、話題や関心が消えたことではない。#44）。集計中の言語圏は zero にもしない
    prev_areas = {area for s in cmp_src for (area, _w) in qp.get(s, {})}
    zero = sorted(({area for s in seen for (area, _w) in seen[s]} | prev_areas) - have - incomplete)
    # 地図の国・地域は共通の言語圏の対応表（config/language_areas.toml。多対多。色は言語圏で統一し、文字・Source で変えない。ADR 0049）
    from game_signal_scout.signal import language_areas
    lv = language_areas.for_view([x["code"] for x in langs] + sorted(incomplete) + [x["code"] for x in _thin_areas(ctx, d, set())])   # 観測した言語圏・集計中の言語圏の国・役割（主要 / 共通語）・理由（ADR 0049）
    cn = {**dict(countries), **lv["countries"]}
    pending = sorted(incomplete - have)
    thin = _thin_areas(ctx, d, have | incomplete)   # 1 人だけ観測された言語圏（zero）も、量が少なければ「観測が届いていない」と示す
    no_source = sorted(unavailable - have - set(zero) - incomplete)
    # 並びは作品数の多い順・同じ数なら言語コードの順（画面と同じ。同じ入力から毎回同じファイルにする。#18）
    return {"comparable": comparable_base, "langs": sorted(langs, key=lambda x: (-x["n"], x["code"])), "zero": [{"code": z, **_lname(z)} for z in zero],
            "countries": cn, "country_roles": lv["roles"], "country_why": lv["why"], **({"incomplete": [{"code": z, **_lname(z)} for z in pending]} if pending else {}),
            **({"no_source": no_source} if no_source else {}), **({"thin": thin} if thin else {})}, {"gates": g_today, "gates_prev": g_prev}


def _thin_areas(ctx, d: date, shown: set) -> list[dict]:
    """観測が届いていない言語圏（MULTI-SOURCE-DESIGN 付記 2026-10-09: 観測値ゼロと未整備を区別する。ADR 0049）。
    人数の閾値では決めない: 主要な社会言語の国がある言語圏のうち、直近 14 日に地図の条件（同じ日に同じ作品を 2 人以上）を一度も満たしていないもの。
    どこで止まっているか（stage）と直近 7 日の件数を持つ: collection_stopped（収集が止まっている）/ no_posts（その言語の投稿が集まっていない）/
    no_anime（アニメの投稿がない）/ not_identified（作品を同定できない）/ below_condition（同定できたが 2 人に届かない）。
    材料は共通の原文の表（source_item）と共通層（utterance・判定・共通の集計）だけ（Source の名前で分岐しない。ADR 0054）。"""
    from game_signal_scout.signal import language_areas
    from game_signal_scout.days import day_range
    cache = ctx.__dict__.setdefault("_thin", {})
    if getattr(ctx, "conn", None) is None:   # DB のない試験
        return [x for x in cache.get(d, []) if x["code"] not in shown]
    if d not in cache:
        # 公開する日をまとめて 1 回ずつ数える（日ごとに 7 日・14 日の窓を数え直すと、日数 × 4 回の重い問い合わせになる。#18）。
        # 窓の端は放送日の区切り（3:00 JST）なので、放送日ごとの件数の和は、日ごとに窓で数えた値と同じ
        days = sorted(set(getattr(ctx, "pdays", None) or []) | {d})
        c = ctx.conn
        lo, hi = day_range(days[0] - timedelta(days=13))[0], day_range(days[-1])[1]
        per: dict[tuple[str, date], dict] = {}

        def add(rows, key):
            for lg, day, n in rows:
                st = per.setdefault((language_areas.area_of(lg or ""), day), {"collected": 0, "anime": 0, "identified": 0, "qualified_days": 0})
                st[key] += n
        add(source_item.count_items_by_lang_day(c, lo, hi), "collected")
        add(foundation_repo.count_anime_utterances_by_lang_day(c, lo, hi), "anime")
        add(foundation_repo.count_identified_utterances_by_lang_day(c, lo, hi), "identified")
        add(observation_repo.count_language_days(c, days[0] - timedelta(days=13), days[-1], min_persons=2), "qualified_days")
        fresh = source_item.get_last_ok_fetch_of_any_source(c)
        c.rollback()
        roles = language_areas.roles()
        for x in days:
            e = day_range(x)[1]
            stopped = fresh is None or (e <= datetime.now(timezone.utc) + timedelta(days=1) and fresh < min(e, datetime.now(timezone.utc)) - timedelta(minutes=60))
            stats: dict[str, dict] = {}
            for (a, day), st in per.items():
                age = (x - day).days
                if 0 <= age < 14:
                    t = stats.setdefault(a, {"collected": 0, "anime": 0, "identified": 0, "qualified_days": 0})
                    t["qualified_days"] += st["qualified_days"]
                    if age < 7:
                        for k in ("collected", "anime", "identified"):
                            t[k] += st[k]
            out = []
            for a in sorted(roles):
                if not any(r == "p" for r in roles[a].values()):
                    continue
                st = stats.get(a, {"collected": 0, "anime": 0, "identified": 0, "qualified_days": 0})
                if st["qualified_days"] > 0:
                    continue
                stage = ("collection_stopped" if stopped else "no_posts" if st["collected"] == 0 else "no_anime" if st["anime"] == 0
                         else "not_identified" if st["identified"] == 0 else "below_condition")
                out.append({"code": a, **_lname(a), "stage": stage, "collected7": st["collected"], "anime7": st["anime"], "identified7": st["identified"]})
            cache[x] = out
    return [x for x in cache[d] if x["code"] not in shown]


def _lname(code: str) -> dict:
    from game_signal_scout.signal.content import lname
    return lname(code)
