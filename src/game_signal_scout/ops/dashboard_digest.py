"""今日の兆し（Anime の ops/dashboard_digest.py を流用し、論点の種類と LLM への指示を Game の声に作り替えた）: ダッシュボード（dd）と世界で広がる作品（sd）。その日の観測から、読者に伝える価値のある発見を選び、プレイヤーが何を語っているかを伝える。

仕様の正本は docs/TODAYS-SIGNAL-PAGES.md（§0・§1・§2）と ADR 0044〜0046・0052。2 つのページは同じ仕組みで、別の発見を伝える。

発見を確定してから文章にする（文章から始めない）:
- 段 1 声（規則）: 作品ごとに、その日のプレイヤー本人の投稿の本文（設定 voice_sources の取得元が保存している本文。ADR 0042。宣伝・ニュースの共有・URL のもの、削除済み、
  !no-unauthenticated の投稿者、情報の発信の投稿者・同じ本文、成人向けの印、取得元の Adapter が公開してよいと言わない投稿〔quotable: 投稿者・内容のラベルなど〕は除く）。1 つの声 = 1 人。
- 段 2 論点（LLM）: 作品ごとに具体的な論点を取り出させる。各論点に、語っている声の ID と原文の抜粋。
- 段 3 確かめ（規則）: 抜粋が原文の一字一句で、文として完結しているか・独立した人数（2 人以上）・意見の分かれ方（両側の人数）・評価の分類でないか。
- 段 4 発見の確定と評価（規則）: 発見の記録（作品・論点・根拠・言語）と評価（finding_assess: 作品の普段と比べた変化〔全 Source 共通の基盤〕・
  裏付け・どこまで言えるか・段階）。段階の順に、論点が根拠で支えられているか（LLM）を確かめて 1 つ選ぶ。選べない日は書かない（no_finding）。
- 段 5 文章: LLM は見出しと論点の言い換え・引用の訳だけ。人数・言語・作品の変化の文は記録から規則で組む。原文は文章に混ぜず、引用（cites）として分ける。
- 段 6 検査（規則）: 記録・原文との照合（数・話数・名前は原文にあるか・訳されていない言葉・規模の書き方・引用）。日英とも通ったものだけを保存・公開する。
- 保存: job_artifact（job = "dashboard_digest" / "spread_digest"）。画面は保存した記録を読むだけ。
"""
from __future__ import annotations

import json
import re
from datetime import date
from typing import Protocol

from game_signal_scout.languages import NAMES, is_language
from game_signal_scout.ops.digest_checks import LEAD_MAX, classify, cite_pool, count_numbers, feedback_for, validate
from game_signal_scout.ops.digest_verbatim import (EXCERPT_MIN_CONTENT, content_length, max_excerpt_length,
                                                    strip_brackets, verbatim_span)
from game_signal_scout.repositories import foundation as foundation_repo, source_item, work as work_repo


def _name(c: dict, loc: str) -> str:
    return (c.get("display_name") or {}).get(loc) or c.get("name") or c["key"]


VERSION = "dd-game-2026-11-08"   # 生成の規則の版（Game: ゲームの話題の種類・見出しの上限 70 字。2026-11-08）（保存した記録の鍵。名前は記録の出どころなので変えない。規則を次に変えるときは、決めた日付の名前にする。CONTRIBUTING.md）。決まりは docs/TODAYS-SIGNAL-PAGES.md と ADR 0044〜0046・0052・0054
JOB = "dashboard_digest"
KINDS_NEWS = ("none", "share")      # 宣伝・ニュースの共有（プレイヤー本人の声ではない）
URL = re.compile(r"https?://|www\.|\.(com|be|jp|tv|app|moe|me|net|io|tw)/|youtu", re.I)
MIN_TEXT, MAX_TEXT = 15, 500        # 声として読む本文の長さ（短すぎるものは話題が読めない）
MAX_VOICES, MAX_CARDS = 24, 12      # 1 作品の声の上限・1 日に話題を取り出す作品の上限（プレイヤーの声の多い順。件数に比例して伸びないように）
MAX_CONTEXT = 5                     # 出来事の文脈として渡すニュースの見出しの上限（根拠・人数には使わない）
# 論点の種類。generic = 作画が良い・声優が良いのような評価の分類だけ（発見にしない）
KINDS = ("update", "statement", "comparison", "gameplay", "performance", "debate", "behavior", "content", "price", "event", "generic")   # Game の論点の種類（Anime から作り替え）
MIN_TOPIC_PEOPLE = 2                # 話題として扱う独立した人数（1 人の感想を傾向にしない）
MIN_EXCERPT_VOICES = 2              # 論点の根拠の抜粋を出した別々の人の数（LLM が別の話を 1 つの論点にまとめても、2 人の原文がなければ使わない）
VAGUE = re.compile(r"^(特定の|作品(への|の)?(感想|反応|評価)$)|^(感想|反応|評価|視聴)$|特定の作品|属性への反応")


# ---------------------------------------------------------------- 段 1 声（規則）
def voice_sources(cfg: dict) -> list[str]:
    """声の本文を読む取得元（config/daily.toml [dashboard_digest] voice_sources。本文を保存する Source だけ。Source ごとに別々に数え、足さない。ADR 0035・0043 §7・0054）。"""
    return list((cfg.get("dashboard_digest") or {}).get("voice_sources") or [])


def digest_languages() -> frozenset[str]:
    """「新しい言語」の発見と文に使う言語圏（config/daily.toml [dashboard_digest] languages。2026-10-27 のユーザーの決定: 数を仕様として固定せず、
    取得できている言語と分析の品質で決める）。名前の表（languages.NAMES）にない値・欠けた設定は読み込みで失敗させる。"""
    from game_signal_scout.config import load_daily_config
    from game_signal_scout.languages import NAMES
    ls = (load_daily_config().get("dashboard_digest") or {}).get("languages")
    if not ls:
        raise ValueError("config/daily.toml [dashboard_digest] languages がない")
    if bad := [x for x in ls if x not in NAMES]:
        raise ValueError(f"config/daily.toml [dashboard_digest] languages に名前の表にない言語: {bad}")
    return frozenset(ls)


def info_posts(conn, source: str, uris: list[str]) -> set[str]:
    """全 Source 共通の品質判定（ADR 0051）で、情報の発信の投稿者（まとめ・同じ文の宣伝。config/foundation_rules.toml）の投稿。
    仕様 §0.3「宣伝・ニュースの共有はプレイヤーの声として数えない」を、地図・人数と同じ判定の結果でそろえる。"""
    if not uris:
        return set()
    from game_signal_scout.foundation.signals import info_roles
    return foundation_repo.list_utterances_with_actor_role(conn, source, info_roles(), uris)


def _work_ids(conn, card: dict) -> list[int]:
    if card.get("work_id"):
        return [int(card["work_id"])]
    return work_repo.list_work_ids_by_keys(conn, list(card.get("keys") or [card.get("key")]))


def fan_voices(conn, source: str, day: date, card: dict, quotable=None) -> list[dict]:
    """その日のその作品のプレイヤー本人の声（1 人 1 つ。いちばん長い本文）。共通層の発言（utterance・utterance_work）と原文の表の本文（ADR 0042・0054）。参照（uri）を残す。
    公開してよい投稿（投稿者・内容のラベル。取得元の Adapter の quotable）だけを声・引用にする（ADR 0052）。"""
    rows = foundation_repo.list_longest_voice_per_actor(conn, source, day, _work_ids(conn, card))
    return voices_from_rows(conn, source, [(r[1], r[2], r[3], r[4]) for r in rows], quotable)


def voices_from_rows(conn, source: str, rows: list[tuple], quotable=None) -> list[dict]:
    """読んだ行（分類・投稿の ID・言語・本文）から声を作る（dd と 4 ページの共通の規則）: 宣伝・ニュースの共有・URL・短い本文・情報の発信の投稿者・
    同じ本文の重なりを除き、公開してよい投稿（取得元の quotable）だけを 1 人 1 つ、MAX_VOICES まで。"""
    from game_signal_scout.sources import factory
    info = info_posts(conn, source, [r[1] for r in rows])
    cand, seen = [], set()
    for kind, uri, lang, text in sorted(rows, key=lambda r: (-len(r[3]), r[1])):
        # 空白はつめるが改行は残す（抜粋の始まりを行の切れ目で決めるため。#62: 改行をつぶすと日付の行の切れ端から引用していた）
        t = re.sub(r"[^\S\n]+", " ", re.sub(r"\s*\n\s*", "\n", text)).strip()
        if kind in KINDS_NEWS or URL.search(t) or len(t) < MIN_TEXT or uri in info:
            continue
        if t in seen:          # 別の人が同じ本文を出した（同じ文の拡散）は 1 つの声（共通の集計と同じ考え）
            continue
        seen.add(t)
        cand.append((uri, lang, t))
    cand = cand[:MAX_VOICES * 2]
    ad = factory.reader_for(source)
    ok = (quotable or (lambda uris: ad.quotable(conn, uris) if ad else set(uris)))([u for u, _, _ in cand])   # Game: 取得元の部品がなければ、公開の発言はすべて引用してよい
    out = []
    for uri, lang, t in cand:
        if uri in ok:
            out.append({"id": f"V{len(out) + 1}", "lang": lang, "text": t[:MAX_TEXT], "uri": uri, "source": source})
        if len(out) >= MAX_VOICES:
            break
    return out


