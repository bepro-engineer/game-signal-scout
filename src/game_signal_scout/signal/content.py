"""画面の内容の組み立て（ADR 0056）。データベースは読むだけ。公開の Service（publication/publishing）が、材料の版が変わるたびに
ここの関数で公開用の文書を作る。公開の前の検査（audit_public）もここ。書き込みと外部への問い合わせは別の module:
世界で広がる作品の文章の生成と保存は publication/spread_digest、画面が読む記録の取り直しは publication/inputs。

作る内容: 公開した日の一覧（days）、日ごとのダッシュボード・世界で広がる・言語別（dashboard・spread）、最新の日の価値ページ（pages）、
作品を探す（search）、作品詳細（work_detail）。入力は全 Source 共通の基盤だけ（ADR 0054）: 共通の観測の集計（obs_*）の系列、共通の Signal 発見
（foundation/signals）、発言の分類（observation）、作品の台帳。判定は共通の関数のまま（foundation/series・foundation/signals・publication/movement）。
ここでは並べ替え・数え直し（重複を除いた人数）・文の組み立てだけを行い、閾値を変えない。
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import time
from collections import Counter
from datetime import date, timedelta

from game_signal_scout import config, db
from game_signal_scout.foundation import series
from game_signal_scout.days import MON_EN
from game_signal_scout.sources import factory
from game_signal_scout.ops import work
from game_signal_scout.repositories import foundation as foundation_repo, job as job_repo, observation as observation_repo, session, work as work_repo
from game_signal_scout.signal import catalog_extra, language_areas, links

log = logging.getLogger(__name__)

WD = {"ja": "月火水木金土日", "en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]}
from game_signal_scout.languages import NAMES, NOT_LANGUAGE  # noqa: E402
TOPIC_MIN = 2               # 「話題になった」= その日 2 人以上（本番の地図・一覧と同じ数え方）
# 放送後も熱い（#26）: 判定の結果 → 作品の状態（読者に見せる区分）。None = 判定に通った。not_finished・no_end_date は終わった作品の一覧に入れない
PA_STATE = {None: "hot", "small": "thin", "not_independent": "thin", "weak_anchor": "thin", "faded": "faded",
            "in_settle": "early", "few_after_days": "early", "weak_baseline": "low_before", "few_baseline_days": "no_before", "no_baseline": "no_before"}
PA_ORDER = ["hot", "thin", "faded", "early", "low_before", "no_before"]                       # 一覧の順（話題が続いている作品を先頭に）
PA_DEPTH = {"no_before": 0, "low_before": 1, "early": 2, "faded": 3, "thin": 4, "hot": 5}       # 判定がどこまで進んだか（取得元の系列の中で選ぶ）
# 価値ページの並び順の既定（人気の順ではなく、その作品自身の変化: 人数・日数・比）
PAGE_SORT = {
    "revival": lambda s: (-s["revive_authors"], -s["quiet_days"]),
    "post_air": lambda s: (-s["after_median"], -s["ratio"]),
    "language_spread": lambda s: (-s["new_authors"], -date.fromisoformat(s["first_day"]).toordinal()),
}


def connect():
    """読み取りだけの接続（session を read only にし、autocommit にする）。写しを作る間は数分かけて多くの問い合わせを出すので、
    1 つの取引を開いたままにしない（2026-10-25: 取引を開いたままの接続を DB 側が idle_in_transaction_session_timeout で切り、
    写しを作り直せず古い画面が残った）。読むだけなので autocommit で意味は変わらない（取引の分離は既定の READ COMMITTED のまま）。
    分類の改善の判定に本文・除外の印を読むが、本文は判定だけに使い、書き出す JSON には入れない。"""
    conn = db.connect(autocommit=True)
    session.set_read_only(conn)
    return conn




def lname(code: str) -> dict:
    """言語コード → 画面の言語名。文字・地域の区別のコード（zh-Hant・zh-Hans など）は言語圏にまとめる（config/language_areas.toml の aliases。区別は内部だけ）。"""
    code = language_areas.area_of(code)
    ja, en = NAMES.get(code, (code, code))
    return {"ja": ja, "en": en}


def _unique(names: list[dict]) -> list[dict]:
    """同じ言語圏の名前を 1 回にする（zh-Hant と zh-Hans は同じ「中国語」）。並びは最初に出た順。"""
    return [n for i, n in enumerate(names) if n not in names[:i]]


def dlabel(d: date) -> dict:
    return {"ja": f"{d.year}年{d.month}月{d.day}日（{WD['ja'][d.weekday()]}）", "en": f"{WD['en'][d.weekday()]}, {MON_EN[d.month - 1]} {d.day}, {d.year}",
            "md": f"{d.month}/{d.day}", "w": {"ja": WD["ja"][d.weekday()], "en": WD["en"][d.weekday()]}}


class NoObservedDayError(RuntimeError):
    """観測をそろえた日・公開できる日がまだない（観測を始めた直後・試験の空の表）。段の失敗として記録される（SystemExit にしない: 日次の段の受け止めを素通りする）。"""


class Ctx:
    """1 回の事前計算で共有するもの（系列・作品の名前と画像・作品情報）。"""

    def __init__(self, conn, cfg: dict, as_of: date | None = None):
        """入力は全 Source 共通の観測（sources/observations.py の obs_post・obs_day_state）だけ。Source の名前を知らない（ADR 0050・0051）。
        表示する日 = 登録された本番の Source のどれかが観測をそろえた日（公開の開始日から）。"""
        from game_signal_scout import observations
        self.conn, self.cfg = conn, cfg
        start = date.fromisoformat(str(cfg["publish"]["start_day"]))
        self.sources = observations.sources()
        # 地図・言語ページ・作品詳細の取得元（登録された本番の取得元。ADR 0047・0050）。作るのはここ 1 か所
        self.map_sources = {**config.load_map_sources_config(), "sources": dict(self.sources)}
        self.ui_next = False          # 今日の兆しの先頭の組（[dashboard_digest] enabled。公開の Service が付ける）
        self.astore, self.aid2w = None, {}   # 作品詳細の追加の作品情報（公開の Service が付ける）
        top = as_of or observation_repo.latest_complete_day(conn, list(self.sources))[0]
        conn.rollback()
        if top is None:
            raise NoObservedDayError("観測をそろえた日がない")
        self.latest = top
        pages = self.pages = series.load_pages()   # 画面の判定の閾値（config/pages.toml）
        lookback = max(int(pages["common"]["lookback_days"]), (self.latest - start).days + 1)
        first = self.latest - timedelta(days=lookback - 1)
        t0 = time.perf_counter()
        self.ss, self.sss = observations.common_series(conn, first, self.latest, self.sources)
        self.pdays = [d for d, _, st in self.ss.days if st != "none" and d >= start]
        if not self.pdays:
            raise NoObservedDayError("公開できる日がない")
        ok = set(work.publishable_works(conn, list(self.ss.works)))
        self.works = {w: ws for w, ws in self.ss.works.items() if w in ok}
        log.info("系列 %d 作品（公開できる %d・Source %s）%.1fs", len(self.ss.works), len(self.works), ",".join(self.sss), time.perf_counter() - t0)
        self.gobs = {d: st for d, _, st in self.ss.days}                     # 分析に使える状態（complete / partial / none）
        self._cards()
        self._briefs = None
        self._profiles: dict[int, dict] = {}
        self._catalog = None
        self.tstore = None   # 訳文の保存先（publication/inputs.translate_missing で決める）
        self.lstore = None   # 外部リンクの確認の記録（publication/inputs.check_links で決める）

    def profile(self, w: int) -> dict:
        """作品情報（表示する期）。表示と翻訳の対象は、この 1 か所の結果を使う（catalog/profile.work_profile）。"""
        if w not in self._profiles:
            from game_signal_scout import catalog
            from game_signal_scout.catalog import profile
            if self._catalog is None:   # 作品情報の表は 1 回だけ読む（作品ごとに問い合わせない。#18）
                self._catalog = profile.CatalogView(self.conn, catalog.provider_name(catalog.load_settings()))
            self._profiles[w] = profile.work_profile(self.conn, w, self.works[w].level, self.latest, view=self._catalog) or {}
            self.conn.rollback()
        return self._profiles[w]

    def _cards(self):
        """作品の名前（ja / en）と画像（作品の台帳だけから。ops/work_display.py）。"""
        from game_signal_scout.ops import work_display
        ids = list(self.works)
        self.keys = work_repo.list_keys_by_work(self.conn, ids)
        self.meta = work_display.work_meta(self.conn, ids)
        for w in ids:
            self.meta.setdefault(w, {"id": f"w{w}", "name": {"ja": str(w), "en": str(w)}, "cover": None, "banner": None})

    @property
    def briefs(self) -> dict:
        if self._briefs is None:   # 作品詳細と同じ 1 回の作品情報から（同じ作品を 2 回調べない）
            from game_signal_scout.catalog import profile
            self._briefs = {w: b for w in self.works if (b := profile.brief(self.profile(w)))}
        return self._briefs

    def authors(self, w: int, d: date) -> int:
        day = self.works[w].at(d) if hasattr(self.works[w], "at") else None
        return day.authors if day is not None else 0

    def day_map(self, d: date) -> dict[int, int]:
        """その日の作品ごとの投稿者数（1 人以上）。"""
        out = {}
        for w, ws in self.works.items():
            x = ws.at(d)
            if x is not None and x.authors:
                out[w] = x.authors
        return out

    def lang_map(self, d: date) -> dict[str, dict[int, int]]:
        """その日の言語 → 作品 → 投稿者数。"""
        out: dict[str, dict[int, int]] = {}
        for w, ws in self.works.items():
            x = ws.at(d)
            if x is None:
                continue
            for lg, a in x.langs.items():
                if lg not in NOT_LANGUAGE and a.authors:
                    out.setdefault(lg, {})[w] = a.authors
        return out

    def ref(self, w: int, **extra) -> dict:
        return {**self.meta[w], **extra}


def _judge(m: dict) -> dict:
    """日本人が作品を選ぶときに最初に見る属性（#2）: 日本語の UI・字幕・音声（jp。null = 未確認）、開発元と国・地域（dev）、機種（plat）、日本向けの価格（price。なければ未確認）。"""
    return {k: m.get(k) for k in ("jp", "jp_at", "dev", "plat", "price") if k in m}


# ---------------------------------------------------------------- ダッシュボード（公開した日ごと）
def _complete(ctx: Ctx, d: date) -> bool:
    return ctx.gobs.get(d) in ("complete", "recovered")   # recovered（再取得で埋まったと検証できた日）は比べる対象に含める


def day_stats(ctx: Ctx, d: date) -> dict:
    """その日の「話題になった作品」（2 人以上）の数・人数の合計・上位 5 作品の人数・1 位。"""
    m = {w: n for w, n in ctx.day_map(d).items() if n >= TOPIC_MIN}
    top = sorted(m.items(), key=lambda x: (-x[1], x[0]))
    return {"day": d.isoformat(), **dlabel(d), "complete": _complete(ctx, d), "observed": ctx.gobs.get(d, "none"), "works": len(m),
            "all": sum(m.values()), "top5": sum(n for _, n in top[:5]), "top": [ctx.ref(w, n=n) for w, n in top[:5]]}


