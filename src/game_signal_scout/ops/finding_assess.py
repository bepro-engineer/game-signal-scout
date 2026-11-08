"""今日の兆しの発見の評価と選定（ADR 0052。docs/TODAYS-SIGNAL-PAGES.md §0.7）。ダッシュボード（dd）と世界で広がる作品（sd）が同じ仕組みを使う。

評価は 1 つの点数ではなく、確かめられる事実の記録と、そこから決まる 2 つの判断:
- 事実（assessment）: 作品の変化（全 Source 共通の基盤の分析 publication/movement.work_changes: 普段と比べた急増・初めての出現・新しい言語圏・続いている・定番）、
  論点を語った独立した人数・言語・その日の作品のプレイヤーの声に占める割合、観測した Source、意見の分かれ方（両側の人数）、新しさ（Q2 と同じ理由）。
- どこまで言えるか（claim）: individual（2 人。個々のプレイヤーの声として書く）/ several（3〜4 人）/ many（5 人以上で、その日の声の 3 割以上。
  「プレイヤーの間で」と書いてよいのはこれだけ）。見出しには individual・several のとき人数を書く（少数の声を全体の傾向に見せない）。
- 段階（tier）: ページの目的に照らした採用の順。ダッシュボード = 作品に普段と違う動きがあり、その中身を複数の独立したプレイヤーが裏付けている発見を先に。
  世界で広がる作品 = 新しく加わった言語圏のプレイヤー自身が語っている発見を先に。段階の中の順は人数・変化の大きさ・論点の種類の順（並べ方で、品質の判定ではない）。
感情の向き（肯定・否定）は採否に使わない。人数が少ないことだけで発見を消さない（段階が下がり、書き方が「個々の声」になる）。
"""
from __future__ import annotations

KIND_ORDER = {"update": 0, "statement": 0, "behavior": 1, "performance": 1, "price": 1, "event": 1, "comparison": 1, "debate": 1, "gameplay": 2, "content": 2}   # Game の論点の種類（Anime から作り替え）
CHANGE = ("surge", "emergence", "new_language", "continuing")
ENTRY = ("premiere", "first", "again")   # 前日は話題でなかった作品がこの日に話題になった理由のうち、作品の変化として扱うもの（Q2 と同じ判定。flicker・other は扱わない）
MANY_PEOPLE, MANY_SHARE, SEVERAL_PEOPLE = 5, 0.3, 3


def claim_level(people: int, voices: int) -> str:
    share = people / voices if voices else 0
    if people >= MANY_PEOPLE and share >= MANY_SHARE:
        return "many"
    return "several" if people >= SEVERAL_PEOPLE else "individual"


def fans_label(people: int, loc: str) -> str:
    """見出しに入れる規模（individual・several のとき）。"""
    return f"{people}人のプレイヤー" if loc == "ja" else f"{people} players"


def assess(f: dict, change: dict | None, voices: int, source: str | None = None) -> dict:
    """発見の記録 f の評価（事実と判断）。change は publication/movement.work_changes のその作品の値（なければ None）、voices はその日のその作品のプレイヤーの声の数、
    source は声の Source（作品の変化はこの Source の値で評価し、文章に書く。ほかの Source の変化は other_sources に記録だけする）。"""
    p = f["people_on_topic"]
    langs = list(f.get("topic_languages") or [])
    whole = change or {}
    ch = (whole.get("by_source") or {}).get(source) or ({} if whole.get("by_source") else whole)
    kind = ch.get("kind") if ch.get("kind") in CHANGE else (f"entry:{ch['entry']}" if ch.get("entry") in ENTRY else None)
    sides = f.get("sides") or {}
    corroborated = p >= SEVERAL_PEOPLE or (p >= 2 and len(langs) >= 2)
    notes = []
    if not kind:
        notes.append("no_change_vs_usual")
    if len(langs) <= 1:
        notes.append("single_language")
    if sides and min(sides.get("for", 0), sides.get("against", 0)) < 2:
        notes.append("split_few_each_side")   # 意見の分かれ方の片側が 1 人: 片側だけを見出しにしない（両側を並べて書く）
    a = {"people": p, "voices": voices, "share": round(p / voices, 2) if voices else None, "languages": langs,
         "change": {k: ch.get(k) for k in ("kind", "n", "base", "ratio", "streak", "new_langs", "entry", "prev")} if ch else None,
         "change_notable": bool(kind), "change_kind": kind, "sources": list(whole.get("sources") or []), "sides": sides or None,
         "other_sources": {s: {k: c.get(k) for k in ("kind", "n", "base")} for s, c in (whole.get("by_source") or {}).items() if s != source},
         "corroborated": corroborated, "claim": claim_level(p, voices), "notes": notes}
    if f.get("page") == "spread":
        added = {x["code"] for x in f.get("added") or []}
        a["voices_new_area"] = bool(set(langs) & added)
        a["tier"] = 1 if a["voices_new_area"] else (2 if p >= SEVERAL_PEOPLE else 3)
    else:
        a["tier"] = 1 if kind and corroborated else (2 if kind else (3 if corroborated else 4))
    return a


DASHBOARD_MAX_TIER = 3   # ダッシュボードの今日の兆しにするのは段階 3 まで（変化がなく 2 人・1 つの言語の声はサイトの最上部の発見にしない。§0.6-6）


def eligible(f: dict) -> bool:
    return f.get("page") == "spread" or f["assessment"]["tier"] <= DASHBOARD_MAX_TIER


def order_key(f: dict) -> tuple:
    a = f["assessment"]
    ch = a.get("change") or {}
    if f.get("page") == "spread":
        return (a["tier"], -sum(x.get("people") or 0 for x in f.get("added") or []), -a["people"], KIND_ORDER.get(f.get("kind"), 3), f["works"][0]["ja"] or "")
    return (a["tier"], -a["people"], -(ch.get("ratio") or 0), KIND_ORDER.get(f.get("kind"), 3), f["works"][0]["ja"] or "")


TIER_REASON = {
    "dashboard": {1: "作品に普段と違う動きがあり、その中身を複数の独立したプレイヤーが裏付けている",
                  2: "作品に普段と違う動きがあり、その中で語られていること（個々のプレイヤーの声）",
                  3: "作品の動きは普段どおりだが、複数の独立したプレイヤー・言語圏で同じ具体的な点が語られている",
                  4: "作品の動きは普段どおりで、2 人のプレイヤーの声（規模をそのまま書く）"},
    "spread": {1: "新しく加わった言語圏のプレイヤー自身が語っている", 2: "加わった言語圏の作品について、複数のプレイヤーが同じ点を語っている",
               3: "加わった言語圏の作品について、2 人のプレイヤーが同じ点を語っている"},
}


def explain(f: dict) -> str:
    return TIER_REASON.get(f.get("page") or "dashboard", TIER_REASON["dashboard"])[f["assessment"]["tier"]]