def day_works(conn, source: str, day: date, limit: int = MAX_CARDS) -> list[dict]:
    """その日にプレイヤー本人の声（本文があり、宣伝・ニュースの共有・URL でない投稿）の多い作品（カードの有無を問わない。仕様 §1「全作品から」）。
    返すのは作品ごとの {work_id, keys, voices（その日の声の人数）}。人数は作品全体の人数ではなく、本文のある声の人数。"""
    # 情報の発信の投稿者（まとめ・同じ文の宣伝。全 Source 共通の品質判定 ADR 0051）の投稿は声に数えない（仕様 §0.3）
    from game_signal_scout.foundation.signals import info_roles
    exclude = info_roles()
    rows = [(w, n) for w, n in foundation_repo.count_voice_actors_by_work(conn, source, day, list(KINDS_NEWS), MIN_TEXT, URL.pattern, exclude) if n]
    keys = work_repo.list_keys_by_work(conn, [w for w, _ in rows])
    out = [{"work_id": w, "keys": keys.get(w, []), "voices": n} for w, n in rows]
    return sorted(out, key=lambda x: (-x["voices"], x["work_id"]))[:limit]


def context_lines(conn, source: str, day: date, keys: list[str]) -> list[str]:
    """その日のその作品の出来事の文脈: ニュース・宣伝の共有の見出し（URL を除いた先頭 120 字。同じものは 1 つ）。
    LLM が「何が起きたか」を取り違えないための材料で、根拠・人数・引用には使わない。"""
    rows = foundation_repo.list_news_texts(conn, source, day, work_repo.list_work_ids_by_keys(conn, list(keys)), list(KINDS_NEWS), URL.pattern)
    out = []
    for t in rows:
        x = re.sub(r"\s+", " ", re.sub(r"(https?://|www\.)\S+|\S+\.(com|jp|net|me|moe|tv|io|app)/\S*|#\S+", " ", t)).strip()[:120]
        if len(x) >= 20 and not any(x[:40] == y[:40] for y in out):
            out.append(x)
        if len(out) >= MAX_CONTEXT:
            break
    return out


# ---------------------------------------------------------------- 段 2 話題（LLM）
TOPICS_SYSTEM = """あなたはゲームのプレイヤーの投稿・レビューを読む分析者です。読者は仕事で自由な時間が少なく、週末に遊ぶゲームを選んでいます。
あるゲームについて、その日のプレイヤーの投稿・レビュー（voices。1 つが 1 人）と、同じ日のニュース・告知の見出し（context）が渡されます。
読者が「いまこのゲームでこんなことが起きているのか」「遊ぶ・買う前に知っておきたい」と分かる、具体的な論点を最大 4 つ取り出してください。
- 論点は具体的に書く: 何についての話か（更新・パッチの中身・遊びの仕組み・難しさ・動作や不具合・ボリューム・価格や課金・運営や開発者の発言・前作や他のゲームとの比較・
  プレイヤーの行動）と、プレイヤーがそれについて何を言っているか。
  ×「面白い」「グラフィックがきれい」「神ゲー」「クソゲー」のような、どのゲームにも言える評価の分類で済ませない（そういう話題しかなければ kind を generic にする）。
- kind: update（更新・パッチ・シーズンへの反応）/ statement（開発者・運営の発言や方針への反応）/ comparison（前作・前の版・他のゲームとの比較）/
  gameplay（遊びの仕組み・難しさ・特定の場面や要素）/ performance（動作の重さ・不具合・落ちる・つながらない）/ debate（同じ点について意見が分かれている）/
  behavior（遊び始めた・やめた・返金した・人に勧めた・仲間と遊び始めたなどの行動）/ content（ボリューム・やり込み・遊べる時間）/ price（価格・課金・セール）/
  event（発売・アップデートの配信・大会・セールなどの出来事への反応）/ generic（評価の分類だけ）。
- 投稿ごとに細かい点が違っていても、同じ対象について語っていれば 1 つの論点にまとめる（例: 更新のあとに落ちる・重くなった・設定が消えたとそれぞれ語る 3 人は
  「更新のあとの動作の問題」という 1 つの論点。細かい点の違いは about_ja の中で「〜や〜」と書き分ける）。1 人しか語っていない論点は最後に回す。
  ただし、別の対象（例: 戦闘の難しさと、課金の仕組み）を 1 つの論点にまとめない。1 つの論点には 1 つの対象だけ。
- context は出来事を理解するためだけに使う。論点の根拠・人数にしない（voices に書かれていないことを論点にしない）。
- 各論点に、それを語っている voices の id をすべて入れる。
- debate（意見が分かれている）にしてよいのは、voices の中に、同じ点について違う意見の人が実際にいるときだけ。そのときは sides に両側の id と、両側それぞれの抜粋を入れる
  （sides: {"for": ["V1"], "against": ["V4"]}）。全員が同じ方向なら debate にしない（例: 不満の声ばかりなら、何が不満と言っているかを具体的に書く）。
- 各論点に、根拠の抜粋を 1〜3 つ。抜粋は voices の text の一部を一字も変えずに写す（40 字以内。訳さない・つなげない・省略記号を足さない）。
- stance: positive / negative / mixed / neutral。
- about_ja は日本語、about_en は英語で、論点を 1 文で（40 字程度）。宣伝・ニュースの転載・遊んだ記録だけの投稿は根拠にしない。
出力は JSON だけ: {"topics": [{"about_ja": "…", "about_en": "…", "kind": "…", "stance": "…", "voice_ids": ["V1", "V3"], "sides": {"for": [], "against": []}, "excerpts": [{"voice_id": "V1", "text": "…"}]}]}"""


class DayReader(Protocol):
    """今日の兆しの 2 ページ（ダッシュボード・世界で広がる作品）が読む材料の境界（#46 D10）。本番は DbDayReader（DB）。
    試験は同じ形の偽物を渡し、本番と同じ段 1〜6（候補・声・話題・確かめ・材料・文章）を通す（DB の有無で処理を分けない）。"""
    def sources(self, cfg: dict) -> list[str]: ...
    def candidates(self, source: str, day: date, changes: dict | None) -> list[dict]: ...
    def voices(self, source: str, day: date, card: dict) -> list[dict]: ...
    def context(self, source: str, day: date, keys: list[str]) -> list[str]: ...
    def item_texts(self, source: str, uris: list[str]) -> list[tuple]: ...


class DbDayReader:
    """DayReader の本番の実装（データベースを読むだけ。読み終えたら取引を閉じる）。"""
    def __init__(self, conn):
        self.conn = conn

    def sources(self, cfg: dict) -> list[str]:
        return voice_sources(cfg)

    def candidates(self, source, day, changes):
        try:
            return [_work_card(self.conn, w) for w in _candidate_works(self.conn, source, day, changes)]
        finally:
            self.conn.rollback()

    def voices(self, source, day, card):
        try:
            return fan_voices(self.conn, source, day, card)
        finally:
            self.conn.rollback()

    def context(self, source, day, keys):
        try:
            return context_lines(self.conn, source, day, keys)
        finally:
            self.conn.rollback()

    def item_texts(self, source, uris):
        try:
            return source_item.list_item_texts(self.conn, source, uris)
        finally:
            self.conn.rollback()


def _chat(model: str, system: str, user: str, predict: int, seed: int = 42, temperature: float = 0) -> dict:
    """LLM の 1 回の呼び出し（推論エンジンは llm.py の境界の向こう。待ち時間・文脈の長さは config/daily.toml [dashboard_digest]）。
    出力の上限 predict・seed・やり直しの温度は、指示文と組で決まる業務の定数（呼ぶ側に書く）。"""
    from game_signal_scout import llm
    from game_signal_scout.config import load_daily_config
    dc = load_daily_config()["dashboard_digest"]
    return llm.chat(model, system, user, format="json", think=False, options={"temperature": temperature, "seed": seed, "num_ctx": int(dc["num_ctx"]), "num_predict": predict},
                    timeout=dc["timeout_seconds"]).json()


def ask_topics(model: str, work: str, voices: list[dict], context: list[str] | None = None) -> dict:
    vs = [{"id": v["id"], "lang": v["lang"], "text": v["text"]} for v in voices]
    return _chat(model, TOPICS_SYSTEM, json.dumps({"work": work, "context": context or [], "voices": vs}, ensure_ascii=False), 1600)