def turnover(ctx: Ctx, d: date) -> dict | None:
    """前日と比べた顔ぶれの入れ替わり（両方の日が一日を通して観測できたときだけ）。"""
    p = d - timedelta(days=1)
    if not (_complete(ctx, d) and _complete(ctx, p)):
        return None
    a = {w: n for w, n in ctx.day_map(d).items() if n >= TOPIC_MIN}
    b = {w: n for w, n in ctx.day_map(p).items() if n >= TOPIC_MIN}
    cont = [w for w in a if w in b]
    return {"day": d.isoformat(), **dlabel(d), "entered": len([w for w in a if w not in b]), "left": len([w for w in b if w not in a]),
            "up": sum(1 for w in cont if a[w] > b[w]), "same": sum(1 for w in cont if a[w] == b[w]), "down": sum(1 for w in cont if a[w] < b[w]),
            "entered_ids": [w for w in a if w not in b]}


def first_day(ctx: Ctx, w: int) -> date | None:
    for x in ctx.works[w].days:
        if x.authors >= TOPIC_MIN:
            return x.day
    return None


def _digest_work_ids(works: list) -> list[int]:
    """今日の兆しが選んだ作品の work_id（重なりを除き、選んだ順。記録はすべて work_id を持つ: 2026-10-28 に本番の全 52 件で確かめた）。"""
    return list(dict.fromkeys(w["work_id"] for w in works or [] if w.get("work_id")))


def _movement(ctx: Ctx, d: date) -> dict | None:
    """Q1・Q2 の分析（publication/movement.py。全 Source 共通の系列と Signal 発見だけ）。作れない日は None（画面はその段を出さない理由を示す）。
    各作品に、その日に何が起きたか（中心の出来事と自分の言葉の反応。publication/work_events が行の人数と同じ投稿から作って確かめた記録）を添える（_with_events）。"""
    from game_signal_scout.signal import movement
    try:
        return _with_events(ctx, d, movement.analyze(ctx, d))
    except Exception as e:  # noqa: BLE001
        ctx.conn.rollback()
        log.warning("movement %s: %s", d, e)
        return None


def _with_events(ctx: Ctx, d: date, mv: dict) -> dict:
    """Q1・Q2 の作品の行に、人数の変化（A）とは別に、中心の出来事（B）と自分の言葉の反応（C）を添える（Issue #28）。保存した記録を読むだけ
    （新しい生成はしない）。行と同じ取得元の記録だけ（出どころの違う数字を 1 行に混ぜない。TODAYS-SIGNAL-PAGES §0.7）。"""
    if not (ctx.cfg.get("work_events") or {}).get("enabled", False):   # 旗が切なら何も添えない（旧い記録も出さない）
        return mv
    from game_signal_scout.signal import work_events
    try:
        ev = work_events.for_rows(ctx.conn, d)
    finally:
        ctx.conn.rollback()
    for r in work_events.rows_of(mv):
        x = ev.get((r.get("src"), int(str(r["id"]).lstrip("w"))))
        if x:
            r["what"] = x
    return mv


def dash_digest(ctx: Ctx, d: date) -> dict:
    """ダッシュボードの今日の兆し（ops/dashboard_digest.py。世界で広がる作品の今日の兆しとは別の文章）。
    [dashboard_digest] enabled が false の間は {"enabled": False}（画面はこれまでどおり）。"""
    if not (ctx.cfg.get("dashboard_digest") or {}).get("enabled", False):
        return {"enabled": False}
    from game_signal_scout.ops import dashboard_digest
    try:
        x = dashboard_digest.stored(ctx.conn, d) or {}
    except Exception as e:  # noqa: BLE001 — 読めなくても画面は作る（文章のない日と同じ扱い）。理由は記録に残す
        ctx.conn.rollback()
        log.warning("今日の兆しの記録を読めない %s: %s", d, e)
        x = {}
    ctx.conn.rollback()
    return {"enabled": True, "ja": x.get("ja"), "en": x.get("en"), "sents": x.get("sents") or {}, "cites": x.get("cites") or {}, "works": x.get("works") or [],
            "evidence": x.get("evidence") or []}


def visible_cites(ctx: Ctx, cites: list[dict] | None) -> list[dict]:
    """今日の兆しの引用の欄を、配信の時点の状態で絞る（ADR 0037・0052）: 取得元の Adapter の quotable（投稿者の状態・投稿の内容のラベル。生成の後に付いたものも外す）。
    記録に取得元と項目の ID のない引用は出さない（確かめられない）。文章は記録のまま（引用だけを外す）。公開の形には取得元・項目の ID を含めない。"""
    cites = [c for c in (cites or []) if c.get("url") and c.get("source") and c.get("item")]
    by_src: dict[str, list[str]] = {}
    for c in cites:
        by_src.setdefault(c["source"], []).append(c["item"])
    ok = set()
    for src, items in by_src.items():
        ad = factory.reader_for(src)
        ok |= {(src, i) for i in (ad.quotable(ctx.conn, items) if ad else set())}
    ctx.conn.rollback()
    return [{k: v for k, v in c.items() if k not in ("source", "item")} for c in cites if (c["source"], c["item"]) in ok]


def dash_lead(ctx: Ctx, dd: dict, summary: dict) -> dict:
    """ダッシュボードの先頭の組（ADR 0052）: 今日の兆しの見出し・本文・引用と、作品の列の先頭の作品を 1 つの発見から作る。
    発見の文章（dd。日英とも検査に合格）があればその作品、なければ集計の見出し（Q1 の分析: 作品自身の普段と比べた変化）とその作品。
    言語ごとに別の基準で文章を選ばない（1 つの言語だけ文章がある日に、文章と作品が別々になっていた: 10/11）。"""
    ids = [w for w in _digest_work_ids(dd.get("works")) if w in ctx.works] if dd.get("enabled") else []
    sents = dd.get("sents") or {}
    if ids and dd.get("ja") and dd.get("en") and sents.get("ja") and sents.get("en"):
        return {"kind": "finding", "work": f"w{ids[0]}", "evidence": dd.get("evidence") or [],
                **{loc: {"head": sents[loc][0], "body": sents[loc][1:], "cites": visible_cites(ctx, (dd.get("cites") or {}).get(loc)),
                         "names": [w.get(loc) for w in dd.get("works") or [] if w.get(loc)]} for loc in ("ja", "en")}}
    return {"kind": "aggregate", "work": summary.get("work"),
            **{loc: {"head": summary["head"][loc], "body": [summary["lede"][loc]] if summary.get("lede") else [], "cites": []} for loc in ("ja", "en")}}


def summarize(today: dict, focus_share: float, mv: dict | None = None) -> dict:
    """今日の兆しの見出しと説明（AI の解説がない日に出す、数から組み立てた事実の文 = 仕様 §0.3 の集計の見出し）と、Q1・Q2 の答えの文。原因は書かない。
    見出しは Q1 の分析（作品それぞれの普段と比べた変化。publication/movement.headline）から組む。分析がない日だけ、これまでの数の文。"""
    top_n = today["top"][0]["n"] if today["top"] else 0
    focused = bool(today["top"]) and today["all"] and today["top"][0]["n"] / today["all"] >= focus_share
    if focused:
        w = today["top"][0]["name"]
        head = {"ja": f"今日は『{w['ja']}』に話題が集まった。", "en": f"Today, the buzz gathered around {w['en']}."}
        lede = {"ja": f"いちばん話題の作品に{top_n}人が集まり、話題全体の{round(today['top'][0]['n'] / today['all'] * 100)}%を占めました。",
                "en": f"The most talked-about title drew {top_n} people, {round(today['top'][0]['n'] / today['all'] * 100)}% of all the buzz."}
    else:
        head = {"ja": "今日は、さまざまなアニメが話題に。", "en": "Today, many different anime were in the conversation."}
        lede = {"ja": "この日は特定の作品に反応が集中せず、多くの作品に関心が向きました。",
                "en": "Reactions were not concentrated on any one title; interest was spread across many."}
    from game_signal_scout.signal import movement
    hl = movement.headline(mv)
    if hl:
        head, lede = hl["head"], hl["lede"]
    # basis: 見出しの根拠（movement = Q1 の分析。画面は下の作品の列を見出しの例として紹介しない: 列は話題になった作品で、動いた作品とは限らない）
    return {"head": head, "lede": lede, "focused": focused, "basis": "movement" if hl else "counts", "work": (hl or {}).get("work")}


