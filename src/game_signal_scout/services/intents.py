"""遊びたい体験の入口（#2 2026-11-11 オーナーの確定指示。承認済みの方針 6722785883「次に遊びたいゲームを発見する」）。

入口は 4 つ: じっくり没頭したい（deep）・短時間で楽しみたい（short）・新しい体験がしたい（novel）・友達と遊びたい（friends）。
作品を選ぶ根拠は、プレイヤーの体験の読み取り（services/insight）にある「実際に遊んだ人の体験」だけ。ジャンル・ストアの遊び方の表示・
タグを固定で割り当てて選ばない（ストアの遊び方の表示は、友達と遊びたいの入口で「できること」として添えるだけ）。

- deep: 醍醐味が 探索（explore）・物語（story）・育成とやり込み（grow）の体験
- short: 1 回に遊ぶ時間が短い（session = short）と書いた体験（2026-11-11 から読み取る。前に読んだ発言にはない）
- novel: 醍醐味が 予想外が起きる面白さ（surprise）の体験
- friends: 醍醐味が 仲間との連携（team）・相手との駆け引き（versus）の体験か、協力・対戦で遊んだ（style）体験
いずれも不満（frustration）の体験は根拠にしない。作品ごとに、根拠の体験（書いた人の数つき）・注意（不満の体験と、注意の印の人数）・
向いている人（読み取りのまとまりにあるときだけ）を返す。根拠がない入口は空のまま返し、ほかの作品で埋めない。
"""
from __future__ import annotations

from collections import Counter

INTENTS = ("deep", "short", "novel", "friends")
RULES = {
    "deep": {"kinds": {"explore", "story", "grow"}},
    "short": {"sessions": {"short"}},
    "novel": {"kinds": {"surprise"}},
    "friends": {"kinds": {"team", "versus"}, "styles": {"coop", "versus"}},
}
MAX_WHY = 3
MAX_WARN = 2


def matches(intent: str, x: dict) -> bool:
    """体験 x がその入口の根拠になるか（不満の体験は根拠にしない）。"""
    if x.get("verdict") == "frustration":
        return False
    r = RULES[intent]
    if x.get("kind") in r.get("kinds", ()):          # 醍醐味（面白さの核心）がその体験: 賛否の混じる体験も根拠にする（醍醐味は面白さが書かれたときだけ付く）
        return True
    # 遊び方・1 回の時間だけが合う体験は、面白かった（fun）ときだけ根拠にする（例: 協力で遊んだが味方が無反応だった、は根拠にしない）
    return x.get("verdict") == "fun" and (x.get("style") in r.get("styles", ()) or x.get("session") in r.get("sessions", ()))


def long_voices(xs: list[dict]) -> int:
    """1 回に時間がかかる・長いと書いた人の数（短時間で楽しみたい人への注意）。"""
    return sum(x.get("people") or 1 for x in xs if x.get("session") == "long" or x.get("caution") == "time")


def select(works: dict[int, dict]) -> dict[str, list[dict]]:
    """works: 作品 → {"xs": 体験の一覧, ...}（signal/content.work_finds の形）。入口 → [{work, why, why_people, warn, cautions, fits, long}]。
    並びは根拠の体験を書いた人の多い順（同じなら作品の番号）。"""
    out: dict[str, list[dict]] = {k: [] for k in INTENTS}
    for w, wf in works.items():
        xs = wf.get("xs") or []
        warn = sorted([x for x in xs if x.get("verdict") == "frustration"], key=lambda x: -(x.get("people") or 1))[:MAX_WARN]
        cautions = Counter()
        for x in xs:
            if x.get("caution"):
                cautions[x["caution"]] += x.get("people") or 1
        for k in INTENTS:
            why = sorted([x for x in xs if matches(k, x)], key=lambda x: -(x.get("people") or 1))
            if not why:
                continue
            out[k].append({"work": w, "why": why[:MAX_WHY], "why_people": sum(x.get("people") or 1 for x in why), "why_n": len(why),
                           "warn": warn, "cautions": dict(cautions.most_common()), "fits": next((x["fits"] for x in why if x.get("fits")), ""),
                           "long": long_voices(xs)})
    for k in INTENTS:
        out[k].sort(key=lambda it: (-it["why_people"], it["work"]))
    return out


DIVIDED_MIN = 2   # 面白いと書いた人・不満を書いた人が、どちらもこの数以上の作品だけ（ひとりずつの声では「分かれる」と言わない）


def divided(works: dict[int, dict]) -> list[dict]:
    """賛否が分かれる作品（#2 2026-11-11 オーナーの左メニューの候補。実データで成立を確かめて採用）: 同じ作品で、面白いと書いた人と
    不満を書いた人がどちらも DIVIDED_MIN 人以上。人数はこちらで数えた体験の人数（面白い体験の反対の声も不満に数える）。賛否の混じる体験（mixed）は数えない。
    返り値: [{work, fun, against, fun_xs, against_xs}]（両方の声の少ない側が多い順＝より割れている順）。"""
    out = []
    for w, wf in works.items():
        xs = wf.get("xs") or []
        fun_xs = sorted([x for x in xs if x.get("verdict") == "fun"], key=lambda x: -(x.get("people") or 1))
        bad_xs = sorted([x for x in xs if x.get("verdict") == "frustration"], key=lambda x: -(x.get("people") or 1))
        fun = sum(x.get("people") or 1 for x in fun_xs)
        bad = sum(x.get("people") or 1 for x in bad_xs) + sum(x.get("against") or 0 for x in fun_xs)
        if fun >= DIVIDED_MIN and bad >= DIVIDED_MIN and bad_xs:
            out.append({"work": w, "fun": fun, "against": bad, "fun_xs": fun_xs[:MAX_WHY], "against_xs": bad_xs[:MAX_WHY]})
    return sorted(out, key=lambda it: (-min(it["fun"], it["against"]), -(it["fun"] + it["against"]), it["work"]))