# ---------------------------------------------------------------- 段 3 確かめ（規則）
def verify_topics(raw: dict, voices: list[dict]) -> list[dict]:
    """LLM の論点を原文で確かめる。残すのは: 声の ID が実在・抜粋がその声の原文の一字一句の部分・独立した人数が 2 人以上・名前に中身がある・
    評価の分類だけ（kind = generic）でない論点。"""
    by = {v["id"]: v for v in voices}
    out = []
    for t in (raw or {}).get("topics") or []:
        if not isinstance(t, dict):
            continue
        ids = [i for i in dict.fromkeys(t.get("voice_ids") or []) if i in by]
        ex = []
        for e in t.get("excerpts") or []:
            if not (isinstance(e, dict) and e.get("voice_id") in ids and e.get("text")):
                continue
            v = verbatim_span(str(e["text"]), by[e["voice_id"]]["text"])
            # 中身は LLM の選んだ部分で数える（文の始まり・終わりまで伸ばした分で中身のない抜粋を通さない）
            if v and min(content_length(v), content_length(str(e["text"]))) >= EXCERPT_MIN_CONTENT and strip_brackets(v) not in {x["text"] for x in ex}:
                # 抜粋の中の「」は『』にそろえる（文章の引用の「」と区別するため。表記だけの違いで、語は一字も変えない）
                ex.append({"text": strip_brackets(v), "lang": by[e["voice_id"]]["lang"], "voice_id": e["voice_id"], "uri": by[e["voice_id"]].get("uri"),
                           "source": by[e["voice_id"]].get("source")})
        about = strip_brackets(str(t.get("about_ja") or "").strip())
        kind = t.get("kind") if t.get("kind") in KINDS else "generic"
        stance = t.get("stance") if t.get("stance") in ("positive", "negative", "mixed", "neutral") else "neutral"
        # 意見が分かれている（debate・mixed）は、両側に声があり、両側の抜粋が原文で確かめられたときだけ認める（同じ方向の声ばかりの「議論」は評価の分類）
        sides = t.get("sides") if isinstance(t.get("sides"), dict) else {}
        pro = [i for i in sides.get("for") or [] if i in ids]
        con = [i for i in sides.get("against") or [] if i in ids]
        two_sides = bool(pro and con and any(x["voice_id"] in pro for x in ex) and any(x["voice_id"] in con for x in ex))
        if kind == "debate" and not two_sides:
            kind = "generic"
        if stance == "mixed" and not two_sides:
            stance = "neutral"
        reasons = ([] if len(ids) >= MIN_TOPIC_PEOPLE else ["one_person"]) + ([] if ex else ["no_verbatim_excerpt"]) + \
                  (["excerpts_from_one_person"] if ex and len({x["voice_id"] for x in ex}) < MIN_EXCERPT_VOICES else []) + \
                  (["vague_topic"] if not about or VAGUE.search(about) else []) + (["generic_evaluation"] if kind == "generic" else [])
        if two_sides:   # 意見の分かれ方: 両側の独立した人数と抜粋（片側だけを見出しにしない。ADR 0052）
            for x in ex:
                x["side"] = "for" if x["voice_id"] in pro else ("against" if x["voice_id"] in con else None)
        out.append({"about_ja": about, "about_en": str(t.get("about_en") or "").strip(), "kind": kind, "stance": stance,
                    "sides": {"for": len(pro), "against": len(con)} if two_sides else None,
                    "people": len(ids), "voice_ids": ids, "excerpts": ex, "langs": sorted({by[i]["lang"] for i in ids if by[i]["lang"]}),
                    "evidence": [by[i]["uri"] for i in ids], "ok": not reasons, "rejected": reasons})
    return out


# ---------------------------------------------------------------- 段 4 発見の確定（規則）
def _lang_names(codes, loc: str) -> list[str]:
    k = 0 if loc == "ja" else 1
    return [NAMES[c][k] for c in codes if c in NAMES]


def _sub(t: dict | None) -> dict | None:
    return ({"topic": {"ja": t["about_ja"], "en": t["about_en"]}, "kind": t.get("kind"), "stance": t["stance"], "people_on_topic": t["people"],
             "excerpts": t["excerpts"][:1], "evidence": t["evidence"], "languages": t["langs"]} if t else None)


def _pick(topics: list[dict], prefer=None) -> tuple[dict | None, dict | None, dict | None]:
    """主な論点・違う方向の声・ほかの論点。主な論点は、prefer を満たす論点を先に、次に人数の多い順・論点の種類の順（ADR 0052: 議論であることを
    上乗せしない。意見が分かれていることは主な論点の両側として記録し、書き方で示す）。"""
    from game_signal_scout.ops.finding_assess import KIND_ORDER
    ok = [t for t in topics if t["ok"]]
    if not ok:
        return None, None, None
    key = lambda t: (-int(bool(prefer and prefer(t))), -t["people"], KIND_ORDER.get(t["kind"], 3), t["about_ja"])
    main = sorted(ok, key=key)[0]
    rest = [t for t in sorted(ok, key=key) if t is not main and not set(t["voice_ids"]) <= set(main["voice_ids"])]
    # 違う方向の声（「一方で」）は、肯定と否定の組み合わせだけ。中立・分かれている論点は「ほかの論点」（「また」）にする
    contrast = None if main.get("sides") else next((t for t in rest if {t["stance"], main["stance"]} == {"positive", "negative"}), None)
    also = None if contrast else (rest[0] if rest else None)
    return main, contrast, also


def build_finding(card: dict, topics: list[dict]) -> dict | None:
    """1 作品の発見の記録（docs/TODAYS-SIGNAL-PAGES.md §1）。具体的な論点（評価の分類でない・2 人以上・原文の抜粋つき）がなければ None。
    card はその作品（カードがあればカード）。作品の変化・評価・選定は finding_assess（全 Source 共通の基盤の分析。ADR 0052）。"""
    main, contrast, also = _pick(topics)
    if not main:
        return None
    langs = sorted(set(main["langs"]) | set(contrast["langs"] if contrast else []))
    why = (["contrast"] if (main.get("sides") or contrast) else []) + (["abroad"] if set(langs) - {"ja"} else [])
    people_any = len(set(main["voice_ids"]) | set(contrast["voice_ids"] if contrast else []))
    return {"works": [{"ja": _name(card, "ja"), "en": _name(card, "en")}], "key": card.get("key"), "work_id": card.get("work_id"),
            "languages": langs, "topic": {"ja": main["about_ja"], "en": main["about_en"]}, "kind": main["kind"], "stance": main["stance"],
            "sides": main.get("sides"), "people_on_topic": main["people"], "excerpts": main["excerpts"][:3], "evidence": main["evidence"],
            "contrast": _sub(contrast), "also": _sub(also), "topic_languages": main["langs"],
            "context": card.get("context") or [], "why": why or ["shared"],
            "page_reason": "dashboard: the most worthwhile finding across all titles, languages and kinds of change",
            "limits": ["one_day_observation"] + (["few_people"] if people_any < 5 else []), "people_any": people_any}


SUPPORT_SYSTEM = """あなたはゲームプレイヤーの反応を観測するサイトの検証担当です。論点（topic）と、その根拠として選ばれたプレイヤーの投稿の抜粋（excerpts）が渡されます。
抜粋が、論点そのものについて書いているかだけを判定してください。論点の言葉が抜粋の内容と合っていなければ支えていません
（例: 論点が「プレイヤーアートの制作」なのに、抜粋が「このキャラが好き」「あのキャラより好き」という好みだけなら支えていない）。
抜粋が論点の一部の側面だけでも、論点についての具体的な発言なら支えている。推測で補わない。
抜粋がプレイヤー本人の反応・意見・行動ではなく、宣伝・告知・ニュースの見出し・制作物の紹介だけなら支えていない（プレイヤーの声を伝える場所のため）。
出力は JSON だけ: {"supports": true または false, "reason": "日本語で 40 字以内"}"""


def check_support(model: str, f: dict, llm=None) -> dict:
    """発見の論点が、根拠の抜粋で支えられているか（2026-10-14: 10/13 に「キャラクターのプレイヤーアート制作」という論点が、
    好みの声（「Choso my sweet boi」「虎杖の方が野薔薇より好き」）だけで最上位に選ばれた）。"""
    req = {"topic": f["topic"]["ja"], "topic_en": f["topic"]["en"], "excerpts": [{"text": x["text"], "lang": x["lang"]} for x in f["excerpts"]]}
    r = (llm or (lambda q: _chat(model, SUPPORT_SYSTEM, json.dumps(q, ensure_ascii=False), 120)))(req)
    return {"supports": bool((r or {}).get("supports")), "reason": str((r or {}).get("reason") or "")[:80]}


def judge_supported(findings: list[dict], model: str, llm=None, log=print, tries: int = 3) -> tuple[dict | None, list[dict]]:
    """評価の段階の順（finding_assess.order_key。ADR 0052）に、論点が根拠で支えられているかを確かめ、最初に支えられた発見を選ぶ（上位 tries 件まで。
    どれも支えられなければ None: 誤った発見を出すより、文章を出さない）。確かめられなかったとき（LLM の失敗）は、その候補を飛ばす。"""
    from game_signal_scout.ops import finding_assess
    rejected = []
    for f in [f for f in findings if f and (f.get("people_on_topic") or 0) < MIN_TOPIC_PEOPLE]:   # 論点を書いた人が 2 人未満は選ばない（サイトの「2 人以上」）
        rejected.append({"work": f["works"][0]["ja"], "topic": f["topic"]["ja"], "tier": f["assessment"]["tier"], "supports": False, "reason": "fewer_than_two_on_topic"})
    for f in [f for f in findings if f and not finding_assess.eligible(f)]:   # 段階の外（ダッシュボード: 変化がなく 2 人・1 つの言語）。記録に残す
        rejected.append({"work": f["works"][0]["ja"], "topic": f["topic"]["ja"], "tier": f["assessment"]["tier"], "supports": None, "reason": "below_tier"})
    for f in sorted([f for f in findings if f and (f.get("people_on_topic") or 0) >= MIN_TOPIC_PEOPLE and finding_assess.eligible(f)], key=finding_assess.order_key)[:tries]:
        try:
            v = check_support(model, f, llm)
        except Exception as ex:  # noqa: BLE001
            v = {"supports": False, "reason": f"llm_error:{type(ex).__name__}"}
        if v["supports"]:
            return {**f, "support": v, "selected_because": finding_assess.explain(f)}, rejected
        rejected.append({"work": f["works"][0]["ja"], "topic": f["topic"]["ja"], "tier": f["assessment"]["tier"], **v})
        log(f"dashboard_digest: 論点が根拠で支えられない → 次の候補: {f['works'][0]['ja']} / {f['topic']['ja']}（{v['reason']}）")
    return None, rejected