def dashboard(ctx: Ctx, d: date) -> dict:
    """1 日分のダッシュボード（共通の系列・共通の Signal 発見・保存した今日の兆しだけから）。"""
    win = [x for x in ctx.pdays if x <= d][-10:]                                   # 推移は公開した日のうち直近 10 日
    days = [day_stats(ctx, x) for x in win]
    today = days[-1]
    m = {w: n for w, n in ctx.day_map(d).items() if n >= TOPIC_MIN}
    ranked = sorted(m.items(), key=lambda x: (-x[1], x[0]))
    cut = ranked[9][1] if len(ranked) >= 10 else (ranked[-1][1] if ranked else 0)   # 上位 10 作品（同じ人数は含める）
    top = [ctx.ref(w, n=n, first=first_day(ctx, w) == d, rs=(ctx.briefs.get(w) or {}).get("status")) for w, n in ranked if n >= cut][:15]
    comp = [x for x in days if x["complete"]]
    shape = [{**x, "focused": bool(x["top"]) and x["all"] > 0 and x["top"][0]["n"] / x["all"] >= ctx.pages["dashboard"]["focus_share"]} for x in comp[-3:]]   # 比べる 3 日。focused = 1 つの作品に集中
    # 入れ替わり: その日と前日がそろった日（recovered を含む）を最大 7 日（Q1 の表と同じ日数。モックの 4 日は、当時に比べられる日が 4 日しかなかった結果）
    turns = [t for t in (turnover(ctx, x) for x in win) if t][-7:]
    # 新しく加わった作品の放送の状況（作品情報の status）
    br = ctx.briefs
    st = lambda w: (br.get(w) or {}).get("status") or "unknown"  # noqa: E731
    entrants = {"by_day": [{"day": t["day"], "md": t["md"], "upcoming": sum(1 for w in t["entered_ids"] if st(w) == "upcoming")} for t in turns],
                "today": dict(Counter(st(w) for w in (turns[-1]["entered_ids"] if turns and turns[-1]["day"] == d.isoformat() else [])))}
    for t in turns:
        t.pop("entered_ids")
    # 1 位の作品の偏り（各日の 1 位の人数・上位 5 作品の割合・1 位の割合。1 位が前日の 2 倍以上かつ 20 人以上なら「急増」）
    t1 = []
    for x in comp[-7:]:
        if not x["top"]:
            continue
        w1 = int(x["top"][0]["id"][1:])
        prev = ctx.authors(w1, date.fromisoformat(x["day"]) - timedelta(days=1))
        ties = sum(1 for y in x["top"] if y["n"] == x["top"][0]["n"]) - 1
        t1.append({"day": x["day"], "md": x["md"], "w": x["w"], "work": x["top"][0], "n": x["top"][0]["n"], "ties": ties, "prev": prev,
                   "top5_share": x["top5"] / x["all"] if x["all"] else 0, "top1_share": x["top"][0]["n"] / x["all"] if x["all"] else 0,
                   "spike": x["top"][0]["n"] >= ctx.pages["dashboard"]["spike_min_people"] and x["top"][0]["n"] >= ctx.pages["dashboard"]["spike_ratio"] * max(prev, 1)})
    # 言語ごとに話題になった作品の数（その日 2 人以上の言語ごとの作品）。前日と比べられるのは前日も一日を通して観測できたとき
    lm, lp = ctx.lang_map(d), ctx.lang_map(d - timedelta(days=1))
    langs = []
    for lg, ws in lm.items():
        n = {w: a for w, a in ws.items() if a >= TOPIC_MIN}
        if not n:
            continue
        langs.append({"code": lg, "name": lname(lg), "n": len(n), "prev": sum(1 for a in lp.get(lg, {}).values() if a >= TOPIC_MIN),
                      "works": [ctx.ref(w, n=a, prev=lp.get(lg, {}).get(w, 0)) for w, a in sorted(n.items(), key=lambda x: (-x[1], x[0]))]})
    for lg, ws in lp.items():   # 前日に話題の作品があった言語は、この日 0 作品でも行に残す（モックと同じ）
        if lg not in {x["code"] for x in langs} and lg not in NOT_LANGUAGE and any(a >= TOPIC_MIN for a in ws.values()):
            langs.append({"code": lg, "name": lname(lg), "n": 0, "prev": sum(1 for a in ws.values() if a >= TOPIC_MIN), "works": []})
    zero = sorted(lg for lg in lm if lg not in {x["code"] for x in langs})
    lang_obs = {"comparable": _complete(ctx, d - timedelta(days=1)) and _complete(ctx, d), "langs": sorted(langs, key=lambda x: (-x["n"], x["code"])),
                "zero": [{"code": z, **lname(z)} for z in zero], "countries": {}}
    if language_areas.enabled():   # 世界の言語圏の対応表（ADR 0049）
        lv = language_areas.for_view([x["code"] for x in lang_obs["langs"]])
        lang_obs.update(countries={**lang_obs["countries"], **lv["countries"]}, country_roles=lv["roles"], country_why=lv["why"])
    from game_signal_scout.signal import area_input   # 地図・言語ページは登録された本番の取得元すべてから（ADR 0047）
    lang_obs, _gates = area_input.area_obs(ctx, d, ctx.map_sources, lang_obs["countries"], lang_obs["comparable"])
    # 今チェックしておきたい作品: その日、普段と比べて動いた作品（共通の Signal 発見）
    cks = checks(ctx, d)
    # 今日の兆しの作品の列: 動いた作品を先に、残りは人数の多い作品（人数の順には並べない）
    dd = dash_digest(ctx, d)
    mv = _movement(ctx, d)   # Q1・Q2 の分析（集計の見出しにも使う）
    summ = summarize(today, ctx.pages["dashboard"]["focus_share"], mv)
    lead = dash_lead(ctx, dd, summ)
    feat_ids = []
    if lead.get("work") and int(lead["work"][1:]) in ctx.works:   # 作品の列の先頭 = 見出しの作品（文章とピックアップは同じ発見。仕様 §0.2-4）
        feat_ids.append(int(lead["work"][1:]))
    for c in cks:
        if int(c["id"][1:]) in ctx.works and int(c["id"][1:]) not in feat_ids:
            feat_ids.append(int(c["id"][1:]))
    for w, _ in ranked:
        if len(feat_ids) >= 7:
            break
        if w not in feat_ids:
            feat_ids.append(w)
    featured = [ctx.ref(w, n=m.get(w, 0)) for w in feat_ids[:7]]
    # 今日の兆しの作品で、プレイヤーがしたこと・起きたこと（読み取りは直近の発言なので、最新の日だけ。面白さの上位 3 件）
    if lead.get("work") and ctx.pdays and d == ctx.pdays[-1] and (wf := work_finds(ctx).get(int(lead["work"][1:]))) and wf["good"]:
        lead["finds"] = {"good": wf["good"][:3], "window_days": wf["window_days"]}
    if lead.get("work"):   # 「今日の注目」（大カード）も見出しの作品に（一覧にあるときだけ。docs/TODAYS-SIGNAL-PAGES.md §1）
        cks.sort(key=lambda c: 0 if c["id"] == lead["work"] else 1)
    return {"day": d.isoformat(), "label": dlabel(d), "complete": _complete(ctx, d), "obs_status": ctx.gobs.get(d, "none"),
            "dash_digest": {"enabled": bool(dd.get("enabled"))}, "lead": lead, "ui_next": bool(ctx.ui_next), "works_today": len(m), "featured": featured,
            "days": [{k: v for k, v in x.items() if k != "top"} for x in days], "shape": shape, "turnover": turns, "entrants": entrants,
            "top1": t1, "top": top, "checks": cks, "lang_obs": lang_obs, "summary": summ, "movement": mv,
            "display": {k: int(v) for k, v in series.load_pages()["display"].items()}}   # Q1・Q2 の一覧の初めの件数と足す件数（common.js の moreList。#24）


CLS = {"surge": "surge", "emergence": "new", "new_language": "overseas", "continuing": "cont"}
CLS_LABEL = {"surge": {"ja": "急増", "en": "Jump"}, "emergence": {"ja": "初めて話題に", "en": "First time"},
             "new_language": {"ja": "言語圏の広がり", "en": "New language area"}, "continuing": {"ja": "続いている", "en": "Keeps going"}}


def checks(ctx: Ctx, d: date) -> list[dict]:
    """今チェックしておきたい作品: その日、作品自身の普段と比べて動いた作品（共通の Signal 発見と系列。publication/movement.work_changes）。
    並びは変化の種類ごとに、変化が始まった時の新しい順（movement.order。ADR 0010。量の大きさで並べない・順位ではない）。文は分析の事実から日英で組む（LLM なし）。"""
    from game_signal_scout.signal import movement
    out = []
    moved = [(w, x) for w, x in work_changes(ctx, d).items() if x["kind"] in movement.CHANGE and w in ctx.works]   # 作れない日は空（_movement と同じ扱い）
    for w, x in sorted(moved, key=lambda kv: movement.order(*kv)):
        ws, m = ctx.works[w], ctx.meta[w]
        day, nxt = ws.at(d), ws.at(d + timedelta(days=1))
        first = next((y.day for y in ws.days if y.authors >= TOPIC_MIN), None)
        first_n = ws.at(first).authors if first else None
        spread = _unique([lname(lg) for lg, a in sorted((day.langs.items() if day else []), key=lambda kv: (-kv[1].authors, kv[0])) if lg not in NOT_LANGUAGE and a.authors >= TOPIC_MIN])
        out.append({"id": m["id"], "name": m["name"], "cover": m["cover"], **_judge(m), "cls": CLS[x["kind"]], "people": x["n"], "label": CLS_LABEL[x["kind"]],
                    "line": {loc: movement._fact({**x, "name": m["name"]}, loc) for loc in ("ja", "en")},
                    "after": {"ja": f"{nxt.authors}人" if nxt and nxt.observed != "none" else "", "en": f"{nxt.authors} people" if nxt and nxt.observed != "none" else ""},
                    "spread": {"ja": "・".join(x["ja"] for x in spread), "en": ", ".join(x["en"] for x in spread)},
                    "first": {"ja": dlabel(first)["md"], "en": dlabel(first)["md"]} if first else {}, "grow": [first_n, x["n"]],
                    "new_langs": _unique([lname(lg) for lg in x.get("new_langs") or [] if lg not in NOT_LANGUAGE])})
    return out


# ---------------------------------------------------------------- 世界で広がる（公開した日ごと）
def spread(ctx: Ctx, d: date) -> dict:
    """その日、2 つ以上の言語で話題になった作品（言語ごとに 2 人以上）。前日になかった言語にも広がった / 初めて複数の言語 / 前から複数の言語。
    言語は全 Source 共通の観測の集計から、Source ごとに数えた言語圏の集合（Source をまたいで人数を足さない。同じ言語圏は登録の順で最初の Source。
    ADR 0050）。比較の基準: 後から加わった Source は、その日より前に prior_min_days 日以上観測してから入れる。「前日になかった」は前日も観測した
    Source の言語だけ。「初めて」は観測したすべての日の記録で決める。"""
    from game_signal_scout.signal import area_input
    srcs = src_series(ctx)
    pmin = int(series.load_pages()["language_spread"]["prior_min_days"])
    site_first = min((x for x, _, st in ctx.ss.days if st != "none"), default=None)
    obs_days = {src: src_observed(ctx, src) for src, _, _ in srcs}
    first_obs = {src: min(ds, default=None) for src, ds in obs_days.items()}

    def observed(src, x: date) -> bool:
        return x in obs_days[src]   # 確定した日だけ（系列にも確定した日しかない）

    def eligible(src, x: date) -> bool:
        """その日の言語を「この日の広がり」に入れてよいか: サイトの観測の始めから観測している Source か、その日より前に pmin 日以上観測した Source。"""
        if not observed(src, x):
            return False
        f = first_obs.get(src)
        return src is None or f is None or site_first is None or f <= site_first or sum(1 for y in obs_days[src] if y < x) >= pmin

    def langs_at(w: int, x: date, min_n: int, gate) -> dict[str, tuple[int, str]]:
        """言語圏 → （人数、Source）。同じ言語圏は登録の順で最初の Source（人数を足さない）。"""
        out: dict[str, tuple[int, str]] = {}
        for src, prof, works in srcs:
            ws = works.get(w)
            if ws is None or not gate(src, x):
                continue
            day = ws.at(x)
            for lg, a in (day.langs.items() if day else []):
                if lg in NOT_LANGUAGE or a.authors < min_n:
                    continue
                area = area_input._area(prof, lg)[0] if src else lg
                if area not in out:
                    out[area] = (a.authors, src)
        return out

    out = []
    br = ctx.briefs
    labels = {src: prof.get("label") or [src, src] for src, prof, _ in srcs}
    all_days = [x for x, _, _ in ctx.ss.days if x <= d]
    works = list(dict.fromkeys(w for _, _, ws_ in srcs for w in ws_))
    for w in works:
        now_s = langs_at(w, d, TOPIC_MIN, eligible)
        if len(now_s) < 2:
            continue
        now = {lg: n for lg, (n, _) in now_s.items()}
        prev = {lg: n for lg, (n, _) in langs_at(w, d - timedelta(days=1), TOPIC_MIN, observed).items()}
        first: dict[str, str] = {}
        ones: dict[str, str] = {}
        multi_before = False
        for x in all_days:
            ls = langs_at(w, x, 1, observed)
            for lg, (a, _) in ls.items():
                if a >= TOPIC_MIN:
                    first.setdefault(lg, x.isoformat())
                elif x < d:
                    ones.setdefault(lg, x.isoformat())
            if x < d and sum(1 for a, _ in ls.values() if a >= TOPIC_MIN) >= 2:
                multi_before = True
        # 前日になかった言語: その言語を数えた Source が前日も観測していたものだけ（観測していない日と比べない）
        lead_src = srcs[0][0]
        order = lambda lg: (now_s[lg][1] != lead_src, -now[lg])   # noqa: E731 — 最初に登録した Source の言語を先に（Source をまたいで人数で並べない）
        added = sorted((lg for lg in now if lg not in prev and observed(now_s[lg][1], d - timedelta(days=1))), key=order)
        group = "new" if not multi_before else ("grew" if added else "cont")
        b = br.get(w) or {}
        out.append(ctx.ref(w, langs=sorted(now, key=order), n=now, prev=sorted(prev, key=lambda lg: -prev[lg]), first=first, added=added,
                           group=group, prior_ones=sorted(((lg, dd) for lg, dd in ones.items() if lg not in first or first[lg] >= d.isoformat()), key=lambda x: x[1]),
                           air={"status": b.get("status"), "start": _ymd(b.get("start")), "year": b.get("year")},
                           **({"by_src": {lg: sv for lg, (_, sv) in now_s.items()}} if len(srcs) > 1 else {}),
                           **({"src_lang_label": lbl} if (lbl := {lg: labels[sv] for lg, (_, sv) in now_s.items() if sv != lead_src}) else {})))
    # 並び: 最初に登録した Source の言語の人数の合計（Source をまたいで人数を足さない）
    lead = srcs[0][0]
    out.sort(key=lambda x: (-sum(n for lg, n in x["n"].items() if (x.get("by_src") or {}).get(lg, lead) == lead), x["id"]))
    res = {"day": d.isoformat(), "items": out}
    if ctx.ui_next:
        res["lead"] = spread_lead(ctx, d, out)
    return res


