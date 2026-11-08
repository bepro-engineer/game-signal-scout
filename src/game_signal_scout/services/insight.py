"""プレイヤーの発見（AI の読み取り。#2: 「世界で広がる作品」の置き換え）。

作品ごとに、世界のプレイヤーの発言から「何をした → 何が起きた → 面白い／不満 → ほかの人も同じか → 前と比べてどう変わったか」を根拠つきで取り出す。
件数はこちらで数え、LLM は読むことと、同じ体験をまとめることだけをする（Anime の theme_engine と同じ分担）。データにない発見は作らない。

1. 読む: 直近 window_days × 2 日の発言から、投稿者ごとに 1 件（宣伝などの印のあるもの・短いものは除く）。LLM が 1 件ずつ、具体的な体験
   （did・happened・verdict・topic）か、体験でない（null）かを返す。読んだ結果は発言ごとに残し（body.reads）、次の回は新しい発言だけを読む。
2. まとめる: 体験の一覧を LLM に渡し、同じ具体的な体験（同じことをして同じことが起きた）をまとめさせる。番号は読んだものだけを使う。
3. 数える: まとめごとに、直近の窓（window_days）と前の窓の、独立した投稿者の数・言語・面白い／不満の内訳をこちらで数える。
   直近の窓で min_people 人（既定 2）以上のものを発見とする。人数は確からしさの目安で、面白さの保証ではない。反対の声の人数も添える。
   まだ重ならない「ひとりの体験」も、そう明記して作品ごとに数件残す（2 人でも 1 人でも具体的な体験は読者の判断材料になる。#2 6723365999）。
   遊び方（style: ひとりで・協力・対戦）と入力（コントローラー）は固定の分類ではなく、体験に付く観点。発言から言えるときだけ付ける。
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
STYLES = ("solo", "coop", "versus")       # その体験をどう遊んでいたか（ひとりで・協力して・対戦で）。発言から言えるときだけ
INPUTS = ("controller",)                  # 体験が入力機器の操作感についてのとき
CAUTIONS = ("time", "price", "performance", "bugs", "difficulty", "online")
KANA = re.compile(r"[\u3040-\u30ff]")
HANZI_ONLY = re.compile(r"[遇到们这个吗么还没为说时会对过進數膨脹遊後變們這個麼還說時會對過]")   # 日本語では使わない簡体字・中国語の語

READ_PROMPT = """ゲーム「{title}」のプレイヤーの発言を 1 件ずつ読んでください。発言が「自分が実際に遊んで、何をして、何が起きたか」を具体的に書いているときだけ、それを取り出します。
感想だけ・ニュース・質問・宣伝・抽象的な評価だけのものは null にします。発言にないことは書かないでください。
did は、ゲームの中の具体的な行動・場面・遊び方（例: 大剣で溜め攻撃を連発した・2 人で拠点を守った・設定で影を切った）。「プレイした」「遊んだ」「始めた」のような中身のない行動なら null。
happened は、その結果ゲームの中で具体的に起きたこと（例: ボスを 1 回で倒せた・味方と連携できた・フレームレートが倍になった）。「楽しかった」「良かった」だけなら null。
style は、その体験をどう遊んでいたときのものか（発言に書いてあるときだけ。言えなければ none）: solo（ひとりで）/ coop（ほかの人と協力して）/ versus（ほかの人と対戦して）/ none
input は、体験がコントローラーの操作感・使い勝手についてのとき controller、それ以外は none
caution は、買う・遊ぶ前に知っておくべき注意（発言に書いてあるときだけ）: time（時間がかかる）/ price（価格・課金）/ performance（重い・動作）/ bugs（不具合）/ difficulty（難しさ）/ online（接続・人がいない・不正）/ none
各発言について次の JSON を返します: {{"id": 番号, "exp": null または {{"did": "プレイヤーがしたこと（日本語 30 字以内）", "happened": "その結果起きたこと（日本語 40 字以内）", "verdict": "fun（面白い・良かった）/ frustration（不満・困った）/ mixed", "topic": "体験の話題を表す短い日本語（15 字以内）", "style": "solo / coop / versus / none", "input": "controller / none", "caution": "time / price / performance / bugs / difficulty / online / none"}}}}
次の形の JSON だけを返してください（前置き不要）: {{"items": [各発言の JSON, ...]}}