# ---------------------------------------------------------------- 段 4.5 文章の材料（発見は変えない）
PICK_SYSTEM = """次の投稿（同じ言語の、同じ作品のプレイヤーの投稿）から、指定した論点について書いている部分を 1 つ、一字一句そのまま抜き出してください。
その論点の具体的な中身（何についての話か・何を言っているか）が分かる部分を選ぶ（「なんで変えた」のような感想だけの短い部分は選ばない。中身 8 字以上）。
1 つの文として読める部分を選ぶ（文の途中で切らない）。日本語などは 45 字以内、英語などラテン文字は 80 字以内。言い換えない・つなげない・訳さない。
該当する部分がなければ null。出力は JSON だけ: {"text": "…"}"""


CRUDE = re.compile(r"\b(shit|fuck\w*|damn|crap|ass)\b|クソ|くそ|糞", re.I)


def _calm_first(excerpts: list[dict]) -> list[dict]:
    """引用に出す抜粋。罵り言葉を含まない抜粋があればそれだけ、なければそのまま（サイトの最上部の引用に罵り言葉を選ばない。
    抜粋そのもの・発見の記録は変えない）。"""
    calm = [x for x in excerpts if not CRUDE.search(x["text"])]
    return calm or list(excerpts)


def _anchor(f: dict) -> dict | None:
    """中心の出来事: 主な論点の抜粋のうち、罵り言葉がなく中身の文字数が最も多いもの（最も具体的な原文）。
    意見が分かれている論点（sides）は中心を 1 つに決めない（片側だけを見出しにしない。ADR 0052）。"""
    if f.get("sides"):
        return None
    ex = _calm_first(f.get("excerpts") or [])
    return max(ex, key=lambda x: (content_length(x["text"]), x["text"])) if ex else None


def enrich(reader: DayReader, f: dict, model: str, llm_pick=None) -> dict:
    """文章の材料を足す（発見の記録は変えない）: 根拠の投稿の言語ごとの人数（topic_lang_counts）・言語ごとの原文の抜粋（by_lang）・
    中心の出来事（anchor）。記録に抜粋のない言語は、その言語の根拠の投稿の原文から一字一句の抜粋を選ばせ、原文と照合する（作らない）。"""
    rows = reader.item_texts(f.get("source"), list(f.get("evidence") or []))
    by_post = {u: (lg, re.sub(r"\s+", " ", t or "")) for u, lg, t in rows}
    counts: dict[str, int] = {}
    for u in f.get("evidence") or []:
        if u in by_post and is_language(by_post[u][0]) and by_post[u][0] in NAMES:   # 判定できた言語の人だけ。残りが「言語を判定できない投稿」（§1）
            counts[by_post[u][0]] = counts.get(by_post[u][0], 0) + 1
    order = [a["code"] for a in f.get("added") or []] + sorted(counts, key=lambda c: (c == "ja", -counts[c], c))
    by_lang = {}
    for lg in dict.fromkeys(order):
        if lg not in counts:
            continue
        ex = next((x for x in _calm_first(f.get("excerpts") or []) if x["lang"] == lg), None)
        if ex is None:
            posts = [(u, t) for u, (post_lang, t) in by_post.items() if post_lang == lg][:3]
            texts = [t for _, t in posts]
            note = None
            for k in range(3):   # 長すぎる・原文にない・途中で切れた抜粋は、理由を伝えて選び直させる（上限は max_excerpt_length）
                try:
                    req = {"topic": f["topic"]["ja"], "posts": texts, **({"note": note} if note else {})}
                    raw = (llm_pick or (lambda ts, rq=req: _chat(model, PICK_SYSTEM, json.dumps(rq, ensure_ascii=False), 200, seed=42 + k)))(texts)
                except Exception:  # noqa: BLE001 — 選べなければ、その言語の引用は出さない（人数だけ）
                    break
                cand = str((raw or {}).get("text") or "").strip()
                hit = next((t for t in texts if cand and cand in t), None)
                if hit and len(cand) > max_excerpt_length(cand):
                    note = f"前の抜粋は {len(cand)} 字で長すぎます。原文のまま、{max_excerpt_length(cand)} 字以内の部分を選び直してください。"
                    continue
                v, src = next(((x, u) for x, u in ((verbatim_span(cand, t), u) for u, t in posts) if x), (None, None))
                if v and content_length(v) >= EXCERPT_MIN_CONTENT and not CRUDE.search(v):
                    ex = {"text": strip_brackets(v), "lang": lg, "picked": True, "uri": src, "source": f.get("source")}
                    break
                note = ("前の抜粋は短すぎて論点の中身が分かりません。何についての話かが分かる、もっと具体的な部分を原文のまま選び直してください。"
                        if v and content_length(v) < EXCERPT_MIN_CONTENT else
                        "前の抜粋は罵り言葉を含みます。別の部分を原文のまま選び直してください。" if v else
                        "前の抜粋は原文と一字一句同じでないか、文の途中で切れています。1 つの文として読める部分を原文のまま選び直してください。")
        by_lang[lg] = {"people": counts[lg], "excerpt": ex}
    return {**f, "topic_lang_counts": counts, "by_lang": by_lang, "anchor": _anchor(f)}


TRANSLATE_SYSTEM = {
    "ja": """次の引用（ゲームプレイヤーの投稿の一部）を、自然な日本語に訳してください。意味を足さない・要約しない・評価しない。
work（作品名）と topic（この引用が書いている論点）は、語の意味を決めるための手がかりです（例: ゲームの話の ending・opening は ED・OP〔主題歌の映像〕のこと。人名はカタカナで）。手がかりの言葉を訳に足さない。
出力は JSON だけ: {"meaning": "…"}""",
    "en": """Translate the quoted fragment of an anime fan's post into natural English. Do not add, summarize or judge.
`work` (the title) and `topic` (what the quote is about) are hints for word meanings only; do not add their words to the translation.
Japanese notes: a sentence ending in 〜ない / 〜じゃない / 〜てない is often a question or a check ("hasn't it…?", "isn't it…?"), not a negation; 〜やん is Kansai for 〜じゃない (emphasis).
Output JSON only: {"meaning": "..."}""",
}
NOTE_IN_MEANING = re.compile(r"※|注[:：]|Note[:：]|\(note|文脈上|context", re.I)


QUOTE_SCREEN_SYSTEM = """ゲームプレイヤーの投稿の一部（quote）が、ある論点（topic）の根拠になるかを判定してください。材料は work（作品名）・topic・quote。
work は確かめてあるので、topic の中の作品名・キャラクター名・作品の世界観の言葉は判定に使わない（quote にそれらがなくてよい）。
- sexual: 性的な表現（性行為・性器・性的な身体の描写・性的な嗜好の話題）を含むか。作品の内容の説明やキャラクターの性格・関係性の話は含まない。
- supports: quote だけを読んだ読者が、topic の話だと分かるか。topic の一部（場面・要素・作ったもの・行動のどれか）にふれていれば true。
  false にするのは次のときだけ: topic と別の話／場面の描写の断片・掛け声・挨拶だけで何の話か分からない／意味が通らない。
出力は JSON だけ: {"sexual": true または false, "supports": true または false}"""


def _screen_targets(f: dict) -> list[tuple[dict, str]]:
    """引用の候補と、それが裏付ける論点（違う方向の声 / ほかの論点の抜粋はその論点）。"""
    own = [(x, f[k]["topic"]["ja"]) for k in ("contrast", "also") if f.get(k) for x in f[k]["excerpts"][:1]]
    own_texts = {x["text"] for x, _ in own}
    return [(x, f["topic"]["ja"]) for x in cite_pool(f) if x["text"] not in own_texts] + own


def withheld_quotes(model: str, f: dict, llm=None) -> dict[str, str]:
    """引用の候補のうち、公開の引用に出さない原文と理由（人数・論点の根拠には残す。観測の原文・履歴は消さない）。何が不確かなのかを分けて記録する（§0.6 引用の基準）:
      sexual          … 性的な表現（プラットフォームの内容ラベルが付かない投稿でも。語の一覧を足して追いかけない: 2026-10-10）
      not_about_topic … 抜粋だけでは論点の根拠だと読めない・意味が通らない（2026-10-24 の「Ofuda out, flames up, argument over」は
                        ハッシュタグの #fanart を外すとプレイヤーアートの話だと分からなかった。Issue #41。10/15〜24 の合格の引用 17 件で判定を確かめた）
      unclassified    … 判定できなかった（出さない側に倒す）"""
    out: dict[str, str] = {}
    work = f["works"][0]["ja"]
    for x, topic in {x["text"]: (x, t) for x, t in _screen_targets(f)}.values():
        try:
            q = {"work": work, "topic": topic, "quote": x["text"]}
            r = (llm or (lambda q: _chat(model, QUOTE_SCREEN_SYSTEM, json.dumps(q, ensure_ascii=False), 60)))(q) or {}
            if r.get("sexual") is not False:
                out[x["text"]] = "sexual"
            elif r.get("supports") is not True:
                out[x["text"]] = "not_about_topic"
        except Exception:  # noqa: BLE001
            out[x["text"]] = "unclassified"
    return out