def _spread_hero(items: list[dict], d: date) -> dict | None:
    """発見の文章がない日の今日の広がりの作品（規則）: 前日になかった言語にも広がった作品のうち、加わった言語が「このサイトで初めて」の作品を先に、
    次に加わった言語の人数（2 番目以降の Source で数えた言語は後ろ）。"""
    grew = [w for w in items if w.get("group") == "grew" and w.get("added")]
    def rank(w):
        a = w["added"][0]
        return (1 if (w.get("first") or {}).get(a) == d.isoformat() else 0, 0 if (w.get("src_lang_label") or {}).get(a) else (w.get("n") or {}).get(a, 0))
    return sorted(grew, key=lambda w: (tuple(-x for x in rank(w)), w["id"]))[0] if grew else None


def spread_lead(ctx: Ctx, d: date, items: list[dict]) -> dict:
    """世界で広がる作品の先頭の組（ADR 0052）: 今日の兆しの文章・引用と、今日の広がり（大きなカード）の作品を 1 つの発見から作る。
    発見の文章（sd。日英とも検査に合格）があればその作品、なければ規則で選んだ作品と、その作品の観測の事実（画面がこの事実から文を組む）。
    ダッシュボードの見出し・ほかのページの文章を代わりに使わない（ページごとに別の発見。仕様 §2）。"""
    sv = spread_voice(ctx, d, items)
    by_id = {w["id"]: w for w in items}
    if sv and sv.get("ja") and sv.get("en") and sv.get("id") in by_id and by_id[sv["id"]].get("added"):
        return {"kind": "finding", "work": sv["id"], "sents": sv.get("sents") or {}, "cites": {loc: visible_cites(ctx, (sv.get("cites") or {}).get(loc)) for loc in ("ja", "en")},
                "evidence": sv.get("evidence") or [],
                "names": sv.get("names") or []}
    hero = _spread_hero(items, d)
    if not hero:
        return {"kind": "none", "work": None}
    a = hero["added"][0]
    return {"kind": "aggregate", "work": hero["id"], "lang": a, "n": (hero.get("n") or {}).get(a), "prev": hero.get("prev") or [],
            "grew": sum(1 for w in items if w.get("group") == "grew")}


def spread_items_key(items: list[dict], exclude: list[str] | None = None) -> str:
    """世界で広がる作品の今日の兆し（sd）の入力の鍵 = ページに載る作品と言語の一覧と、外す作品（ダッシュボードの発見）の hash（仕様 §2 の保存の鍵）。"""
    return hashlib.sha256(json.dumps([[(w["id"], w.get("added"), w.get("n")) for w in items], sorted(exclude or [])], sort_keys=True).encode()).hexdigest()[:16]


def dashboard_finding_ids(conn, d: date) -> list[str]:
    """その日のダッシュボードの今日の兆し（dd。合格したもの）の発見の作品（"w<ID>"）。世界で広がる作品は別の発見にする（2026-10-16 のユーザーの指示・仕様 §1・§2）。"""
    from game_signal_scout.ops import dashboard_digest
    o = job_repo.latest_artifact(conn, dashboard_digest.JOB, d, passed_only=True)
    conn.rollback()
    return [f"w{w['work_id']}" for w in (((o or {}).get("signal") or {}).get("works") or []) if w.get("work_id")]


def spread_voice(ctx: Ctx, d: date, items: list[dict]) -> dict | None:
    """世界で広がる作品の今日の兆し（ファンの話題から。ops/dashboard_digest.spread_day）。日次処理の段 spread_digest が保存した記録を読むだけ
    （画面の作り直しでは生成しない。DB は読むだけ）。同じ一覧の記録がなければ None（文章のない日の表示）。"""
    from game_signal_scout.ops import dashboard_digest
    exclude = dashboard_finding_ids(ctx.conn, d)
    saved = job_repo.latest_artifact_for_input(ctx.conn, dashboard_digest.SPREAD_JOB, d, spread_items_key(items, exclude))   # いちばん新しい記録（作った時刻で選ぶ。版の名前を解釈しない）
    if not saved:
        # 後から作り直した日（削除への追従などで一覧の人数が少し変わった）: その日の記録のうち、発見の作品がいまもページの
        # 「前日になかった言語にも広がった作品」に同じ加わった言語で載っているもの（なければ文章のない日の表示）
        # 文章の数（加わった言語の人数）がいまのページの数と同じときだけ（数の食い違う文章は出さない）
        grew = {w["id"]: {a: (w.get("n") or {}).get(a) for a in w.get("added") or []} for w in items if w.get("added")}
        for o in job_repo.list_artifacts(ctx.conn, dashboard_digest.SPREAD_JOB, d):
            f = (o or {}).get("finding") or {}
            add = {a["code"]: a.get("people") for a in f.get("added") or []}
            if o.get("passed") and add and f.get("id") in grew and f.get("id") not in exclude and all(grew[f["id"]].get(c) == n for c, n in add.items()):
                saved = o
                break
    ctx.conn.rollback()
    if not saved:
        return None
    t = dashboard_digest.texts(saved) if saved.get("passed") else None
    f = saved.get("finding") or {}
    return {"ja": (t or {}).get("ja"), "en": (t or {}).get("en"), "sents": (t or {}).get("sents") or {}, "cites": (t or {}).get("cites") or {},
            "evidence": (t or {}).get("evidence") or [], "id": f.get("id"), "names": [v for w in f.get("works") or [] for v in w.values() if v]} if t else None


def day_ctx(cfg: dict, d: date) -> Ctx:
    """日次の段（dashboard_digest・spread_digest）が使う、その日までの画面の文脈（全 Source 共通の観測の集計。処理の層のアプリと同じ入力）。"""
    return Ctx(connect(), cfg, d)


def work_changes(ctx: Ctx, d: date) -> dict:
    """作品ごとの普段と比べた変化（publication/movement.work_changes）。作れない日は空（今日の兆しは変化なしとして評価する）。"""
    from game_signal_scout.signal import movement
    try:
        return movement.work_changes(ctx, d)
    except Exception as e:  # noqa: BLE001
        ctx.conn.rollback()
        log.warning("work_changes %s: %s", d, e)
        return {}




def _ymd(o) -> str | None:
    try:
        return date(int(o["y"]), int(o["m"]), int(o["d"])).isoformat() if o and o.get("y") and o.get("m") and o.get("d") else None
    except (TypeError, ValueError):
        return None


import re as _re  # noqa: E402


# ---------------------------------------------------------------- 価値ページ（最新の日）
def src_series(ctx: Ctx) -> list[tuple[str, dict, dict]]:
    """変化の判定のページの入力: 登録の順の Source ごとの系列（Ctx が共通の観測から作ったもの。sources/observations.series_set。ADR 0050）。
    作品は Viewer の作品（作品のページがある単位）だけ。"""
    if getattr(ctx, "_src_series", None) is None:
        ctx._src_series = [(src, prof, {w: ctx.sss[src].works[w] for w in ctx.works if w in ctx.sss[src].works})
                           for src, prof in sorted(ctx.sources.items(), key=lambda x: x[1].get("order", 99))]
    return ctx._src_series


def src_observed(ctx: Ctx, src: str) -> set:
    """その Source が観測をそろえた日。"""
    return {d for d, _, st in ctx.sss[src].days if st != "none"}


def each_series(ctx: Ctx):
    """（Source・登録・作品・系列）を登録の順に。"""
    for src, prof, works in src_series(ctx):
        for w, ws in works.items():
            yield src, prof, w, ws


def _src_tag(ctx: Ctx, src: str | None, prof: dict) -> dict:
    """ページの作品がどの Source の系列で判定されたか（人数はその Source の中の数。Source をまたいで足さない）。
    最初に登録した Source 以外は出典の表記（label）も付ける（画面の作品名の横。数の出どころを取り違えさせない）。"""
    if not src:
        return {}
    return {"src": src, **({"src_label": prof.get("label")} if src != src_series(ctx)[0][0] else {})}


def series_tail(ctx: Ctx, w: int, days: list[date], lang: str | None = None, ws=None) -> list[int]:
    out = []
    ws = ws or ctx.works[w]
    for d in days:
        x = ws.at(d)
        if x is None:
            out.append(0)
        elif lang:
            a = x.langs.get(lang)
            out.append(a.authors if a else 0)
        else:
            out.append(x.authors)
    return out


def obs_string(ctx: Ctx, days: list[date]) -> str:
    return "".join({"complete": "c", "recovered": "r", "partial": "p"}.get(ctx.gobs.get(d), "n") for d in days)


def sort_revived(rev: list[dict]) -> list[dict]:
    """再燃した作品の並び: 再び話題になった日の人数の多い順 → 静かな期間の長い順 → 作品の ID（PAGE_SORT。同じ条件なら毎回同じ順。
    Issue #22: 規則は定義してあったが当てておらず、取得元と作品の辞書の順のままだった）。"""
    rev.sort(key=lambda x: (PAGE_SORT["revival"](x["ev"]), x["id"]))
    return rev


def recent_quiet(watch: list[dict], as_of: date, days: int) -> list[dict]:
    """話題が落ち着いている作品: 最後に話題になった日が直近 days 日の内の作品だけ（古くなった作品は外し、日を追って一覧が伸び続けないようにする。Issue #16）。
    並びは、以前に話題にした人の多い順（再び話題になったときの発見の価値が高い）→ 静かな日の多い順。画面は静かな日数の区分ごとにこの順で並べる。"""
    lo = as_of - timedelta(days=days - 1)
    out = [w for w in watch if date.fromisoformat(w["last"]) >= lo]
    out.sort(key=lambda x: (-x["last_n"], -x["quiet"], x["id"]))
    return out


