"""プレイヤーの発見（AI の読み取り。#2: 「世界で広がる作品」の置き換え）。

作品ごとに、世界のプレイヤーの発言から「何をした → 何が起きた → 面白い／不満 → ほかの人も同じか → 前と比べてどう変わったか」を根拠つきで取り出す。
件数はこちらで数え、LLM は読むことと、同じ体験をまとめることだけをする（Anime の theme_engine と同じ分担）。データにない発見は作らない。

1. 読む: 直近 window_days × 2 日の発言から、投稿者ごとに 1 件（宣伝などの印のあるもの・短いものは除く）。LLM が 1 件ずつ、具体的な体験
   （did・happened・verdict・topic）か、体験でない（null）かを返す。読んだ結果は発言ごとに残し（body.reads）、次の回は新しい発言だけを読む。
2. まとめる: 体験の一覧を LLM に渡し、同じ具体的な体験（同じことをして同じことが起きた）をまとめさせる。番号は読んだものだけを使う。
3. 数える: まとめごとに、直近の窓（window_days）と前の窓の、独立した投稿者の数・言語・面白い／不満の内訳をこちらで数える。
   直近の窓で min_people 人以上のものだけを発見とする。前の窓との比較: new（前は 0）・up・same・down。
結果は game_insight（作品ごとに 1 行。材料の hash が同じなら作り直さない）。共有の LLM は llm.chat（共有の枠）だけを通す。
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone

KIND = "finds"
READ_BATCH = 6
TEXT_CHARS = 500
VERDICTS = ("fun", "frustration", "mixed")
KANA = re.compile(r"[\u3040-\u30ff]")
HANZI_ONLY = re.compile(r"[遇到们这个吗么还没为说时会对过]")   # 日本語では使わない簡体字・中国語の語

READ_PROMPT = """ゲーム「{title}」のプレイヤーの発言を 1 件ずつ読んでください。発言が「自分が実際に遊んで、何をして、何が起きたか」を具体的に書いているときだけ、それを取り出します。
感想だけ・ニュース・質問・宣伝・抽象的な評価だけのものは null にします。発言にないことは書かないでください。
did は、ゲームの中の具体的な行動・場面・遊び方（例: 大剣で溜め攻撃を連発した・2 人で拠点を守った・設定で影を切った）。「プレイした」「遊んだ」「始めた」のような中身のない行動なら null。
happened は、その結果ゲームの中で具体的に起きたこと（例: ボスを 1 回で倒せた・味方と連携できた・フレームレートが倍になった）。「楽しかった」「良かった」だけなら null。
各発言について次の JSON を返します: {{"id": 番号, "exp": null または {{"did": "プレイヤーがしたこと（日本語 30 字以内）", "happened": "その結果起きたこと（日本語 40 字以内）", "verdict": "fun（面白い・良かった）/ frustration（不満・困った）/ mixed", "topic": "体験の話題を表す短い日本語（15 字以内）"}}}}
次の形の JSON だけを返してください（前置き不要）: {{"items": [各発言の JSON, ...]}}

発言:
{lines}"""

GROUP_PROMPT = """ゲーム「{title}」のプレイヤーの体験の一覧です。同じ具体的な体験（同じことをして、同じことが起きた）を書いているものをまとめてください。
言い換えでも中身が同じならまとめ、中身が違えば分けます。まとまらないものは入れなくてよいです。番号は一覧にあるものだけを使います。
次の形の JSON だけを返してください（前置き不要）: {{"groups": [{{"title": "まとめた体験を 1 文で（「〜すると〜」の形。日本語 50 字以内。一覧にないことを足さない）", "ids": [番号, ...]}}]}}