def translate_quotes(model: str, f: dict, loc: str, llm=None) -> list[dict]:
    """読者の言語でない引用の訳（引用ごとに 1 回、訳だけを頼む。文章の部品と同じ呼び出しで訳させると誤訳が出た: 2026-10-13
    「ノリコの性格変わっちゃってない」→「性格は変わっていない」）。注釈・推測を足した訳は使わない。
    作品名と、その引用が裏付ける論点を語の意味の手がかりとして渡す（10/25: ED の話の「ending」を「結末」と訳した）。"""
    out, seen = [], set()
    own = {x["text"]: f[k]["topic"][loc] for k in ("contrast", "also") if f.get(k) for x in f[k]["excerpts"][:1]}
    work, topic = ((f.get("works") or [{}])[0]).get(loc), (f.get("topic") or {}).get(loc)
    for x in cite_pool(f):
        if x["lang"] == loc or x["text"] in seen:
            continue
        seen.add(x["text"])
        for k in range(2):
            try:
                hint = {k_: v for k_, v in {"quote": x["text"], "work": work, "topic": own.get(x["text"]) or topic}.items() if v}
                m = (llm or (lambda q, k=k, hint=hint: _chat(model, TRANSLATE_SYSTEM[loc], json.dumps(hint, ensure_ascii=False), 200, seed=42 + k)))(x["text"])
            except Exception:  # noqa: BLE001 — 訳せなければ、その引用は出さない
                break
            mean = str((m or {}).get("meaning") or "").strip()
            if not mean or NOTE_IN_MEANING.search(mean):
                continue
            out.append({"quote": x["text"], "meaning": mean})
            break
    return out


# ---------------------------------------------------------------- 段 5 文章（ADR 0052: 地の文は読者の言語、原文は出典として分ける）
# 2026-10-16 のユーザーの指摘: 日本語の文章の中にポルトガル語・英語の原文が混ざり読みにくい。少数の強い否定の声を、サイトの代表の発見として
# 一般化した見出しにしていた（「最悪のプレイヤーサービスだという意見が出ています」は 2 人のうちの 1 人）。
# 文章 = 見出し（LLM の部品。規模を書く）＋ 規則で組む文（論点の人数と言語の内訳・違う方向の声 / ほかの論点・作品の変化）。
# 引用（cites）は文章と分け、原文・訳・言語・投稿へのリンクを持つ出典として画面に並べる。
PARTS_SYSTEM = {   # 論点の名詞句だけを LLM に頼む（見出しは規則で組む: rule_lead。1 人の具体的な言葉は引用の欄に）
    "ja": """あなたは、世界のゲームプレイヤーの反応を観測するサイトの編集者です。材料は finding だけです。次の部品を JSON で返してください（文章は組み立て側が作ります）。
- point: 「〜について書いたプレイヤー」の「〜」に入る短い名詞句（finding.point_max_chars があればその字数以内、なければ 25 字以内。引用なし。原文にある話数などの数字は書いてよい）。finding.topic を具体的に、自然な日本語で。外国語の原文を書かない。人名・作中の固有名詞は英字で書かず、excerpts の meaning の表記（カタカナなど）で書く（finding.topic に英字があっても）。
- contrast_point / also_point: finding.contrast / finding.also があれば同じ形の名詞句、なければ null。
推測・宣伝の言葉を使わない。出力は JSON だけ: {"point": "…", "contrast_point": null, "also_point": null}""",
    "en": """Using only `finding`, return JSON parts. point: a short natural English noun phrase (at most finding.point_max_chars characters if given, otherwise under 12 words; no quotes) that fits "fans who wrote about <point>", concrete; an episode number may appear only if it is in the posts.
contrast_point / also_point: the same for finding.contrast / finding.also, or null. No hype. Output JSON only: {"point": "...", "contrast_point": null, "also_point": null}""",
}


def _parts_view(f: dict, loc: str, meanings: dict) -> dict:
    a = f.get("anchor")
    o = {"work": f["works"][0][loc], "topic": f["topic"][loc], "kind": f.get("kind"), "languages": _lang_names(f["topic_languages"], loc),
         "excerpts": [{"original": x["text"], "meaning": meanings.get(x["text"]) if x["lang"] != loc else x["text"]} for x in f["excerpts"]]}
    if a:
        o["anchor"] = {"original": a["text"], "meaning": meanings.get(a["text"]) if a["lang"] != loc else a["text"]}
    for k in ("contrast", "also"):
        if f.get(k):
            o[k] = {"topic": f[k]["topic"][loc], "languages": _lang_names(f[k].get("languages") or [], loc)}
    if f.get("page") != "spread":   # ダッシュボードの見出しは「「作品」で、N人のプレイヤーが〈point〉について書いています。」: 作品名が長いほど point は短く
        o["point_max_chars"] = point_max_chars(f, loc)
    if f.get("context"):
        o["context"] = f["context"]
    return o


def ask_parts(model: str, f: dict, loc: str, feedback: str | None, attempt: int = 0) -> dict:
    meanings = translate_quotes(model, f, loc)   # 引用の訳は訳だけの呼び出しで（先に訳し、中心の出来事の意味を部品の材料にする）
    view = _parts_view(f, loc, {m["quote"]: m["meaning"] for m in meanings})
    user = json.dumps({"finding": view}, ensure_ascii=False)
    if feedback:
        user += ("\n前の出力は次の検査に通りませんでした。直してください: " if loc == "ja" else "\nThe previous output failed these checks; fix it: ") + feedback
    system = PARTS_SYSTEM[loc]
    p = _chat(model, system, user, 600, seed=42 + attempt, temperature=0 if not attempt else 0.4)
    if isinstance(p, dict):
        p["meanings"] = meanings
    return p


def _join_langs(codes, loc: str) -> str:
    ns = _lang_names(codes, loc)
    return ("・".join(ns) if loc == "ja" else (" and ".join(ns) if len(ns) <= 2 else ", ".join(ns[:-1]) + " and " + ns[-1]))


def _counts_label(counts: dict[str, int], loc: str, total: int | None = None) -> str:
    """言語ごとの人数（「英語2人・日本語2人」）。言語を判定できない投稿の人は「言語を判定できない投稿1人」として足し、内訳の合計を total にそろえる。"""
    order = sorted(counts, key=lambda c: (c == "ja", -counts[c], c))
    rest = (total or 0) - sum(counts.values())
    if len(order) == 1 and rest <= 0:   # 1 つの言語だけ（「3人（日本語3人）」と繰り返さない）
        return f"すべて{_lang_names(order, loc)[0]}" if loc == "ja" else f"all in {_lang_names(order, loc)[0]}"
    if loc == "ja":
        return "・".join([f"{_lang_names([c], loc)[0]}{counts[c]}人" for c in order] + ([f"言語を判定できない投稿{rest}人"] if rest > 0 else []))
    return ", ".join([f"{counts[c]} in {_lang_names([c], loc)[0]}" for c in order] + ([f"{rest} in an undetermined language"] if rest > 0 else []))


def post_url(source: str | None, uri: str) -> str:
    """引用のリンク（取得元の permalink。取得元の名前で分岐しない）。"""
    from game_signal_scout.sources import factory
    return factory.permalink(source, uri)


def _fmt_base(b: float) -> str:
    return str(int(b + 0.5))


def change_sentence(f: dict, loc: str) -> str | None:
    """作品の変化の文（全 Source 共通の基盤の分析の値。ADR 0052）。変化がない日は書かない。数は、その作品に触れた独立した投稿者（品質判定の後）。"""
    if f.get("page") == "spread":
        return None
    ch = ((f.get("assessment") or {}).get("change") or {})
    k, n, b = ch.get("kind"), ch.get("n"), ch.get("base")
    if k == "surge" and n:
        if b is None or b < 1:
            return ("この作品は普段ほとんど話題にならない作品でしたが、この日は" + f"{n}人が触れました。") if loc == "ja" else \
                f"This title is usually barely talked about; on this day {n} people mentioned it."
        return (f"この作品に触れた人は、普段の1日{_fmt_base(b)}人前後から、この日{n}人に増えました。" if loc == "ja" else
                f"People mentioning the title rose from about {_fmt_base(b)} a day to {n} on this day.")
    first = (f"この作品は、これまでの観測でこの日初めて話題になりました（{n}人）。" if loc == "ja" else
             f"This was the first day the title was talked about in what we observed ({n} people).")
    if k == "emergence" and n:
        return first
    if k == "new_language" and ch.get("new_langs"):
        ls = [l for l in ch["new_langs"] if l in digest_languages()]
        if ls:
            return f"この日は{_join_langs(ls, loc)}でも2人以上がこの作品に触れました。" if loc == "ja" else f"On this day at least 2 people also mentioned it in {_join_langs(ls, loc)}."
    ek = (f.get("assessment") or {}).get("change_kind") or ""
    if ek == "entry:premiere" and n:
        return f"この日は放送が始まった日で、{n}人がこの作品に触れました。" if loc == "ja" else f"This was the day it premiered; {n} people mentioned it."
    if ek == "entry:again" and n:
        return (f"この作品は、しばらく話題になっていなかった後、この日{n}人が触れました。" if loc == "ja" else
                f"After a quiet stretch, {n} people mentioned the title on this day.")
    if ek == "entry:first" and n:
        return first
    if k == "continuing" and n and ch.get("streak"):
        return (f"この作品は、話題が急に増えてから{ch['streak']}日目のこの日も{n}人が触れています。" if loc == "ja" else
                f"On day {ch['streak']} after its rise, {n} people still mentioned the title.")
    return None