def pages(ctx: Ctx) -> dict:
    from game_signal_scout import signal_cards as sc
    page_settings, rules, as_of = series.load_pages(), sc.load_rules(), ctx.latest
    od = ctx.ss.observed_days
    win = [d for d in ctx.pdays][-int(page_settings["common"]["series_days"]):]   # 各ページの作品の列の推移の日数（config/pages.toml [common]）
    window = [win[0] + timedelta(days=i) for i in range((as_of - win[0]).days + 1)]
    obs_s = obs_string(ctx, window)
    out = {"as_of": as_of.isoformat(), "label": dlabel(as_of), "days": [d.isoformat() for d in window], "observed": obs_s}
    br = ctx.briefs
    # 再燃: 本番の判定の作品と、話題が落ち着いている作品（最後の「話題」の日のあと、観測した日がすべて 1 人以下）
    th = page_settings["revival"]
    rev, watch = [], []
    # Source ごとの系列に同じ判定を当てる（ADR 0050）。作品は、判定に通った最初の（登録の順の）Source の 1 つだけ（人数を足さない）
    for src, prof, w, ws in each_series(ctx):
        if any(x["id"] == f"w{w}" for x in rev):
            continue
        v = series.judge_revival(ws, th, rules, as_of)
        if v["shown"]:
            rev.append(ctx.ref(w, rs=(br.get(w) or {}).get("status"), ev=v["evidence"], series=series_tail(ctx, w, window, ws=ws), **_src_tag(ctx, src, prof)))
    sort_revived(rev)
    # 話題が落ち着いている作品: その作品を観測しているどの Source でも、最後の「話題」の日のあと静か（ある Source で落ち着いていても、
    # ほかの Source で話題が続いていれば「落ち着いている」とは言わない）。表示する数は、条件を満たした最初の Source のもの
    shown = {x["id"] for x in rev}
    cand: dict[int, dict] = {}
    active: set = set()
    for src, prof, w, ws in each_series(ctx):
        if f"w{w}" in shown:
            continue
        days = series.observed(ws.days)
        last = None
        for x in days:
            if x.authors > th["quiet_max_authors"] and series.enough(x.total, th["active_min_authors"], rules)[0]:
                last = x
        if last is None:
            continue            # この Source では「話題」の日がない（判断しない）
        after = [x for x in days if x.day > last.day]
        quiet = sum(1 for x in after if x.observed == "complete")
        if not after or any(x.authors > th["quiet_max_authors"] for x in after) or quiet == 0:
            active.add(w)       # この Source では、最後の「話題」の日のあとも静かになっていない
            continue
        cand.setdefault(w, ctx.ref(w, rs=(br.get(w) or {}).get("status"), last=last.day.isoformat(), last_n=last.authors, quiet=quiet,
                                   partial_quiet=sum(1 for x in after if x.observed == "partial"), **_src_tag(ctx, src, prof)))
    watch = recent_quiet([v for w, v in cand.items() if w not in active], as_of, int(th["watch_days"]))
    for v in watch:   # 再燃の候補: 静かな期間が再燃の判定の条件（quiet_min_days）に届いた作品。次に話題になれば再燃（judge_revival）になる（Issue #22）
        v["candidate"] = v["quiet"] >= int(th["quiet_min_days"])
    out["revival"] = {"items": rev, "watch": watch}
    out["display"] = {k: int(v) for k, v in page_settings["display"].items()}   # 長い一覧の初めの件数と足す件数（common.js の moreList）
    # 放送後も熱い: 放送を終えた作品を 1 つの一覧に（#26）。作品ごとに、取得元の系列の中でいちばん判定が進んだ結果を状態にする
    # （判定は本番の judge_post_air のまま。閾値は変えない）。話題が続いている作品（hot）を先頭に。これから放送を終える作品は別の一覧（判定ではない）
    th = page_settings["post_air"]
    best: dict[int, tuple] = {}
    soon, sdone = [], set()
    for src, prof, w, ws in each_series(ctx):
        b = br.get(w)
        if not b:
            continue
        v = series.judge_post_air(ws, th, rules, as_of, b, od[0] if od else None)
        st = PA_STATE.get(None if v["shown"] else v["reason"])
        if st and (w not in best or PA_DEPTH[st] > PA_DEPTH[best[w][0]]):
            best[w] = (st, v, src, prof, ws)
        end = series._end_date(b)
        if w not in sdone and b.get("status") in ("airing", "releasing") and end and as_of < end <= as_of + timedelta(days=int(ctx.pages["post_air"]["ending_soon_days"])):
            sdone.add(w)   # 推移はその作品の最初の Source の系列
            soon.append(ctx.ref(w, fmt=b.get("format"), end=end.isoformat(), series=series_tail(ctx, w, window, ws=ws), **_src_tag(ctx, src, prof)))
    ended = []
    for w, (st, v, src, prof, ws) in best.items():
        if st != "hot" and date.fromisoformat(v["evidence"]["end"]) < window[0] - timedelta(days=3):
            continue   # 比べられない古い作品は載せない（話題が続いている作品は、終了が前でも載せる）
        b = br[w]
        ended.append(ctx.ref(w, state=st, ev=v["evidence"], end=v["evidence"]["end"], fmt=b.get("format"), sort=v.get("sort"),
                             series=series_tail(ctx, w, window, ws=ws), **_src_tag(ctx, src, prof)))
    ended.sort(key=lambda x: (PA_ORDER.index(x["state"]), PAGE_SORT["post_air"](x["sort"]) if x["state"] == "hot" else (0,),
                              -date.fromisoformat(x["end"]).toordinal(), x["id"]))
    for x in ended:
        x.pop("sort")
    out["post_air"] = {"ended": ended, "soon": soon, "counts": {s: sum(1 for x in ended if x["state"] == s) for s in PA_ORDER}}
    # 言語圏の広がり
    th = page_settings["language_spread"]
    recorded: dict[int, set] = {}
    from game_signal_scout.signal import movement
    for src, prof, works in src_series(ctx):   # 共通の Signal 発見で「新しい言語圏」と記録した日
        for dd_, m_ in movement.signals_by_day(ctx, src, window).items():
            for w, x in m_.items():
                if (x.get("change") or {}).get("kind") == "new_language":
                    recorded.setdefault(w, set()).add(dd_)
    ls = []
    for src, prof, w, ws in each_series(ctx):
        if any(x["id"] == f"w{w}" for x in ls):
            continue
        v = series.judge_language_spread(ws, th, rules, as_of, recorded.get(w))
        if not v["shown"]:
            continue
        e = v["evidence"]
        langs = sorted({x["code"] for x in e["new_langs"]} | set(e["prior_langs"]))
        ls.append(ctx.ref(w, rs=(br.get(w) or {}).get("status"), ev=e, sort=v["sort"], per={lg: series_tail(ctx, w, window, lg, ws=ws) for lg in langs},
                          **_src_tag(ctx, src, prof)))
    ls.sort(key=lambda it: (PAGE_SORT["language_spread"](it["sort"]), it["id"]))
    out["language_spread"] = {"items": ls, "grid": {"days": int(th["grid_days"]), "before": int(th["grid_before"])}}   # 言語×日の表の窓（langspread.js）
    out["finds"] = finds_page(ctx)
    return out


def _pub_ev(e: dict, en: dict | None = None) -> dict:
    """体験の公開の形: したこと（act）・起きたこと（result）。did は公開しない項目名（FORBIDDEN_KEYS。内部の識別子の名前）なので名前を変える。
    en = 読み取りの英訳（日本語の文 → 英語。#2）。訳があれば act_en・result_en・appeal_en を添える（なければ付けない。画面は日本語の文を出す）。"""
    en = en or {}
    out = {**{k: v for k, v in e.items() if k not in ("did", "happened")}, "act": e.get("did"), "result": e.get("happened")}
    for k, src in (("act_en", e.get("did")), ("result_en", e.get("happened")), ("appeal_en", e.get("appeal"))):
        if src and en.get(src):
            out[k] = en[src]
    return out


def finds_page(ctx: Ctx) -> dict:
    """見つけた面白さ（#2。services/insight の結果）: 作品ごとに、同じ具体的な体験を書いた独立した投稿者の数と、ひとりの体験（そう明記）。
    体験は 面白さの一文（appeal）・その種類（appeal_kind）・したこと（act）・起きたこと（result）で公開する。原文は出さない。
    作品の判断の属性（日本語・開発元・機種）と、カードの絵（場面の画像・横長の帯・表紙）を添える。"""
    from game_signal_scout.repositories import insight as insight_repo
    from game_signal_scout.ops import work_display
    rows = {a: b for a, b in insight_repo.all_insights(ctx.conn).items() if b.get("kind") == "finds" and (b.get("finds") or b.get("singles"))}
    ctx.conn.rollback()
    if not rows:
        return {"items": []}
    meta = work_display.work_meta(ctx.conn, [int(a) for a in rows])
    talk = insight_repo.talk_counts(ctx.conn, list(rows))   # 話題性（直近 7 日の発言の数）: カードの並びに使う
    ctx.conn.rollback()
    items = []
    for a, b in rows.items():
        m = meta.get(int(a))
        if not m:
            continue
        items.append({**{k: m.get(k) for k in ("id", "name", "cover", "banner", "header", "shots")}, **_judge(m), "talk": talk.get(a, 0),
                      "finds": [{**f, **({"appeal_en": (b.get("en") or {})[f["appeal"]]} if f.get("appeal") and (b.get("en") or {}).get(f["appeal"]) else {}),
                                 "examples": [_pub_ev(x, b.get("en")) for x in f.get("examples") or []]} for f in b.get("finds") or []],
                      "singles": [_pub_ev(e, b.get("en")) for e in b.get("singles") or []],
                      "read_people": b.get("read_people"), "experiences": b.get("experiences"), "window_days": b.get("window_days"),
                      "since": (b.get("since") or "")[:10]})   # 作った時刻（generated_at）は公開しない項目
    items.sort(key=lambda x: (-max([f["people"] for f in x["finds"]] or [1]), x["id"]))
    return {"items": items}


def work_finds(ctx: Ctx) -> dict[int, dict]:
    """作品ごとの プレイヤーが見つけた面白さ と 買う前に知っておきたいこと（注目の作品のページと同じ読み取りの結果。作品詳細とダッシュボードの今日の兆しに添える）。
    good = 面白さの一文のある体験（不満を除く。書いた人の多い順）、warn = AI が不満と判断した体験だけ（賛否の体験の注意の印は良い体験にも付くので使わない）。
    1 回の事前計算で 1 度だけ読む。原文は出さない。"""
    if (got := getattr(ctx, "_work_finds", None)) is not None:
        return got
    from game_signal_scout.repositories import insight as insight_repo
    rows = {a: b for a, b in insight_repo.all_insights(ctx.conn).items() if b.get("kind") == "finds" and (b.get("finds") or b.get("singles"))}
    ctx.conn.rollback()
    out: dict[int, dict] = {}
    for a, b in rows.items():
        xs = []
        for f in b.get("finds") or []:
            ev = (f.get("examples") or [{}])[0]
            xs.append({"appeal": f.get("appeal"), "kind": f.get("appeal_kind"), "verdict": f.get("verdict"), "act": ev.get("did"), "result": ev.get("happened"),
                       "people": f.get("people") or 1, "against": (f.get("frustration") or 0) if f.get("verdict") == "fun" else 0, "caution": f.get("caution")})
        for e in b.get("singles") or []:
            xs.append({"appeal": e.get("appeal"), "kind": e.get("appeal_kind"), "verdict": e.get("verdict"), "act": e.get("did"), "result": e.get("happened"),
                       "people": 1, "against": 0, "caution": e.get("caution")})
        xs = [x for x in xs if x["act"] and x["result"]]
        en = b.get("en") or {}
        for x in xs:   # 英訳（#2）。訳のない文には付けない
            for k in ("appeal", "act", "result"):
                if x[k] and en.get(x[k]):
                    x[f"{k}_en"] = en[x[k]]
        good = sorted([x for x in xs if x["appeal"] and x["verdict"] != "frustration"], key=lambda x: -x["people"])
        warn = sorted([x for x in xs if x["verdict"] == "frustration"], key=lambda x: -x["people"])
        if good or warn:
            out[int(a)] = {"good": good, "warn": warn, "read_people": b.get("read_people"), "experiences": b.get("experiences"),
                           "window_days": b.get("window_days"), "since": (b.get("since") or "")[:10]}
    ctx._work_finds = out
    return out


