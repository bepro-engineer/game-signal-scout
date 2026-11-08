"""作品ごとの「プレイヤーの声の読み取り」（AI。Anime の theme_engine と同じく、件数はこちらで数え、LLM は読むことと言葉にすることだけをする）。

1. 読む: 最近のプレイヤーの発言（取得元に依らない player_post。宣伝などの印のあるものは除く）を、肯定・否定をなるべく半々に最大 MAX_INPUTS 件選ぶ。
   LLM が 1 件ずつ「何について（ASPECTS）・良いか悪いか・日本語の短い要点」を返す（BATCH 件ずつ）。
2. 数える: 観点 × 良い／悪い の件数を、こちらで数える（LLM の書いた数は使わない）。
3. 書く: 数えた表と要点を LLM に渡し、見出し・期待できる体験・合う人・合わない人を日本語で書かせる（数は表の数だけを使わせる）。
結果は game_insight（作品ごとに 1 行。材料の hash が同じなら作り直さない）。共有の Ollama は共有の枠 scout-llm を通す。
"""
from __future__ import annotations

import base64
import hashlib
import json
import subprocess
from collections import defaultdict
from datetime import datetime, timezone

MAX_INPUTS = 40
BATCH = 10
TEXT_CHARS = 260
MIN_SUPPORT = 2
CLI = "/Users/Shared/scout-infra/bin/scout-llm"

ASPECTS = {"fun": "遊びの面白さ", "combat": "戦闘・操作の手触り", "story": "物語・世界観", "visual": "映像・音", "volume": "ボリューム・やり込み",
           "difficulty": "難しさ", "perf": "動作の重さ・最適化", "bugs": "不具合・落ちる", "online": "オンライン・マッチング", "friends": "仲間と遊ぶ",
           "solo": "一人で遊ぶ", "time": "遊ぶ時間", "price": "価格・課金", "update": "更新・運営", "other": "その他"}

READ_PROMPT = """ゲーム「{title}」についてのプレイヤーの発言を 1 件ずつ読み、それぞれについて次を返してください。
- aspect: 主に何について書いているか。次の鍵から 1 つ: {aspects}
- stance: その点を良いと書いているなら good、悪いと書いているなら bad、どちらでもなければ neutral
- note: 書いていることの要点を、日本語だけで 25 字以内（中国語・英語を混ぜない。発言にないことは書かない）

次の JSON の配列だけを返してください（前置き不要）: [{{"id": 番号, "aspect": "鍵", "stance": "good", "note": "要点"}}, ...]

発言:
{lines}
"""

WRITE_PROMPT = """あなたはゲームの情報サイトの編集者です。読者は仕事で自由な時間が少なく、週末に遊ぶゲームを選んでいます。
ゲーム「{title}」について、最近のプレイヤーの発言 {n} 件を AI が 1 件ずつ読み、何について・良いか悪いかを数えた表が下にあります。
この表と要点だけを使い、日本語だけで（中国語・英語を混ぜない）、読者が数十秒で判断できる文を書いてください。数を書くときは表の数だけを使ってください。

表（観点: 良いと書いた人数 / 悪いと書いた人数 / 要点の例）:
{table}

次の JSON だけを返してください（前置き不要）:
{{"headline": "いまプレイヤーが最も多く書いていることを 1 文で。人数を入れる（例:『{title}』では、N 人のプレイヤーが〜と書いています。）",
 "experience": "このゲームで期待できる体験を 1〜2 文で",
 "fits": ["合う人（表から言えること。1〜3 個）"],
 "not_fits": ["合わないかもしれない人（表から言えること。1〜3 個）"]}}
"""