def _cites(f: dict, meanings: dict, loc: str) -> list[dict]:
    """文章に添える引用（出典）。主な論点（意見が分かれていれば両側から 1 つずつ。そうでなければ中心の出来事と、別の言語の 1 つ）→ 言語ごと（世界で広がる作品）→
    違う方向の声 / ほかの論点。読者の言語でない引用は訳のあるものだけ（訳のない原文を出さない）。"""
    unsafe = {x["quote"] for x in f.get("withheld_quotes") or []}

    def c(x, role):
        if x["text"] in unsafe or (x["lang"] != loc and not meanings.get(x["text"])):
            return None
        return {"lang": x["lang"], "quote": x["text"], "meaning": meanings.get(x["text"]) if x["lang"] != loc else None,
                "url": post_url(x.get("source"), x.get("uri")), "role": role, "source": x.get("source"), "item": x.get("uri")}
    out: list[dict] = []
    ex = _calm_first(f["excerpts"])
    if f.get("page") == "spread":
        main = [b["excerpt"] for b in (f.get("by_lang") or {}).values() if b.get("excerpt")][:3] or ex[:2]
        roles = ["main"] * len(main)
    elif f.get("sides"):
        main = [x for side in ("for", "against") for x in [next((y for y in ex if y.get("side") == side), None)] if x]
        roles = [x["side"] for x in main]
    else:
        a = f.get("anchor")
        rest = [x for x in ex if not a or x["text"] != a["text"]]
        other = next((x for x in rest if a and x["lang"] != a["lang"]), rest[0] if rest else None)
        main = [x for x in ([a] if a else []) + ([other] if other else []) if x][:2]
        roles = ["main"] * len(main)
    def add(y):   # 同じ投稿・重なる文の引用は 1 つだけ
        if y and not any(y["quote"] in z["quote"] or z["quote"] in y["quote"] or (y["url"] and y["url"] == z["url"]) for z in out):
            out.append(y)
    for x, r in zip(main, roles):
        add(c(x, r))
    for k in ("contrast", "also"):
        if f.get(k) and f[k]["excerpts"]:
            add(c(f[k]["excerpts"][0], k))
    return out


def compose(f: dict, parts: dict, loc: str) -> dict:
    """部品と記録から文章と引用を組む。人数・言語・作品の変化は記録の値だけ。文章の中に原文を混ぜない（引用は cites）。"""
    p = parts or {}
    mean = {str(m.get("quote")): str(m.get("meaning") or "").strip().rstrip("。.") for m in (p.get("meanings") or []) if isinstance(m, dict)}
    work = f["works"][0][loc]
    point = str(p.get("point") or "").strip().rstrip("。.")
    counts = f.get("topic_lang_counts") or {}
    total = f["people_on_topic"]
    lab = _counts_label(counts, loc, total) if counts or total else None   # 全員の言語を判定できない日も「言語を判定できない投稿N人」と書く
    sents = []
    if f.get("page") == "spread":
        # 1 文目: どの言語圏で観測されたか（前日との比較）。伝わった・広まったとは書かない（観測されたことと伝播は別）
        # 2 番目以降の Source で数えた言語は出典を添える（ページの表示と同じ。人数は Source の中の数）
        add_ja = "・".join(f"{_lang_names([a['code']], 'ja')[0]}で投稿した{a['people']}人" + (f"（{a['src_label'][0]}）" if a.get("src_label") else "") for a in f["added"])
        add_en = ", ".join(f"{a['people']} people posting in {_lang_names([a['code']], 'en')[0]}" + (f" ({a['src_label'][1]})" if a.get("src_label") else "") for a in f["added"])
        if f.get("before"):
            sents.append(f"「{work}」は前日、{_join_langs(f['before'], loc)}で2人以上が話題にしていた作品で、この日は{add_ja}もこの作品に触れました。" if loc == "ja" else
                         f"{work} was talked about by at least 2 people in {_join_langs(f['before'], loc)} the day before; on this day, {add_en} also mentioned it.")
        else:
            sents.append(f"「{work}」は前日、どの言語でも2人以上が話題にしていなかった作品で、この日は{add_ja}がこの作品に触れました。" if loc == "ja" else
                         f"{work} was not talked about by 2 or more people in any language the day before; on this day, {add_en} mentioned it.")
    else:
        lead = str(p.get("lead_rule") or "")
        if loc == "en" and lead[:1].islower():   # 規模の言葉「fans」で始まる見出しの文頭（表記だけ）
            lead = lead[0].upper() + lead[1:]
        sents.append(lead)
    sides = f.get("sides")
    if p.get("lead_rule") and not sides and f.get("page") != "spread":   # 規則の見出しは論点と人数を持つので、2 文目は言語の内訳だけ（同じ句を繰り返さない）
        sents.append((f"書いた人の言語は、{lab}です。" if loc == "ja" else f"By language: {lab}.") if lab else None)
        sents = [x for x in sents if x]
    elif loc == "ja":
        second = f"{point}について書いたプレイヤーは{total}人" + (f"（{lab}）" if lab else "")
        sents.append(second + (f"で、意見は{sides['for']}人と{sides['against']}人に分かれています。" if sides else "です。"))
    else:
        second = f"{total} players" + (f" ({lab})" if lab else "") + f" wrote about {point}"
        sents.append(second + (f", split {sides['for']} to {sides['against']}." if sides else "."))
    for k in ("contrast", "also"):
        c = f.get(k)
        if not c:
            continue
        cp = str(p.get(f"{k}_point") or "").strip().rstrip("。.")
        cl = c.get("languages") or []
        if loc == "ja":
            sents.append(("一方で、" if k == "contrast" else "また、") + f"{_join_langs(cl, loc) + 'の' if cl else ''}プレイヤー{c['people_on_topic']}人は{cp}" +
                         ("を挙げています。" if k == "contrast" else "について書いています。"))
        else:
            sents.append(("Meanwhile, " if k == "contrast" else "Also, ") + f"{c['people_on_topic']} players" + (f" writing in {_join_langs(cl, loc)}" if cl else "") + f" wrote about {cp}.")
        break
    cs = change_sentence(f, loc)
    if cs:
        sents.append(cs)
    return {"sentences": sents, "cites": _cites(f, mean, loc), "anchor_meaning": (mean.get(f["anchor"]["text"]) if f.get("anchor") and f["anchor"]["lang"] != loc else
                                                                                 (f["anchor"]["text"] if f.get("anchor") else None))}


# ---------------------------------------------------------------- 段 6 検査（ADR 0052: 記録・原文との照合。合格は事実と食い違わないことの確認で、価値の保証ではない）
def _anchor_for(f: dict, loc: str, model: str, llm=None) -> dict:
    """中心の出来事（anchor）が読者の言語でなく、注釈のない訳が得られないとき、読者の言語の抜粋か、訳の得られる別の抜粋を中心に選び直す。候補がなければ元のまま。"""
    a = f.get("anchor")
    if not a or a["lang"] == loc:
        return f
    def ok(x):
        return x["lang"] == loc or bool(translate_quotes(model, {"excerpts": [x], "anchor": None, "by_lang": {}}, loc, llm=llm))
    if ok(a):
        return f
    pool = [x for x in _calm_first(f.get("excerpts") or []) if x["text"] != a["text"]]
    pool += [b["excerpt"] for b in (f.get("by_lang") or {}).values() if b.get("excerpt") and b["excerpt"]["text"] != a["text"]]
    for x in sorted(pool, key=lambda x: x["lang"] != loc):
        if ok(x):
            return {**f, "anchor": x}
    return f


def _lead_text(f: dict, point: str, loc: str) -> str:
    from game_signal_scout.ops.finding_assess import fans_label
    work = f["works"][0][loc]
    who = fans_label(f["people_on_topic"], loc)
    if f.get("sides"):
        return f"「{work}」の{point}をめぐって、{who}の評価が分かれています。" if loc == "ja" else f"{who} were divided over {point} in {work}."
    return f"「{work}」で、{who}が{point}について書いています。" if loc == "ja" else f"{who} of {work} wrote about {point}."


def point_max_chars(f: dict, loc: str) -> int:
    """見出しを上限（LEAD_MAX）に収めるために、論点の名詞句に使える字数（作品名が長いほど短い。10/23 の「サイバーパンク: エッジランナーズ2」は 19 字）。"""
    return LEAD_MAX[loc] - len(_lead_text(f, "", loc))


def rule_lead(f: dict, parts: dict, loc: str) -> str | None:
    """見出し（記録から規則で組む）。規模を書き、論点の名詞句を使う（原文は入れない）。上限を超えるときは None（短い point を頼み直す）。"""
    point = str((parts or {}).get("point") or "").strip().rstrip("。.") or f["topic"][loc].rstrip("。.")
    lead = _lead_text(f, point, loc)
    return lead if len(lead) <= LEAD_MAX[loc] else None