一覧:
{items}"""


def _json_array(text: str) -> list:
    try:
        v = json.loads(text[text.find("["):text.rfind("]") + 1])
        return v if isinstance(v, list) else []
    except (ValueError, TypeError):
        return []


VAGUE = re.compile(r"^(ゲームを)?(プレイ|遊|始め|購入|買|触|やっ)[^、。]{0,6}$|^(ゲーム|本作|この作品)を(プレイ|遊)")   # 中身のない行動


def _clean_exp(e) -> dict | None:
    if not isinstance(e, dict):
        return None
    v = str(e.get("verdict") or "").strip()
    out = {k: str(e.get(k) or "").strip()[:60] for k in ("did", "happened", "topic")}
    if not out["did"] or not out["happened"] or v not in VERDICTS or VAGUE.search(out["did"]):
        return None
    return {**out, "verdict": v}


def read_statements(ask, title: str, rows: list[dict]) -> dict[str, dict | None]:
    """発言（item_id・lang・text）を READ_BATCH 件ずつ読む。item_id → 体験（なければ None）。読めなかった束は返さない（次の回に読み直す）。"""
    out: dict[str, dict | None] = {}
    for i in range(0, len(rows), READ_BATCH):
        b = rows[i:i + READ_BATCH]
        lines = "\n".join(f"[{j}] ({r.get('lang') or '?'}) {str(r['text'])[:TEXT_CHARS]}" for j, r in enumerate(b))
        arr = _json_array(ask(READ_PROMPT.format(title=title, lines=lines)))
        if not arr:
            continue
        got = {int(x["id"]): x.get("exp") for x in arr if isinstance(x, dict) and str(x.get("id", "")).isdigit()}
        for j, r in enumerate(b):
            out[r["item_id"]] = _clean_exp(got.get(j))
    return out


def group(ask, title: str, exps: list[tuple[str, dict]]) -> list[dict]:
    """体験（item_id, exp）をまとめる。返り値: [{title, members: [item_id]}]（番号は一覧にあるものだけ）。"""
    if len(exps) < 2:
        return []
    items = "\n".join(f"[{i}] {e['topic']} / {e['did']} → {e['happened']}" for i, (_, e) in enumerate(exps))
    out = []
    for g in _json_array(ask(GROUP_PROMPT.format(title=title, items=items))):
        if not isinstance(g, dict) or not str(g.get("title") or "").strip():
            continue
        if not KANA.search(str(g["title"])) or HANZI_ONLY.search(str(g["title"])):   # 日本語でない文（中国語の混ざり）は出さない
            continue
        ids = sorted({int(i) for i in g.get("ids") or [] if str(i).isdigit() and int(i) < len(exps)})
        if ids:
            out.append({"title": str(g["title"]).strip()[:80], "members": [exps[i][0] for i in ids]})
    return out


def tally(groups: list[dict], posts: dict[str, dict], exps: dict[str, dict], since, min_people: int) -> list[dict]:
    """まとめごとに、直近の窓（at >= since）と前の窓の独立した投稿者を数える。数・内訳はこちらで数え、LLM の数は使わない。"""
    finds = []
    for g in groups:
        cur = [m for m in g["members"] if posts[m]["at"] >= since]
        prev = [m for m in g["members"] if posts[m]["at"] < since]
        people, before = len({posts[m]["author"] for m in cur}), len({posts[m]["author"] for m in prev})
        if people < min_people:
            continue
        v = Counter(exps[m]["verdict"] for m in cur)
        verdict = "fun" if v["fun"] > (v["frustration"] + v["mixed"]) else "frustration" if v["frustration"] > (v["fun"] + v["mixed"]) else "mixed"
        trend = "new" if before == 0 else "up" if people >= before * 1.5 else "down" if people * 1.5 <= before else "same"
        finds.append({"title": g["title"], "verdict": verdict, "people": people, "prev": before, "trend": trend,
                      "fun": v["fun"], "frustration": v["frustration"], "mixed": v["mixed"],
                      "langs": [lg for lg, _ in Counter(posts[m]["lang"] for m in cur if posts[m]["lang"]).most_common()],
                      "examples": [{"did": exps[m]["did"], "happened": exps[m]["happened"]} for m in cur[:3]]})
    return sorted(finds, key=lambda f: (-f["people"], f["title"]))


def input_hash(rows: list[dict]) -> str:
    return hashlib.sha256("|".join(sorted(r["item_id"] for r in rows)).encode()).hexdigest()[:16]


def read_game(conn, appid: str, title: str, model: str, cfg: dict, prev_body: dict | None = None, ask=None) -> dict | None:
    """作品 1 つの発見。prev_body（前の回の body）の reads を使い、新しい発言だけを読む。"""
    from game_signal_scout.repositories import insight as repo
    days = int(cfg.get("window_days", 7))
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    rows = repo.statements_by_author(conn, appid, days * 2, int(cfg.get("max_per_window", 60)), since)
    if not rows:
        return None
    if ask is None:
        from game_signal_scout import llm
        ask = lambda p: llm.chat(model, "", p, format="json", think=False, options={"temperature": 0.1, "num_ctx": 8192, "num_predict": 2048}, timeout=float(cfg.get("timeout_seconds", 1800))).content
    reads = {k: v for k, v in ((prev_body or {}).get("reads") or {}).items() if k in {r["item_id"] for r in rows}}
    todo = [r for r in rows if r["item_id"] not in reads][: int(cfg.get("max_reads_per_run", 60))]
    reads.update(read_statements(ask, title, todo))
    posts = {r["item_id"]: r for r in rows}
    exps = {k: v for k, v in reads.items() if v and k in posts}
    groups = group(ask, title, sorted(exps.items(), key=lambda kv: posts[kv[0]]["at"]))
    finds = tally(groups, posts, exps, since, int(cfg.get("min_people", 3)))
    n_cur = len({r["author"] for r in rows if r["at"] >= since and r["item_id"] in reads})
    return {"appid": appid, "generated_at": now, "model": model, "input_hash": input_hash(rows),
            "body": {"kind": KIND, "window_days": days, "since": since.isoformat(), "read_people": n_cur,
                     "experiences": sum(1 for k in exps if posts[k]["at"] >= since), "finds": finds, "reads": reads}}


def phenomena(body: dict, ranked: bool) -> list[str]:
    """古い公開の文書（publication/content）の互換: 発見の見出し。"""
    return [f["title"] for f in (body or {}).get("finds") or []][: 3 if ranked else 5]