def pick(rows: list[dict]) -> list[dict]:
    """肯定・否定をなるべく半々に、長い発言を優先して選ぶ。"""
    pos = sorted([r for r in rows if r["stance"] == "positive"], key=lambda r: -len(r["text"]))
    neg = sorted([r for r in rows if r["stance"] == "negative"], key=lambda r: -len(r["text"]))
    other = sorted([r for r in rows if r["stance"] is None], key=lambda r: -len(r["text"]))
    out = neg[:MAX_INPUTS // 2]
    out += pos[:MAX_INPUTS - len(out) - min(len(other), 6)]
    out += other[:MAX_INPUTS - len(out)]
    return out[:MAX_INPUTS]


def ask_llm(text: str, model: str, owner: str, timeout: int = 600) -> str:
    """共有の枠を通して 1 回の推論（scout-llm chat。終了コードはいつも 0 で、結果は JSON）。"""
    r = subprocess.run([CLI, "chat", "--owner", owner, "--model", model, "--prompt-b64", base64.b64encode(text.encode()).decode(),
                        "--temperature", "0.1", "--num-ctx", "8192", "--timeout", str(timeout)], capture_output=True, text=True, timeout=timeout + 120)
    out = json.loads(r.stdout or "{}")
    if not out.get("ok"):
        raise RuntimeError(f"LLM の失敗: {str(out.get('error'))[:200]}")
    return out["content"]


def _json(content: str, opener: str, closer: str):
    return json.loads(content[content.find(opener):content.rfind(closer) + 1])


def read_batch(title: str, batch: list[tuple[int, dict]], model: str, owner: str) -> dict[int, dict]:
    """発言を 1 件ずつ読む（観点・良い悪い・要点）。形の崩れた答えは捨てる（その発言は数えない）。"""
    lines = "\n".join(f"{i}. {' '.join(r['text'].split())[:TEXT_CHARS]}" for i, r in batch)
    got = _json(ask_llm(READ_PROMPT.format(title=title, aspects=", ".join(ASPECTS), lines=lines), model, owner), "[", "]")
    ids = {i for i, _ in batch}
    out = {}
    for x in got if isinstance(got, list) else []:
        if not isinstance(x, dict):
            continue
        try:
            i = int(x.get("id"))
        except (TypeError, ValueError):
            continue
        if i in ids and x.get("aspect") in ASPECTS and x.get("stance") in ("good", "bad", "neutral"):
            out[i] = {"aspect": x["aspect"], "stance": x["stance"], "note": str(x.get("note") or "").strip()[:40]}
    return out


def tally(reads: dict[int, dict]) -> dict[str, dict]:
    """観点ごとの良い・悪いの件数と、根拠の番号（こちらで数える）。"""
    t: dict[str, dict] = defaultdict(lambda: {"good": [], "bad": []})
    for i, x in reads.items():
        if x["stance"] in ("good", "bad") and x["aspect"] != "other":
            t[x["aspect"]][x["stance"]].append(i)
    return dict(t)


def table_text(t: dict, reads: dict) -> str:
    rows = sorted(t.items(), key=lambda kv: -(len(kv[1]["good"]) + len(kv[1]["bad"])))
    out = []
    for k, v in rows:
        notes = [reads[i]["note"] for i in (v["good"][:2] + v["bad"][:2]) if reads[i]["note"]]
        out.append(f"- {ASPECTS[k]}: {len(v['good'])} / {len(v['bad'])} / {'、'.join(notes)}")
    return "\n".join(out)


def points(t: dict, reads: dict, side: str) -> list[dict]:
    """良い（side=good）・悪い（bad）の観点を、人数の多い順に（MIN_SUPPORT 人以上）。要点は根拠の発言の要点から。"""
    xs = [(k, v[side]) for k, v in t.items() if len(v[side]) >= MIN_SUPPORT]
    xs.sort(key=lambda kv: -len(kv[1]))
    return [{"aspect": k, "label": ASPECTS[k], "ids": ids, "notes": list(dict.fromkeys(reads[i]["note"] for i in ids if reads[i]["note"]))[:3]}
            for k, ids in xs[:5]]


def input_hash(inputs: list[dict]) -> str:
    return hashlib.sha256("|".join(f"{r['source']}:{r['item_id']}" for r in inputs).encode()).hexdigest()[:16]


def read_game(conn, appid: str, title: str, model: str, days: int) -> dict | None:
    """1 作品の読み取り（材料が少なすぎれば None）。"""
    from game_signal_scout.repositories import insight as repo
    rows = repo.statements(conn, appid, days)
    inputs = pick(rows)
    if len(inputs) < 10:
        return None
    numbered = list(enumerate(inputs, 1))
    reads: dict[int, dict] = {}
    for k in range(0, len(numbered), BATCH):
        reads.update(read_batch(title, numbered[k:k + BATCH], model, f"game:insight:{appid}"))
    t = tally(reads)
    w = _json(ask_llm(WRITE_PROMPT.format(title=title, n=len(reads), table=table_text(t, reads)), model, f"game:insight:{appid}"), "{", "}")
    quotes = {i: {"text": " ".join(r["text"].split())[:TEXT_CHARS], "stance": r["stance"], "lang": r["lang"],
                  "hours": round(r["playtime_minutes"] / 60) if r.get("playtime_minutes") else None, "source": r["source"]}
              for i, r in numbered}
    strs = lambda v: [str(s).strip() for s in v if str(s).strip()][:3] if isinstance(v, list) else []
    body = {"headline": str(w.get("headline") or "").strip(), "experience": str(w.get("experience") or "").strip(),
            "fits": strs(w.get("fits")), "not_fits": strs(w.get("not_fits")),
            "praise": points(t, reads, "good"), "complaints": points(t, reads, "bad"),
            "tally": {k: {"good": len(v["good"]), "bad": len(v["bad"])} for k, v in t.items()},
            "reads": {str(i): x for i, x in reads.items()}, "quotes": quotes,
            "stats": {"n": len(rows), "positive": sum(r["stance"] == "positive" for r in rows), "negative": sum(r["stance"] == "negative" for r in rows),
                      "used": len(inputs), "read": len(reads), "days": days}}
    return {"appid": appid, "generated_at": datetime.now(timezone.utc), "model": model, "input_hash": input_hash(inputs), "body": body}


def phenomena(body: dict, ranked: bool) -> list[str]:
    """左の案内の現象の種類（こちらで数えた件数から決める。LLM に種類を選ばせない）。"""
    t = body.get("tally") or {}
    g = lambda k: (t.get(k) or {}).get("good", 0)
    b = lambda k: (t.get(k) or {}).get("bad", 0)
    st = body.get("stats") or {}
    n = (st.get("positive") or 0) + (st.get("negative") or 0)
    pos = (st.get("positive") or 0) / n if n else None
    read = st.get("read") or 0
    out = []
    if g("update") >= 3 and g("update") > b("update"):
        out.append("rising")
    if g("time") >= 3 and g("time") > b("time"):
        out.append("short")
    if g("friends") >= 3:
        out.append("friends")
    if pos is not None and pos >= 0.85 and n >= 30 and not ranked:
        out.append("gem")
    if read and (b("bugs") + b("perf") + b("online") + b("price")) >= max(4, read * 0.3):
        out.append("caution")
    return out