# ---------------------------------------------------------------- 作品を探す
def _work_kinds(ctx: Ctx, w: int, days: list[date]) -> list[str]:
    """作品のその期間の共通の Signal 発見の種類（登録の順の Source。作品の変化を見つけた Source ごと）。
    公開の分類（CLS: 絞り込みと札の名前。search.js の KIND）で返す。内部の種類の名前を画面に渡さない（#64）。"""
    from game_signal_scout.signal import movement
    kinds = []
    for src, prof, works in src_series(ctx):
        if w not in works:
            continue
        for dd_, m_ in movement.signals_by_day(ctx, src, days).items():
            k = CLS.get(((m_.get(w) or {}).get("change") or {}).get("kind"))
            if k and k not in kinds:
                kinds.append(k)
    return kinds


def search(ctx: Ctx, pg: dict) -> dict:
    """作品を探す: 観測している作品の一覧（共通の系列から。話題になった日・人数・言語・変化の種類）と、価値ページに載っている作品。"""
    works = []
    have = set()
    window = [date.fromisoformat(x) for x in pg["days"]]
    for w, ws in ctx.works.items():
        tdays = [x for x in ws.days if x.authors >= TOPIC_MIN]
        if not tdays:
            continue
        have.add(w)
        langs = Counter()
        for x in tdays:
            for lg, a in x.langs.items():
                if lg not in NOT_LANGUAGE:
                    langs[lg] += a.authors
        b = ctx.briefs.get(w) or {}
        works.append({"id": f"w{w}", "name": ctx.meta[w]["name"], "keys": ctx.keys.get(w, []), "cover": ctx.meta[w]["cover"], **_judge(ctx.meta[w]),
                      "fmt": b.get("format"), "season": b.get("season"), "year": b.get("year"), "rs": b.get("status"), "genres": b.get("genres") or [],
                      "kinds": _work_kinds(ctx, w, window), "langs": [[lg, n] for lg, n in sorted(langs.items(), key=lambda kv: (-kv[1], kv[0]))],
                      "first": tdays[0].day.isoformat(), "last": tdays[-1].day.isoformat(), "days": len(tdays), "peak": max(x.authors for x in tdays), "pages": [],
                      "modes": b.get("modes") or []})   # Game: 遊び方（一人（ソロ）で遊べる などのページの絞り込み）
    on = {"language_spread": [x["id"] for x in pg["language_spread"]["items"]],
          "post_air": [x["id"] for x in pg["post_air"]["ended"] + pg["post_air"]["soon"]],
          "revival": [x["id"] for x in pg["revival"]["items"] + pg["revival"]["watch"]]}
    byid = {x["id"]: x for x in works}
    br = ctx.briefs
    for page, ids in on.items():
        for i in ids:
            if i not in byid:          # 日ごとの変化にはまだ出ていないが、ページに載っている作品も探せるようにする
                w = int(i[1:])
                b = br.get(w) or {}
                byid[i] = {"id": i, "name": ctx.meta[w]["name"], "keys": ctx.keys.get(w, []), "cover": ctx.meta[w]["cover"], **_judge(ctx.meta[w]), "fmt": b.get("format"),
                           "season": b.get("season"), "year": b.get("year"), "rs": b.get("status"), "genres": b.get("genres") or [], "kinds": [], "langs": [],
                           "first": None, "last": None, "days": 0, "peak": 0, "pages": [], "page_only": True}
                works.append(byid[i])
            if page not in byid[i]["pages"]:
                byid[i]["pages"].append(page)
    for x in works:
        x.update(_extra_brief(ctx, int(x["id"][1:])))
    return {"days": len(ctx.pdays), "first": ctx.pdays[0].isoformat(), "latest": ctx.latest.isoformat(), "works": works}


# ---------------------------------------------------------------- 作品詳細
def work_quotes(ctx: Ctx, w: int, window: list[date]) -> dict[date, list[dict]]:
    """作品の、日ごとの引用（発言の分類 observation の確かめた引用。共有は出さない）。公開してよい投稿だけ（投稿者・内容のラベル。取得元の quotable）。"""
    rows = foundation_repo.list_confirmed_quotes_of_work(ctx.conn, w, window[0], window[-1])
    ctx.conn.rollback()
    rows = [r for r in rows if not _re.search(r"https?:|\w\.\w+/", r[5])]
    ok: set[tuple[str, str]] = set()
    for src in {r[1] for r in rows}:
        ad = factory.reader_for(src)
        ok |= {(src, i) for i in (ad.quotable(ctx.conn, [r[2] for r in rows if r[1] == src]) if ad else set())}   # 引用は利用条件で allowed と記録された取得元だけ（source_terms。既定は出さない。#3 G2）
    out: dict[date, list[dict]] = {}
    seen: set[tuple[date, str]] = set()
    from game_signal_scout.repositories import post as post_repo
    urls = post_repo.urls_of(ctx.conn, [(r[1], r[2]) for r in rows])   # 引用から原投稿へ（Anime の §8）
    for d, src, uid, kind, lang, quote in rows:
        key = (d, _re.sub(r"\s+", " ", quote).strip().casefold())
        link = factory.permalink(src, uid, urls.get((src, uid)))
        # 引用は原投稿へ辿れるものだけ（Anime の §8・audit_public の QUOTE_URL。Steam のレビューは投稿者の ID を持たないので個別の URL を作れず、引用しない）
        if len(out.get(d, [])) >= int(ctx.pages["work"]["quotes_per_point"]) or (src, uid) not in ok or key in seen or not link:   # 同じ日の同じ文（同じ投稿の別の分類・同じ文の拡散）は 1 つ
            continue
        seen.add(key)
        out.setdefault(d, []).append({"kind": kind, "lang": lang, "quote": quote, "url": link})
    ctx.conn.rollback()
    return out






def history_window(ctx: Ctx) -> list[date]:
    """作品詳細の全期間（観測を始めた日から最新の日まで。#52）。週・月・四半期にまとめた棒・転換点はこの範囲から作る。
    日ごとの棒・要約・言語圏は、このうち直近の config/pages.toml [common] detail_days 日（work_detail）。"""
    od = ctx.ss.observed_days
    start = od[0] if od else ctx.ss.first
    return [start + timedelta(days=i) for i in range((ctx.latest - start).days + 1)]