def write(f: dict, model: str, all_names: dict[str, set[str]], llm=None, log=print, tries: int = 4, llm_screen=None, llm_translate=None) -> dict:
    """ja・en の文章を書く。LLM に頼むのは論点の名詞句（point など）だけで、見出しは記録から規則で組む（rule_lead: 「N人のプレイヤーが〈論点〉について書いています」）。
    論点の人は必ず 2 人以上で、中心の出来事は 1 人の投稿なので、その具体的な言葉は見出しにせず引用の欄に示す（§0.6-2。Issue #41）。
    検査に通らなければ、指摘を添えて point を頼み直す（発見はやり直さない。ADR 0052）。
    llm（部品）・llm_screen（引用の判定）・llm_translate（訳）は、試験が偽物を渡す口。どれを渡しても通る段は本番と同じ（#46 D1）。"""
    res = {}
    call = llm or (lambda fx, loc, fb, k: ask_parts(model, fx, loc, fb, k))
    bad = withheld_quotes(model, f, llm_screen)   # 引用の候補の判定
    if bad:
        f = {**f, "withheld_quotes": [{"quote": q, "reason": r} for q, r in sorted(bad.items())]}
        if f.get("anchor") and f["anchor"]["text"] in bad:   # 中心の出来事も別の抜粋に（見出しの材料にしない）
            rest = [x for x in _calm_first(f["excerpts"]) if x["text"] not in bad]
            f = {**f, "anchor": max(rest, key=lambda x: (content_length(x["text"]), x["text"])) if rest else None}
        log(f"{f.get('page') or 'dashboard'}_digest: 公開の引用に出さない {len(bad)} 件（{', '.join(sorted(set(bad.values())))}）")
    for loc in ("ja", "en"):
        hist, fb = [], None
        fl = _anchor_for(f, loc, model, llm_translate)
        for k in range(tries):
            p = None
            try:
                p = call(fl, loc, fb, k)
                if f.get("page") != "spread" and isinstance(p, dict):
                    p = {**p, "lead_rule": rule_lead(fl, p, loc)}
                if f.get("page") != "spread" and not p.get("lead_rule"):
                    v = {"passed": False, "errors": [f"lead_too_long:{point_max_chars(fl, loc)}"]}   # 論点の名詞句が長く、見出しが上限を超える
                else:
                    v = validate(compose(fl, p, loc), fl, loc, all_names[loc], p)
            except Exception as ex:  # noqa: BLE001 — LLM が使えない日はブロックを出さない（daily-run は止めない）
                v = {"passed": False, "errors": [f"llm_error:{type(ex).__name__}:{str(ex)[:120]}"]}
            hist.append(v)
            if v["passed"]:
                break
            fb = feedback_for(v["errors"], loc, p if isinstance(p, dict) else None)
        res[loc] = {**hist[-1], "attempts": len(hist)}
        log(f"{f.get('page') or 'dashboard'}_digest {loc}: {'PASS' if hist[-1]['passed'] else 'FAIL ' + str(hist[-1]['errors'][:5])} (attempts {len(hist)})")
    # 日英で同じ事実（数字）を書いているか。食い違えば両方を出さない
    if res["ja"].get("passed") and res["en"].get("passed"):
        nj = count_numbers(" ".join(x["text"] for x in res["ja"]["sentences"]), "ja")
        ne = count_numbers(" ".join(x["text"] for x in res["en"]["sentences"]), "en")
        if nj != ne:
            for loc in ("ja", "en"):
                res[loc] = {**res[loc], "passed": False, "errors": res[loc]["errors"] + [f"ja_en_mismatch:{nj}≠{ne}"]}
    # 片方の言語だけが通った日は、両方を出さない（画面の言語ごとに別の発見・別の作品にならないように。ADR 0052）
    if bool(res["ja"].get("passed")) != bool(res["en"].get("passed")):
        for loc in ("ja", "en"):
            if res[loc].get("passed"):
                res[loc] = {**res[loc], "passed": False, "errors": (res[loc].get("errors") or []) + ["other_language_failed"]}
    for loc in ("ja", "en"):
        res[loc]["checks"] = classify(res[loc].get("errors") or [])
    res["withheld_quotes"] = f.get("withheld_quotes")   # 記録に残す（引用に出さなかった原文と理由）
    return res


# ---------------------------------------------------------------- 1 日分
def _work_card(conn, w: dict) -> dict:
    """候補の作品を、発見の材料の形（key・keys・work_id・display_name・name）にそろえる。"""
    from game_signal_scout.ops import work_display
    n = work_display.display_names(conn, [w["work_id"]])[w["work_id"]]
    return {"key": f"w{w['work_id']}", "keys": w["keys"], "work_id": w["work_id"], "display_name": n, "name": n["ja"]}


MAX_CHANGE_WORKS = 4   # プレイヤーの声の多い作品のほかに候補に足す、普段と違う動きのあった作品（共通基盤の分析。ADR 0052）


def _candidate_works(conn, source: str, day: date, changes: dict | None) -> list[dict]:
    """候補 = その日にプレイヤー本人の声の多い作品（仕様 §1）＋ 作品自身の普段と比べて動いた作品（声の数が少なくても、変化の中身を確かめる）。その Source の中で。"""
    from game_signal_scout.ops.finding_assess import CHANGE as CH
    rows = day_works(conn, source, day, limit=10_000)
    top = rows[:MAX_CARDS]
    have = {w["work_id"] for w in top}

    def mine(w):   # 声と同じ Source の変化
        c = (changes or {}).get(w) or {}
        return (c.get("by_source") or {}).get(source) or {}
    moved = sorted([w for w in rows if w["work_id"] not in have and mine(w["work_id"]).get("kind") in CH and w["voices"] >= MIN_TOPIC_PEOPLE],
                   key=lambda w: (-(mine(w["work_id"]).get("ratio") or 0), -w["voices"], w["work_id"]))
    return top + moved[:MAX_CHANGE_WORKS]


def _evidence_texts(voices: list[dict], f: dict) -> tuple[list[str], list[str]]:
    ev = set(f.get("evidence") or []) | {u for k in ("contrast", "also") if f.get(k) for u in f[k].get("evidence") or []}
    return [v["text"] for v in voices if v["uri"] in ev], [v["text"] for v in voices if v["lang"] == "ja"]


def _findings(model: str, entries, page: str, llm_topics=None, log=print) -> tuple[list[dict], list[dict]]:
    """段 1〜4 の発見の記録まで（2 つのページ共通。仕様 §0.2 の 1・§1・§2「§1 と同じ取り出し・成立条件」）。entries は 1 作品ずつ
    (source, voices, ctx_lines, rec, change, make)。make(topics) がそのページの発見の記録（build_finding・spread_finding）。
    返り値は (作品ごとの記録, 発見の記録)。評価は finding_assess（ADR 0052）。"""
    from game_signal_scout.ops import finding_assess
    per_work, findings = [], []
    for source, voices, ctx_lines, rec, ch, make in entries:
        if len(voices) < MIN_TOPIC_PEOPLE:
            per_work.append({**rec, "reason": "fewer_than_two_voices"})
            continue
        try:
            raw = (llm_topics or (lambda w, vs, cx: ask_topics(model, w, vs, cx)))(rec["work"], voices, ctx_lines)
        except Exception as ex:  # noqa: BLE001
            per_work.append({**rec, "reason": f"llm_error:{type(ex).__name__}"})
            continue
        topics = verify_topics(raw, voices)
        f = make(topics)
        if f:
            f["source"] = source
            f["source_texts"], f["source_texts_ja"] = _evidence_texts(voices, f)
            f["assessment"] = finding_assess.assess(f, ch, len(voices), source)
        per_work.append({**rec, "topics": topics, "finding": bool(f), "tier": f["assessment"]["tier"] if f else None})
        log(f"{page} {rec['work']}: voices {len(voices)} topics {sum(t['ok'] for t in topics)}/{len(topics)} "
            f"{'tier ' + str(f['assessment']['tier']) + ' ' + f['topic']['ja'] if f else 'no finding'}")
        if f:
            findings.append(f)
    return per_work, findings


def _settle(reader: DayReader, model: str, out: dict, findings: list[dict], names, signal, page: str, llm_text=None, llm_support=None, log=print,
            llm_screen=None, llm_translate=None) -> dict:
    """段 4〜6（2 つのページ共通）: 論点が根拠で支えられている発見を 1 つ選び（§0.7）、文章の材料を足して（発見の記録は変えない）、文章と検査。
    names() は作品名の一覧（言語ごと）、signal(best) は記録に残す発見の作品。out は作品ごとの記録・候補を持つ途中の記録（ここで完成させる）。"""
    best, rejected = judge_supported(findings, model, llm_support, log=log)
    out.update(rejected_findings=rejected, finding=best, signal=signal(best) if best else None)
    if not best:
        out.update(passed=False, reason="no_finding", ja=None, en=None)
        log(f"{page}: no finding today (no block)")
        return out
    best = enrich(reader, best, model)   # 中心の出来事・言語ごとの人数と原文の抜粋。発見の記録は変えない
    out["finding"] = best
    out.update(write(best, model, names(), llm=llm_text, log=log, llm_screen=llm_screen, llm_translate=llm_translate))
    out["passed"] = bool(out["ja"]["passed"] and out["en"]["passed"])
    return out