発言:
{lines}"""

GROUP_PROMPT = """ゲーム「{title}」のプレイヤーの体験の一覧です。同じ具体的な体験（同じことをして、同じことが起きた）を書いているものをまとめてください。
言い換えでも中身が同じならまとめ、中身が違えば分けます。まとまらないものは入れなくてよいです。番号は一覧にあるものだけを使います。
title は、一覧にある具体的な行動と結果をそのまま使って書きます（例:「斬馬刀でボスに挑むと、ほぼ一方的に押し切れる」「ボス戦の途中で強制終了し、進行が消える」）。
「〜を評価する」「〜を感じる」「〜に満足」のような抽象的な言い方にしないでください。一覧にないことは足さないでください。
fits は、一覧の体験そのものから言える「この体験が向いている人」（例: 自力で攻略したい人・決まった仲間と遊べる人）。一覧から言えなければ空にします。
次の形の JSON だけを返してください（前置き不要）: {{"groups": [{{"title": "まとめた体験を 1 文で（「〜すると、〜」の形。日本語 50 字以内）", "fits": "向いている人（日本語 25 字以内。言えなければ空）", "ids": [番号, ...]}}]}}

一覧:
{items}"""


def _json_array(text: str) -> list:
    try:
        v = json.loads(text[text.find("["):text.rfind("]") + 1])
        return v if isinstance(v, list) else []
    except (ValueError, TypeError):
        return []


ABSTRACT = re.compile(r"(を|に)(評価する|感じる|満足する|満足した|感じた)。?$")   # 具体的な体験でない見出し
VAGUE = re.compile(r"^(ゲームを)?(プレイ|遊|始め|購入|買|触|やっ)[^、。]{0,6}$|^(ゲーム|本作|この作品)を(プレイ|遊)")   # 中身のない行動


def _clean_exp(e) -> dict | None:
    if not isinstance(e, dict):
        return None
    v = str(e.get("verdict") or "").strip()
    out = {k: str(e.get(k) or "").strip()[:60] for k in ("did", "happened", "topic")}
    if not out["did"] or not out["happened"] or v not in VERDICTS or VAGUE.search(out["did"]):
        return None
    if any(not KANA.search(out[k]) or HANZI_ONLY.search(out[k]) for k in ("did", "happened")):   # 日本語でない（訳されていない）体験は使わない
        return None
    sy, ip, ca = (str(e.get(k) or "").strip() for k in ("style", "input", "caution"))
    return {**out, "verdict": v, "style": sy if sy in STYLES else None, "input": ip if ip in INPUTS else None, "caution": ca if ca in CAUTIONS else None}


def read_statements(ask, title: str, rows: list[dict]) -> dict[str, dict | None]:
    """発言（item_id・lang・text）を READ_BATCH 件ずつ読む。item_id → 体験（なければ None）。読めなかった束は返さない（次の回に読み直す）。"""
    out: dict[str, dict | None] = {}
    for i in range(0, len(rows), READ_BATCH):
        b = rows[i:i + READ_BATCH]
        lines = "\n".join(f"[{j}] ({r.get('lang') or '?'}) {str(r['text'])[:TEXT_CHARS]}" for j, r in enumerate(b))
        try:
            arr = _json_array(ask(READ_PROMPT.format(title=title, lines=lines)))
        except Exception:  # noqa: BLE001 — 共有の LLM の一時的な失敗: この束だけ次の回に読み直す（読めた束は残す）
            arr = []
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
        if not KANA.search(str(g["title"])) or HANZI_ONLY.search(str(g["title"])) or ABSTRACT.search(str(g["title"])):   # 日本語でない文・抽象的な文は出さない
            continue
        ids = sorted({int(i) for i in g.get("ids") or [] if str(i).isdigit() and int(i) < len(exps)})
        fits = str(g.get("fits") or "").strip()[:40]
        if fits and (not KANA.search(fits) or HANZI_ONLY.search(fits)):
            fits = ""
        if ids:
            out.append({"title": str(g["title"]).strip()[:80], "fits": fits, "members": [exps[i][0] for i in ids]})
    return out


def _major(cur: list[str], exps: dict[str, dict], key: str):
    """まとまりの過半の人が同じものを示したときだけ、その値（こちらで数える）。"""
    c = Counter(exps[m].get(key) for m in cur if exps[m].get(key))
    return next((k for k, n in c.most_common(1) if n * 2 > len(cur)), None)


def _verdict(v: Counter) -> str:
    return "fun" if v["fun"] > (v["frustration"] + v["mixed"]) else "frustration" if v["frustration"] > (v["fun"] + v["mixed"]) else "mixed"


def tally(groups: list[dict], posts: dict[str, dict], exps: dict[str, dict], since, min_people: int) -> list[dict]:
    """まとめごとに、直近の窓（at >= since）と前の窓の独立した投稿者を数える。数・内訳はこちらで数え、LLM の数は使わない。
    人数は確からしさの目安として添えるだけ（多い＝正しい・面白い、ではない）。反対の声（面白い ↔ 不満）の人数も必ず添える。"""
    finds = []
    for g in groups:
        cur = [m for m in g["members"] if posts[m]["at"] >= since]
        prev = [m for m in g["members"] if posts[m]["at"] < since]
        people, before = len({posts[m]["author"] for m in cur}), len({posts[m]["author"] for m in prev})
        if people < min_people:
            continue
        v = Counter(exps[m]["verdict"] for m in cur)
        trend = "new" if before == 0 else "up" if people >= before * 1.5 else "down" if people * 1.5 <= before else "same"
        finds.append({"title": g["title"], "fits": g.get("fits") or "", "verdict": _verdict(v), "people": people, "prev": before, "trend": trend,
                      "style": _major(cur, exps, "style"), "input": _major(cur, exps, "input"), "caution": _major(cur, exps, "caution"),
                      "fun": v["fun"], "frustration": v["frustration"], "mixed": v["mixed"],
                      "langs": [lg for lg, _ in Counter(posts[m]["lang"] for m in cur if posts[m]["lang"]).most_common()],
                      "examples": [{"did": exps[m]["did"], "happened": exps[m]["happened"], "verdict": exps[m]["verdict"]} for m in cur[:3]]})
    return sorted(finds, key=lambda f: (-f["people"], f["title"]))


def singles(posts: dict[str, dict], exps: dict[str, dict], finds_members: set[str], since, limit: int = 6) -> list[dict]:
    """まだほかの人の声と重ならない、ひとりの具体的な体験（直近の窓）。発見ではなく「ひとりの体験」として、そう明記して出す。"""
    out = [{"did": e["did"], "happened": e["happened"], "verdict": e["verdict"], "topic": e["topic"], "style": e.get("style"), "input": e.get("input"),
            "caution": e.get("caution"), "lang": posts[k]["lang"]}
           for k, e in sorted(exps.items(), key=lambda kv: posts[kv[0]]["at"], reverse=True) if k not in finds_members and posts[k]["at"] >= since]
    return out[:limit]


def input_hash(rows: list[dict]) -> str:
    return hashlib.sha256("|".join(sorted(r["item_id"] for r in rows)).encode()).hexdigest()[:16]


def read_game(conn, appid: str, title: str, model: str, cfg: dict, prev_body: dict | None = None, ask=None) -> dict | None:
    """作品 1 つの発見。prev_body（前の回の body）の reads を使い、新しい発言だけを読む。"""
    from game_signal_scout.repositories import insight as repo
    days = int(cfg.get("window_days", 7))
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    from game_signal_scout import observations
    srcs = list(observations.sources())   # 集計に入れている取得元（有効で、利用条件で止まっていないもの。保留・停止の取得元の保存済みの発言は使わない）
    rows = repo.statements_by_author(conn, appid, days * 2, int(cfg.get("max_per_window", 60)), since, srcs)
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
    mp = int(cfg.get("min_people", 2))
    finds = tally(groups, posts, exps, since, mp)
    kept = {f["title"] for f in finds}
    members = {m for g in groups if g["title"] in kept for m in g["members"]}
    n_cur = len({r["author"] for r in rows if r["at"] >= since and r["item_id"] in reads})
    cur_exps = sum(1 for k in exps if posts[k]["at"] >= since)
    # 段ごとの件数（#2: どの段で減ったかを確かめられるように）
    stages = {"statements": len(rows), "statements_recent": sum(1 for r in rows if r["at"] >= since), "read_now": len(todo), "read": len(reads),
              "experiences": len(exps), "experiences_recent": cur_exps, "groups": len(groups), "below_min_people": len(groups) - len(finds), "finds": len(finds)}
    return {"appid": appid, "generated_at": now, "model": model, "input_hash": input_hash(rows),
            "body": {"kind": KIND, "window_days": days, "since": since.isoformat(), "read_people": n_cur, "min_people": mp,
                     "experiences": cur_exps, "finds": finds, "singles": singles(posts, exps, members, since), "stages": stages, "reads": reads}}


def phenomena(body: dict, ranked: bool) -> list[str]:
    """古い公開の文書（publication/content）の互換: 発見の見出し。"""
    return [f["title"] for f in (body or {}).get("finds") or []][: 3 if ranked else 5]