def periods(days: list[date], vals: list, obs: str, marks: dict[str, list[str]], unit: str) -> list[dict]:
    """日ごとの値を週（最新の日から 7 日ずつ）・月・四半期・年の区切りにまとめる（#52。話題の動きと創作の動きの共通）。
    値（avg）は観測できた日の 1 日平均（延べ sum ÷ 観測できた日数 obs）。1 日も観測できなかった区切りは None（0 で埋めない）。
    len は暦の区切りの日数（週 7・月・四半期・年）、days はそのうち範囲の日数（観測を始める前と最新の日の後は外す。観測を始めた区切りと途中の区切りは days < len）、part は観測できた日のうち一部の時間だけ観測した日の数、marks は区切りの中で変化が見つかった種類。"""
    key = {"week": lambda i, d: (len(days) - 1 - i) // 7, "month": lambda i, d: (d.year, d.month),
           "quarter": lambda i, d: (d.year, (d.month - 1) // 3), "year": lambda i, d: d.year}[unit]
    out: list[tuple] = []
    for i, d in enumerate(days):
        k = key(i, d)
        if not out or out[-1][0] != k:
            out.append((k, {"from": d.isoformat(), "len": _period_len(d, unit), "days": 0, "obs": 0, "part": 0, "sum": 0, "marks": []}))
        b = out[-1][1]
        b["to"], b["days"] = d.isoformat(), b["days"] + 1
        if obs[i] != "n":
            b["obs"], b["part"], b["sum"] = b["obs"] + 1, b["part"] + (obs[i] == "p"), b["sum"] + (vals[i] or 0)
        b["marks"] += [m for m in marks.get(d.isoformat(), []) if m not in b["marks"]]
    return [{**b, "avg": round(b["sum"] / b["obs"], 1) if b["obs"] else None} for _, b in out]


def _period_len(d: date, unit: str) -> int:
    if unit == "week":
        return 7
    if unit == "year":
        return (date(d.year + 1, 1, 1) - date(d.year, 1, 1)).days
    m0 = d.month if unit == "month" else (d.month - 1) // 3 * 3 + 1
    m1 = m0 + (1 if unit == "month" else 3)
    return (date(d.year + (m1 > 12), (m1 - 1) % 12 + 1, 1) - date(d.year, m0, 1)).days


def chart_ranges(ctx: Ctx, days: list[date], vals: list, obs: str, marks: dict[str, list[str]]) -> list[dict]:
    """作品詳細の棒の期間と粒度（#52。config/pages.toml [work] ranges・all_units）。系列が観測を始めた日（最初の観測できた日）から数え、
    その日数を超える期間だけを出し、最後に全期間（日数に応じた粒度）。日ごとの期間は日数だけ（画面が日ごとの系列を切る）、まとめる期間は区切り（periods）を持つ。"""
    s = next((i for i, o in enumerate(obs) if o != "n"), len(obs))
    days, vals, obs = days[s:], vals[s:], obs[s:]
    if not days:
        return []
    wp = ctx.pages["work"]
    unit_all = next((u for n, u in wp["all_units"] if len(days) <= int(n)), "year")
    def span(unit: str, n: int) -> int:   # 月ごとの期間は暦の月にそろえる（1 年 = 今月と前の 11 か月。最初の区切りが数日だけの月にならない）
        if unit != "month":
            return n
        m = days[-1].year * 12 + days[-1].month - 1 - (round(n / 30.44) - 1)
        return min(len(days), (days[-1] - date(m // 12, m % 12 + 1, 1)).days + 1)
    rngs = [(r["key"], r["unit"], span(r["unit"], int(r["days"]))) for r in wp["ranges"] if len(days) > int(r["days"])] + [("all", unit_all, len(days))]
    return [{"key": k, "unit": u, "days": n, "from": days[-n].isoformat(), "to": days[-1].isoformat(),
             **({} if u == "day" else {"items": periods(days[-n:], vals[-n:], obs[-n:], marks, u)})} for k, u, n in rngs]


def creation_series(ctx: Ctx, window: list[date]) -> dict[int, list[dict]]:
    """作品詳細の「創作の動き」の材料（#19）: 創作を観測する Source（config/sources.toml の kind = "creation"・本番の書き先）ごとに、
    作品 → 日ごとの作家の数（項目の creator_refs の異なり数。アップロードした人ではない）。数えない rating（viewer_exclude_ratings）は除く。
    人の声（話題にした人の数）とも、Source どうしでも足さない。観測の状態 o は日ごとに c（そろった）/ p（一部）/ n（観測していない。人数は None）。
    出典の表示名は label（取得元の名前ではなく説明。公開の画面に仕様・取得元を出さない）。
    1 回の問い合わせで全作品（作品ごとに問い合わせない）。"""
    if getattr(ctx, "_creation", None) is not None:
        return ctx._creation
    from game_signal_scout.foundation.normalize import descriptors
    scfg, desc = config.load_toml("sources.toml"), descriptors()
    srcs = [s for s, c in scfg.items() if isinstance(c, dict) and c.get("kind") == "creation" and (desc.get(s) or {}).get("store") == "production"]
    out: dict[int, list[dict]] = {}
    for src in srcs:
        cov = {d: st.get("coverage") for d, st in foundation_repo.list_normalize_details(ctx.conn, src, window[0], window[-1]).items()}
        n: dict[int, dict[date, int]] = {}
        for w, d, k in foundation_repo.count_creators_by_work_day(ctx.conn, src, window[0], window[-1], list(scfg[src].get("viewer_exclude_ratings") or [])):
            n.setdefault(int(w), {})[d] = int(k)
        ctx.conn.rollback()
        for w, byday in n.items():
            if w in ctx.works:
                o = ["c" if cov.get(d) == "complete" else "p" if cov.get(d) == "partial" else "n" for d in window]   # 話題の動きの観測の状態と同じ語
                out.setdefault(w, []).append({"label": scfg[src]["label"], "o": "".join(o), "n": [None if x == "n" else byday.get(d, 0) for x, d in zip(o, window)]})
    ctx._creation = out
    return out




def synopsis(cur: dict) -> dict:
    """あらすじを言語ごとに分ける: 日本語の欄には日本語（原文が日本語ならそれ、ほかはローカル AI の訳）だけ、英語の欄には英語の原文だけ。
    その言語の文がなければ空（画面はその言語では出さない。#60: 日本語のページに英語の原文を出していた）。"""
    if "about" in cur:     # Game: あらすじの代わりにゲーム内容（日本語・英語とも原文。機械翻訳しない）
        return {"synopsis": dict(cur["about"]), "synopsis_mt": False}
    lang, text, ja = cur.get("synopsis_lang"), cur.get("synopsis"), cur.get("synopsis_ja")
    return {"synopsis": {"ja": text if lang == "ja" else ja, "en": text if lang == "en" else None}, "synopsis_mt": bool(ja) and lang != "ja"}


def work_detail(ctx: Ctx, w: int, hist: list[date], pg_on: dict) -> dict:
    """作品詳細（共通の系列・共通の Signal 発見・発言の分類の引用・作品の台帳だけから）。hist = 全期間（history_window）。days = 直近の detail_days 日。
    話題の動きは Source ごとの系列（streams。_stream）: 棒・言語圏・変化の札・要約・転換点を、それぞれ 1 つの Source の数だけで作る（#53: 棒は 1 つの Source、
    札はほかの Source の変化、という食い違いを作らない。Source をまたいで足さない。ADR 0035）。lead = 最初に出す系列（直近 recent_days の観測した日に話題にした人の
    延べがいちばん多い Source。同じなら登録の順）。画面がこの事実から日英の文を組む（LLM は使わない）。"""
    prof = ctx.profile(w)
    cur = dict(prof.get("current") or {})
    if not cur.get("synopsis_ja") and cur.get("synopsis") and cur.get("synopsis_lang") != "ja" and ctx.tstore is not None:
        from game_signal_scout.catalog.translate import source_hash
        cur["synopsis_ja"] = ctx.tstore.ok_text(cur["id"], source_hash(cur["synopsis"]))   # あらすじの日本語訳（translate_missing）
    nd = int(ctx.pages["common"]["detail_days"])
    window = hist[-nd:]
    srcs = sorted((ctx.map_sources.get("sources") or {}).items(), key=lambda x: x[1].get("order", 99))
    by_day = _obs_index(ctx, hist).get(w, {})
    have = [(k, p) for k, p in srcs if any(by_day.get(d, {}).get(k, {}).get("*") for d in hist)] or srcs[:1]
    per = [_stream(ctx, w, hist, k, p) for k, p in have]
    streams = [_stream_all(ctx, w, hist, per)] if per else []   # 出典の切り替えはしない: 作品全体の 1 つの系列（#7 2026-11-09）
    lead = 0
    meta = ctx.meta[w]
    return {**meta, "alt": [t for t in (cur.get("title"), cur.get("title_en")) if t],
            "credit": prof.get("provider_name"), "credit_url": prof.get("site_url"),
            "fmt": cur.get("format"), "season": cur.get("season"), "year": cur.get("year"), "status": cur.get("status"), "episodes": cur.get("episodes"),
            "studios": cur.get("studios") or [], "source": cur.get("source_type"), "genres": cur.get("genres") or [], "start": cur.get("start"), "end": cur.get("end"),
            "links": links.for_display(cur.get("links") or [], ctx.lstore),   # 言語・区別の手がかり・状態つき。リンク切れは除く（publication/links.py）
            **synopsis(cur), "synopsis_kind": cur.get("synopsis_kind"),
            "days": [d.isoformat() for d in window], "streams": streams, "lead": lead,
            "pages": pg_on.get(meta["id"], []), **({"creation": cr} if (cr := [{"label": c["label"], "o": c["o"][-nd:], "n": c["n"][-nd:], "ranges": chart_ranges(ctx, hist, c["n"], c["o"], {})}
                                                                                for c in creation_series(ctx, hist).get(w, [])]) else {}),
            "extra": _extra(ctx, cur.get("id")), **({"finds": f} if (f := work_finds(ctx).get(w)) else {})}


def _obs_index(ctx: Ctx, window: list[date]) -> dict:
    """作品 → 日 → Source → {言語: 人数}（全 Source 共通の観測の集計。ADR 0050）。作品詳細を作るときに 1 回だけ読む。"""
    if getattr(ctx, "_obs_idx", None) is not None:
        return ctx._obs_idx
    from game_signal_scout.signal import area_input
    idx: dict = {}
    srcs = set(ctx.map_sources.get("sources") or {})
    if window and srcs:
        for src, d, wid, lang, n in observation_repo.list_shown_counts(ctx.conn, window[0], window[-1], list(srcs)):
            cw = area_input._to_ctx_work(ctx, wid)
            if cw is not None:
                cur = idx.setdefault(cw, {}).setdefault(d, {}).setdefault(src, {})
                cur[lang] = max(cur.get(lang, 0), n)
    ctx.conn.rollback()
    ctx._obs_idx = idx
    return idx


def _obs_states(ctx: Ctx, window: list[date]) -> dict:
    """Source → 日 → その日の状態（complete / incomplete / not_covered）。作品詳細を作るときに 1 回だけ読む。"""
    if getattr(ctx, "_obs_st", None) is None:
        ctx._obs_st = observation_repo.day_states(ctx.conn, window[0], window[-1]) if window else {}
        ctx.conn.rollback()
    return ctx._obs_st


def _stream(ctx: Ctx, w: int, hist: list[date], src: str, sprof: dict) -> dict:
    """作品詳細の 1 つの Source の系列（#53）。入力は全 Source 共通の観測の集計・共通の確定の状態・共通の Signal 発見だけで、すべてこの Source の数:
    series = 直近 detail_days 日の日ごとの人数（a）と言語ごとの人数（l）、observed = その日の状態（c / p / n。確定していない日は n）、marks = この Source の
    系列で変化を見つけた日、ranges = 棒の期間と粒度（chart_ranges。#52）、summary = 要約の事実（直近の観測した日とその前の同じ日数の延べ人数、最新の日の
    普段との比較、直近に初めて見えた言語圏）、points = 裏づけのある転換点、point_sets = 期間 → その期間の中で選んだ最大 max_points 件の日（base は日ごとの範囲。
    選び方は期間で変えない）。label・persons_days = 出典の札と延べの人数（取得元の名前は公開しない）。"""
    from game_signal_scout.signal import movement
    nd, wp = int(ctx.pages["common"]["detail_days"]), ctx.pages["work"]
    window = hist[-nd:]
    by_day = _obs_index(ctx, hist).get(w, {})
    hser = [{"a": by_day.get(d, {}).get(src, {}).get("*", 0),
             "l": {lg: n for lg, n in by_day.get(d, {}).get(src, {}).items() if lg != "*" and lg not in NOT_LANGUAGE and n}} for d in hist]
    st = _obs_states(ctx, hist).get(src, {})
    hobs = "".join({"complete": "c", "provisional": "p"}.get(st.get(d), "n") for d in hist)   # 途中の値の日は一部（斜線）
    ser, observed = hser[-nd:], hobs[-nd:]
    sig = movement.signals_by_day(ctx, src, hist) if src in ctx.sss else {}
    marks: dict[str, list[str]] = {}
    for d, m in sig.items():
        k = ((m.get(w) or {}).get("change") or {}).get("kind")
        if k and k not in marks.setdefault(d.isoformat(), []):
            marks[d.isoformat()].append(k)
    marks = {k: v for k, v in marks.items() if v}
    ws = ctx.sss[src].works.get(w) if src in ctx.sss else None
    turning, rd = {k: float(v) for k, v in wp["turning"].items()}, int(wp["recent_days"])
    cands = []
    for d in hist if ws else []:
        if not movement.may_turn(ws, w, d, sig, turning):
            continue
        c = movement.classify(ws, w, d, sig)
        if not c:
            continue
        e = movement.entry(ctx, ws, w, d, sig)
        kind = c["kind"] if c["kind"] in turning else ("resurgence" if e and e["entry"] == "again" else None)
        if kind == "resurgence" and "resurgence" not in marks.get(d.isoformat(), []):
            marks.setdefault(d.isoformat(), []).append("resurgence")
        if kind:
            cands.append((turning[kind] * math.log2(1 + (c["ratio"] or 1)) * math.sqrt(c["n"]), d, kind, c, e))
    ranges = chart_ranges(ctx, hist, [x["a"] for x in hser], hobs, marks)
    top = lambda span: sorted((x for x in cands if x[1] >= span[0]), key=lambda x: (-x[0], x[1]))[:int(wp["max_points"])]   # noqa: E731
    sets = {"base": top(window), **{r["key"]: top(hist[-r["days"]:]) for r in ranges if r["unit"] != "day"}}
    chosen = {x[1]: x for xs in sets.values() for x in xs}
    quotes = work_quotes(ctx, w, sorted(chosen)) if chosen else {}
    points = [{"day": d.isoformat(), "kind": kind, "n": c["n"], "base": c["base"], "ratio": c["ratio"], "prev": c["prev"], "langs": c.get("new_langs") or [],
               "quiet": (e or {}).get("quiet") if kind == "resurgence" else None, "quotes": quotes.get(d, [])[:int(wp["quotes_per_point"])]}
              for _, d, kind, c, e in sorted(chosen.values(), key=lambda x: x[1], reverse=True)]
    obs_idx = [i for i in range(len(window)) if observed[i] != "n"]
    span = lambda idx: ({"from": window[idx[0]].isoformat(), "to": window[idx[-1]].isoformat(), "people": sum(ser[i]["a"] for i in idx), "days": len(idx)}  # noqa: E731
                        if idx else None)
    latest = movement.classify(ws, w, window[-1], sig) if ws else None
    first_seen: dict[str, int] = {}
    for i in range(len(window)):
        for lg in ser[i]["l"]:
            first_seen.setdefault(lg, i)
    summary = {"recent": span(obs_idx[-rd:]), "before": span(obs_idx[-2 * rd:-rd]),
               "latest": {"day": window[-1].isoformat(), "observed": observed[-1] != "n", "n": ser[-1]["a"],
                          **({k: latest[k] for k in ("kind", "base", "ratio", "streak")} if latest else {"kind": None}), "langs": (latest or {}).get("new_langs") or []},
               "new_langs": [lg for lg, i in first_seen.items() if i > 0 and i >= len(window) - rd],
               "peak": (lambda i: {"day": window[i].isoformat(), "n": ser[i]["a"]})(max(range(len(ser)), key=lambda i: ser[i]["a"])) if ser else None}
    return {"_hser": hser, "_hobs": hobs, "_cands": cands, "_latest": latest, "_marks_all": dict(marks),
            "label": sprof.get("label") or [src, src], "persons_days": sum(x["a"] for x in hser), "observed": observed, "series": ser,
            "marks": {k: v for k, v in marks.items() if k >= window[0].isoformat()}, "ranges": ranges, "summary": summary, "points": points,
            "point_sets": {k: [x[1].isoformat() for x in sorted(xs, key=lambda x: x[1], reverse=True)] for k, xs in sets.items()}}


def _stream_all(ctx: Ctx, w: int, hist: list[date], per: list[dict]) -> dict:
    """作品詳細の話題の動き（#7 2026-11-09 オーナー: 出典の切り替えをやめ、作品全体の動きを 1 つの系列で）。
    人数 = 出典ごとに数えた投稿者の数の合計（出典の中では同じ人を 1 人に数える。別の出典の同じ人は見分けられないので別に数える。
    作品 × 日の共通の系列 observations.common_series と同じ数え方）。観測の状態 = すべての出典がそろった日 c、一部 p、どれもない日 n。
    変化の印と転換点は、出典ごとの既存の変化の発見から（新しい分析は足さない）。転換点の人数・普段・倍率は、変化を見つけた出典の中の数（scope = source）。
    sources = 出典ごとの延べ人数（グラフの下の出典の説明。選ぶ部品にはしない）。"""
    nd, wp = int(ctx.pages["common"]["detail_days"]), ctx.pages["work"]
    rd = int(wp["recent_days"])
    window = hist[-nd:]
    hser = []
    for i in range(len(hist)):
        langs: dict[str, int] = {}
        for st in per:
            for lg, n in st["_hser"][i]["l"].items():
                langs[lg] = langs.get(lg, 0) + n
        hser.append({"a": sum(st["_hser"][i]["a"] for st in per), "l": langs})
    hobs = "".join("c" if all(st["_hobs"][i] == "c" for st in per) else "n" if all(st["_hobs"][i] == "n" for st in per) else "p" for i in range(len(hist)))
    marks: dict[str, list[str]] = {}
    for st in per:
        for d, ks in (st.get("_marks_all") or st["marks"]).items():
            for k in ks:
                if k not in marks.setdefault(d, []):
                    marks[d].append(k)
    ser, observed = hser[-nd:], hobs[-nd:]
    ranges = chart_ranges(ctx, hist, [x["a"] for x in hser], hobs, marks)
    cands = sorted([x for st in per for x in st["_cands"]], key=lambda x: (-x[0], x[1]))
    best: dict = {}
    for x in cands:            # 同じ日は、いちばん強い変化の 1 つ
        best.setdefault(x[1], x)
    top = lambda span: sorted((x for x in best.values() if x[1] >= span[0]), key=lambda x: (-x[0], x[1]))[:int(wp["max_points"])]   # noqa: E731
    sets = {"base": top(window), **{r["key"]: top(hist[-r["days"]:]) for r in ranges if r["unit"] != "day"}}
    chosen = {x[1]: x for xs in sets.values() for x in xs}
    quotes = work_quotes(ctx, w, sorted(chosen)) if chosen else {}
    points = [{"day": d.isoformat(), "kind": kind, "n": c["n"], "base": c["base"], "ratio": c["ratio"], "prev": c["prev"], "langs": c.get("new_langs") or [], "scope": "source",
               "quiet": (e or {}).get("quiet") if kind == "resurgence" else None, "quotes": quotes.get(d, [])[:int(wp["quotes_per_point"])]}
              for _, d, kind, c, e in sorted(chosen.values(), key=lambda x: x[1], reverse=True)]
    obs_idx = [i for i in range(len(window)) if observed[i] != "n"]
    span = lambda idx: ({"from": window[idx[0]].isoformat(), "to": window[idx[-1]].isoformat(), "people": sum(ser[i]["a"] for i in idx), "days": len(idx)}  # noqa: E731
                        if idx else None)
    lat = [st["_latest"] for st in per if st.get("_latest")]
    strong = max(lat, key=lambda c: (c.get("kind") in ("surge", "emergence", "new_language", "continuing"), c.get("n") or 0), default=None)
    first_seen: dict[str, int] = {}
    for i in range(len(window)):
        for lg in ser[i]["l"]:
            first_seen.setdefault(lg, i)
    summary = {"recent": span(obs_idx[-rd:]), "before": span(obs_idx[-2 * rd:-rd]),
               "latest": {"day": window[-1].isoformat(), "observed": observed[-1] != "n", "n": ser[-1]["a"], "scope": "source",
                          **({k: strong[k] for k in ("kind", "base", "ratio", "streak")} | {"src_n": strong.get("n")} if strong else {"kind": None}),
                          "langs": (strong or {}).get("new_langs") or []},
               "new_langs": [lg for lg, i in first_seen.items() if i > 0 and i >= len(window) - rd],
               "peak": (lambda i: {"day": window[i].isoformat(), "n": ser[i]["a"]})(max(range(len(ser)), key=lambda i: ser[i]["a"])) if ser else None}
    srcs = sorted(({"label": st["label"], "persons_days": st["persons_days"]} for st in per if st["persons_days"]), key=lambda x: -x["persons_days"])
    return {"label": ["すべての出典", "All sources"], "all": True, "persons_days": sum(x["a"] for x in hser), "observed": observed, "series": ser,
            "marks": {k: v for k, v in marks.items() if k >= window[0].isoformat()}, "ranges": ranges, "summary": summary, "points": points,
            "point_sets": {k: [x[1].isoformat() for x in sorted(xs, key=lambda x: x[1], reverse=True)] for k, xs in sets.items()}, "sources": srcs}


def _extra(ctx: Ctx, aid) -> dict | None:
    """追加の作品情報（作品情報の Provider の extra。記録があるときだけ。ないときは None で、画面は段を出さない）。"""
    st = ctx.astore
    if st is None or not aid:
        return None
    rec = st.data.get(str(aid)) or {}
    return catalog_extra.for_display(rec.get("media"), ctx.aid2w, rec.get("fetched_at"))


def _extra_brief(ctx: Ctx, w: int) -> dict:
    """作品を探すで使う追加の作品情報の項目（平均評価・リストに入れた人・タグ）。"""
    st = ctx.astore
    aid = (ctx.profile(w).get("current") or {}).get("id")
    m = st.get(aid) if st is not None and aid else None
    if not m or m.get("adult"):
        return {}
    return {"score": m.get("score"), "pop": m.get("popularity"),
            "tags": [t["name"] for t in sorted(m.get("tags") or [], key=lambda t: -(t.get("rank") or 0)) if (t.get("rank") or 0) >= ctx.pages["work"]["tag_min_rank"]][:int(ctx.pages["work"]["max_tags"])]}


# ---------------------------------------------------------------- 公開の前の検査（応答を返す前）
# 公開データに出してはいけない項目名（ADR 0037 の「返さない」: model・版・内部の閾値・運用の情報・内部の ID・Work の階層・投稿者の識別・本文）
FORBIDDEN_KEYS = {"model", "version", "thresholds", "run_id", "data_hash", "generated_at", "ops", "did", "author", "author_hash", "text", "temp_text",
                  "reasons", "reason", "parent_id", "level", "provider", "synopsis_ja_model", "registry", "window", "item"}
QUOTE_URL = _re.compile(r"^https://[^\s/]+/\S+$")   # 引用のリンクは取得元の Adapter の permalink（https）。取得元の URL の形は知らない


def audit_public(obj, name: str) -> list[str]:
    """応答のデータの検査（返す前。name は応答の名前）。出してはいけない項目名・投稿者の識別子の露出・引用の link の形・作品の link が http(s) か。
    投稿者・投稿の内部の識別子の形は、取得元の契約の internal_id_markers から集める（取得元の名前を知らない）。"""
    bad: list[str] = []
    markers = factory.internal_id_markers()

    def walk(o, f, path):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in FORBIDDEN_KEYS:
                    bad.append(f"{f}: {path}.{k}")
                if k == "quotes" and isinstance(v, list):
                    for q in v:
                        if not QUOTE_URL.match(str(q.get("url", ""))) or set(q) - {"kind", "lang", "quote", "url"}:
                            bad.append(f"{f}: {path}.quotes の形")
                    continue
                if k == "cites" and isinstance(v, (list, dict)):   # 今日の兆しの引用の欄（ADR 0052）: 決まった項目と、投稿への決まった形のリンクだけ
                    for q in (v if isinstance(v, list) else [x for lst in v.values() for x in (lst if isinstance(lst, list) else [lst])]):
                        if not isinstance(q, dict) or set(q) - {"lang", "quote", "meaning", "url", "role"} or (q.get("url") and not QUOTE_URL.match(str(q["url"]))):
                            bad.append(f"{f}: {path}.cites の形")
                    continue
                if k == "post_url":   # 作品の行の出来事・反応の根拠の投稿（#28）: 取得元の Adapter の permalink の形だけ（引用の link と同じ）
                    if v is not None and not QUOTE_URL.match(str(v)):
                        bad.append(f"{f}: {path}.post_url の形")
                    continue
                if k == "links" and isinstance(v, list) and any(not str(x.get("url", "")).startswith(("https://", "http://")) for x in v if isinstance(x, dict)):
                    bad.append(f"{f}: {path}.links が http(s) でない")
                walk(v, f, f"{path}.{k}")
        elif isinstance(o, list):
            for x in o:
                walk(x, f, path)
        elif isinstance(o, str) and any(m in o for m in markers):
            bad.append(f"{f}: {path} に投稿者・投稿の内部の識別子")
    walk(obj, name, "")
    return bad