def generate_day(reader: DayReader, cfg: dict, day: date, llm_topics=None, llm_text=None, log=print,
                 llm_support=None, changes: dict | None = None, llm_screen=None, llm_translate=None) -> dict:
    """その日の発見を確定し、文章にする（保存はしない）。返り値は job_artifact に保存する記録。
    changes = 作品ごとの普段と比べた変化（publication/movement.work_changes。全 Source 共通の基盤）。評価と選定は finding_assess（ADR 0052）。"""
    from game_signal_scout.ops import finding_assess
    model = (cfg.get("dashboard_digest") or {}).get("model")
    groups = [(s, reader.candidates(s, day, changes)) for s in reader.sources(cfg)]   # 声の取得元ごとに候補を選ぶ（Source をまたいで足さない）
    cands = [c for _, cs in groups for c in cs]

    def entries():
        for source, c in ((s, c) for s, cs in groups for c in cs):
            voices = reader.voices(source, day, c)
            ctx_lines = reader.context(source, day, c.get("keys") or [c["key"]])
            c = {**c, "context": ctx_lines}
            ch = (changes or {}).get(c.get("work_id"))
            rec = {"key": c.get("key"), "work_id": c.get("work_id"), "work": _name(c, "ja"), "source": source, "voices": len(voices), "context": ctx_lines,
                   "change": {k: ch.get(k) for k in ("kind", "n", "base", "ratio", "streak", "entry")} if ch else None}
            yield source, voices, ctx_lines, rec, ch, (lambda topics, c=c: build_finding(c, topics))
    per_work, findings = _findings(model, entries(), "dashboard_digest", llm_topics, log)
    out = {"model": model, "version": VERSION, "sources": voice_sources(cfg), "per_work": per_work,
           "candidates": [{"work": f["works"][0]["ja"], "tier": f["assessment"]["tier"], "claim": f["assessment"]["claim"], "kind": f["kind"],
                           "topic": f["topic"]["ja"], "people": f["people_on_topic"], "change": (f["assessment"].get("change") or {}).get("kind"),
                           "excerpts": [x["text"] for x in f["excerpts"]]} for f in sorted(findings, key=finding_assess.order_key)[:8]]}
    return _settle(reader, model, out, findings, lambda: {loc: {_name(c, loc) for c in cands} for loc in ("ja", "en")},
                   lambda best: {"works": [{**best["works"][0], "work_id": best["work_id"]}]}, "dashboard_digest", llm_text, llm_support, log, llm_screen, llm_translate)


# ---------------------------------------------------------------- 保存の鍵と保存した文章
def input_key(conn, day: date, sources: list[str], changes: dict | None) -> str:
    """その日の入力の鍵: 声の取得元ごとの候補の作品（_candidate_works と同じ集合: 声の多い作品と、普段と比べて動いた作品）と声の人数・変化の種類の hash
    （同じ入力なら作り直さない。動いた作品が入れ替われば作り直す。#46 D5）。"""
    import hashlib
    rows = [(s, w["work_id"], w["voices"], ((changes or {}).get(w["work_id"]) or {}).get("kind")) for s in sources for w in _candidate_works(conn, s, day, changes)]
    conn.rollback()
    return hashlib.sha256(json.dumps(rows).encode()).hexdigest()[:16]


def stored(conn, day: date) -> dict | None:
    """表示用: その日について保存した、最新の版の文章（言語ごとに検査を通ったものだけ。古い版を代わりに出さない）。"""
    from game_signal_scout.repositories import job as job_repo
    o = job_repo.latest_artifact(conn, JOB, day)   # 作った時刻 created_at でいちばん新しい記録（版の名前を解釈しない。ADR 0054）
    return texts(o) if o else None


def texts(o: dict) -> dict | None:
    def t(loc):
        x = o.get(loc) or {}
        return ("" if loc == "ja" else " ").join(s["text"] for s in x["sentences"]) if x.get("passed") else None
    ja, en = t("ja"), t("en")
    # sents: 生成した文の区切り（画面は文の途中で段落を分けない。2026-10-16: 「。」で数え直して 1 文を 2 段落に分けていた）
    sents = {loc: [s["text"] for s in o[loc]["sentences"]] if (o.get(loc) or {}).get("passed") else None for loc in ("ja", "en")}
    # cites: 文章に添える引用（原文・訳・言語・投稿へのリンク。ADR 0052）
    cites = {loc: (o[loc].get("cites") or []) if (o.get(loc) or {}).get("passed") else None for loc in ("ja", "en")}
    return {"ja": ja, "en": en, "sents": sents, "cites": cites, "version": o.get("version"), "works": ((o.get("signal") or {}).get("works") or []),
            "evidence": list(dict.fromkeys(list((o.get("finding") or {}).get("evidence") or []) + [u for kk in ("contrast", "also") for u in (((o.get("finding") or {}).get(kk) or {}).get("evidence") or [])]))} if ja or en else None


# ================================================================ 世界で広がる作品（docs/TODAYS-SIGNAL-PAGES.md §2。ADR 0044）
# ページに実際に載る作品と言語（画面の spread の一覧: 言語ごとに 2 人以上）から、前日になかった言語にも広がった作品を候補にし、
# その作品のプレイヤーの話題（ダッシュボードと同じ段 1〜3）で「どの言語圏のプレイヤーが何を語っているか」を確かめてから書く。
SPREAD_JOB, SPREAD_VERSION = "spread_digest", "sd-2026-10-25"   # 生成の規則の版（保存した記録の鍵。名前は記録の出どころなので変えない。規則を次に変えるときは、決めた日付の名前にする。CONTRIBUTING.md）
MAX_SPREAD_ITEMS = 8

def spread_finding(item: dict, topics: list[dict]) -> dict | None:
    """世界で広がる作品の発見の記録。item は 画面の spread の 1 作品（added = 前日になかった言語、prev = 前日の言語、n = 言語ごとの人数）。
    主な論点は、加わった言語のプレイヤーの論点 → 日本語以外のプレイヤーの論点 → それ以外 の順（同じ順の中は種類の重み × 人数）。"""
    langs = digest_languages()
    added = [a for a in item.get("added") or [] if a in langs]
    if not added:
        return None
    main, contrast, also = _pick(topics, prefer=lambda t: bool(set(t["langs"]) & set(added)) or bool(set(t["langs"]) - {"ja"}))
    if not main:
        return None
    why = ["new_area"] + (["voices_new_area"] if set(main["langs"]) & set(added) else []) + (["abroad"] if set(main["langs"]) - {"ja"} else [])
    name = item.get("name") or {}
    f = {"page": "spread", "works": [{"ja": name.get("ja"), "en": name.get("en") or name.get("ja")}], "id": item.get("id"),
         "added": [{"code": a, "people": (item.get("n") or {}).get(a), **({"src_label": (item.get("src_lang_label") or {})[a]} if (item.get("src_lang_label") or {}).get(a) else {})}
                   for a in added], "before": [p for p in item.get("prev") or [] if p in langs],
         "languages": sorted(set(added) | set(item.get("prev") or []) | set(main["langs"]) | set(contrast["langs"] if contrast else [])
                             | set(also["langs"] if also else [])),
         "topic": {"ja": main["about_ja"], "en": main["about_en"]}, "kind": main["kind"], "stance": main["stance"], "people_on_topic": main["people"],
         "topic_languages": main["langs"], "excerpts": main["excerpts"][:3], "evidence": main["evidence"], "contrast": _sub(contrast), "also": _sub(also),
         "context": item.get("context") or [],
         "why": why, "page_reason": "spread: interest in the title moved into a language area it did not have the day before, and we can read what players there say",
         "limits": ["one_day_observation"], "sides": main.get("sides")}
    return f


def spread_day(reader: DayReader, cfg: dict, day: date, items: list[dict], keys_of, llm_topics=None, llm_text=None, log=print,
               llm_support=None, changes: dict | None = None, llm_screen=None, llm_translate=None) -> dict:
    """世界で広がる作品の発見を確定し、文章にする（保存は呼ぶ側）。items は 画面の spread の一覧（ダッシュボードの発見の作品を除いたもの）、
    keys_of(item) はその作品の候補の鍵、changes は作品ごとの普段と比べた変化（全 Source 共通の基盤。記録に残す）。評価と選定は finding_assess（ADR 0052）。
    ダッシュボードとは別の発見（呼ぶ側がダッシュボードの発見の作品を外す。仕様 §2）。段 1〜6 はダッシュボードと共通（_findings・_settle）。"""
    from game_signal_scout.ops import finding_assess
    model = (cfg.get("dashboard_digest") or {}).get("model")
    cands = sorted([w for w in items if w.get("added")], key=lambda w: (-sum((w.get("n") or {}).get(a, 0) for a in w["added"]), w.get("id") or ""))[:MAX_SPREAD_ITEMS]
    sources = reader.sources(cfg)   # 声の取得元ごとに別々に（Source をまたいで足さない）

    def entries():
        for source, w in ((s, w) for s in sources for w in cands):
            card = {"key": w.get("id"), "keys": keys_of(w)}
            voices = reader.voices(source, day, card) if card["keys"] else []
            ctx_lines = reader.context(source, day, card["keys"]) if card["keys"] else []
            w = {**w, "context": ctx_lines}
            ch = (changes or {}).get(int(str(w.get("id") or "w0")[1:] or 0))
            rec = {"id": w.get("id"), "work": (w.get("name") or {}).get("ja"), "added": w.get("added"), "source": source, "voices": len(voices), "context": ctx_lines}
            yield source, voices, ctx_lines, rec, ch, (lambda topics, w=w: spread_finding(w, topics))
    per_work, findings = _findings(model, entries(), "spread_digest", llm_topics, log)
    out = {"model": model, "version": SPREAD_VERSION, "sources": sources, "per_work": per_work,
           "candidates": [{"work": f["works"][0]["ja"], "tier": f["assessment"]["tier"], "topic": f["topic"]["ja"], "people": f["people_on_topic"]}
                          for f in sorted(findings, key=finding_assess.order_key)[:8]]}
    return _settle(reader, model, out, findings, lambda: {loc: {(w.get("name") or {}).get(loc) or (w.get("name") or {}).get("ja") for w in items} for loc in ("ja", "en")},
                   lambda best: {"works": best["works"]}, "spread_digest", llm_text, llm_support, log, llm_screen, llm_translate)
