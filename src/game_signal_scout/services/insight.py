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
SESSIONS = ("short", "long")              # 1 回に遊ぶ時間（#2 2026-11-11: 「短時間で楽しみたい」の根拠）。発言に書いてあるときだけ。2026-11-11 より前に読んだ発言にはない
# 醍醐味（#2: そのゲームで何が面白いのか、の核心）の種類。体験から言えるときだけ付ける（作品の属性からは付けない）
APPEALS = ("conquer", "explore", "story", "grow", "team", "versus", "feel", "surprise")
KANA = re.compile(r"[\u3040-\u30ff]")
HANZI_ONLY = re.compile(r"[遇到们这个吗么还没为说时会对过進數膨脹遊後變們這個麼還說時會對過]")   # 日本語では使わない簡体字・中国語の語

READ_PROMPT = """ゲーム「{title}」のプレイヤーの発言を 1 件ずつ読んでください。発言が「自分が実際に遊んで、何をして、何が起きたか」を具体的に書いているときだけ、それを取り出します。
感想だけ・ニュース・質問・宣伝・抽象的な評価だけのものは null にします。発言にないことは書かないでください。
did は、ゲームの中の具体的な行動・場面・遊び方（例: 大剣で溜め攻撃を連発した・2 人で拠点を守った・設定で影を切った）。「プレイした」「遊んだ」「始めた」のような中身のない行動なら null。
happened は、その結果ゲームの中で具体的に起きたこと（例: ボスを 1 回で倒せた・味方と連携できた・フレームレートが倍になった）。「楽しかった」「良かった」だけなら null。
  不満（frustration）の体験の happened は、何が困った・嫌だったのかが読めば分かる書き方にします（例: 周りのプレイヤーに邪魔されて釣れなかった）。
  皮肉や「理想と現実」の対比のように、良いことが想像や期待として書かれているときは、その想像ではなく、実際に起きたこと（現実の側）を取り出します。
style は、その体験をどう遊んでいたときのものか（発言に書いてあるときだけ。言えなければ none）: solo（ひとりで）/ coop（ほかの人と協力して）/ versus（ほかの人と対戦して）/ none
input は、体験がコントローラーの操作感・使い勝手についてのとき controller、それ以外は none
appeal は、この体験の醍醐味＝何が面白かったのかの核心を、遊んだ人の実感の言い方で短く書いたもの（日本語 24 字以内）。
  言い方の例（形だけの参考。この文を使わず、必ず発言の中身で書く）: 「畑を広げるほど毎朝やることが増えて、やめ時を失う」「コーナーぎりぎりでドリフトが決まる瞬間がたまらない」
  悪い例（使わない）: 「〜の多様性」「〜の戦略性」「〜な点」「〜を楽しめる」のような、硬い名詞や評論の言い方
  不満だけの体験・面白さが書かれていない体験では空にします。発言にない面白さを足さないでください。
appeal_kind は、その醍醐味の種類: conquer（強敵・難所を自力で乗り越える手応え）/ explore（探索して見つける喜び）/ story（物語・世界に浸る）/ grow（育てる・作り上げる・やり込む）/ team（仲間との連携が決まる）/ versus（相手との駆け引き・読み合い）/ feel（操作・アクションの気持ちよさ）/ surprise（予想外の展開・意外な遊び方）/ none
caution は、買う・遊ぶ前に知っておくべき注意（発言に書いてあるときだけ）: time（時間がかかる）/ price（価格・課金）/ performance（重い・動作）/ bugs（不具合）/ difficulty（難しさ）/ online（接続・人がいない・不正）/ none
session は、1 回に遊ぶ時間について発言に書いてあるときだけ: short（1 回・1 試合が短い、すきま時間や数分〜30 分ほどで区切りよく遊べた）/ long（1 回が長い、何時間も続けて遊んだ・区切りにくい）/ none。書いていなければ none
各発言について次の JSON を返します: {{"id": 番号, "exp": null または {{"did": "プレイヤーがしたこと（日本語 30 字以内）", "happened": "その結果起きたこと（日本語 40 字以内）", "verdict": "fun（面白い・良かった）/ frustration（不満・困った）/ mixed", "topic": "体験の話題を表す短い日本語（15 字以内）", "appeal": "醍醐味（日本語 30 字以内。なければ空）", "appeal_kind": "conquer / explore / story / grow / team / versus / feel / surprise / none", "style": "solo / coop / versus / none", "input": "controller / none", "caution": "time / price / performance / bugs / difficulty / online / none", "session": "short / long / none"}}}}
次の形の JSON だけを返してください（前置き不要）: {{"items": [各発言の JSON, ...]}}

発言:
{lines}"""

GROUP_PROMPT = """ゲーム「{title}」のプレイヤーの体験の一覧です。同じ具体的な体験（同じことをして、同じことが起きた）を書いているものをまとめてください。
言い換えでも中身が同じならまとめ、中身が違えば分けます。まとまらないものは入れなくてよいです。番号は一覧にあるものだけを使います。
title は、一覧にある具体的な行動と結果をそのまま使って書きます（例:「斬馬刀でボスに挑むと、ほぼ一方的に押し切れる」「ボス戦の途中で強制終了し、進行が消える」）。
「〜を評価する」「〜を感じる」「〜に満足」のような抽象的な言い方にしないでください。一覧にないことは足さないでください。
appeal は、このまとまりの体験の醍醐味＝何が面白いのかの核心を、遊んだ人の実感の言い方で短く（日本語 24 字以内）。例の文は使わず、一覧の体験の中身で書く。
「〜の多様性」「〜の戦略性」「〜な点」「〜を楽しめる」のような硬い言い方にしない。一覧にある体験の言葉を使い、面白さが書かれていなければ空にします。
fits は、一覧の体験そのものから言える「この体験が向いている人」（例: 自力で攻略したい人・決まった仲間と遊べる人）。一覧から言えなければ空にします。
次の形の JSON だけを返してください（前置き不要）: {{"groups": [{{"title": "まとめた体験を 1 文で（「〜すると、〜」の形。日本語 50 字以内）", "appeal": "醍醐味（日本語 30 字以内。なければ空）", "fits": "向いている人（日本語 25 字以内。言えなければ空）", "ids": [番号, ...]}}]}}

一覧:
{items}"""


DIVIDE_VERSION = "d3"   # 論点の組の作り方の版（指示文を変えたら上げる。上がると保存済みの読み取りから作り直す）
DIVIDE_PROMPT = """ゲーム「{title}」のプレイヤーの体験の一覧です。[+] は面白かった体験、[-] は不満だった体験です。
同じ 1 つの性質について、[+] の人はそれを良いと感じ、[-] の人は同じその性質を悪いと感じている組だけを探してください。
同じ性質とは、例えば「ボスの難しさ」（[+] 難しいボスを倒せて最高 ／ [-] ボスが難しすぎて嫌になった）、「カメラの動き」（[+] 視点が自由で見やすい ／ [-] 視点が勝手に動いて酔う）、
「マップの広さ」（[+] 広くて探索しがいがある ／ [-] 広すぎて移動が退屈）のように、良し悪しを言っている対象がまったく同じものです。
同じ場所・同じモード・同じマップの話でも、良いと言っている点と悪いと言っている点が違えば組にしません（例: 「街で隠し要素を見つけた」と「街の敵が強すぎる」は、発見と難しさで別の点なので組にしない）。
「協力プレイが楽しい」と「起動時に落ちる」のように対象が違うものも組にしません。一覧の文から同じ性質だと言い切れないものは組にしません。組がなければ空にします。
point は、意見が分かれた性質を表す短い日本語（15 字以内。例: ボスの難しさ・カメラの動き・マップの広さ）。場所やモードの名前だけにしない。一覧にない言葉で膨らませないでください。
番号は一覧にあるものだけを使い、pro には [+] の番号だけ、con には [-] の番号だけを入れます。
次の形の JSON だけを返してください（前置き不要）: {{"pairs": [{{"point": "性質", "pro": [番号, ...], "con": [番号, ...]}}]}}

体験:
{items}"""
CHECK_PROMPT = """次の 2 つの体験は、どちらも「{point}」という同じ性質について述べていて、1 つ目はそれを良いと、2 つ目はそれを悪いと感じていますか。
片方が別の性質（例: 一方は操作の感触、もう一方は物理演算の騒ぎ）について述べているなら no です。文から言い切れないときも no です。
1: {pro}
2: {con}
yes か no だけを JSON で返してください: {{"same": "yes" または "no"}}"""
POINT_BAD = re.compile(r"(全体|色々|いろいろ|様々|さまざま|ゲーム性|体験|その他|評価|満足|不満)$")


def divide(ask, title: str, exps: list[tuple[str, dict]], authors: dict[str, str]) -> list[dict]:
    """同じ論点で賛否が分かれた体験（#2 2026-11-11 オーナー: 違う論点の好評と不満を寄せ集めない）。exps = [(item_id, 体験)]（直近の窓の体験）。
    LLM は「同じ対象についての面白い体験と不満の体験」の組と論点の名前だけを返し、番号・面白い／不満の向き・人数はこちらで確かめて数える。
    返り値: [{point, pro: [体験], con: [体験], pro_people, con_people}]（同じ人は 1 人。両方の側に 1 人以上の組だけ）。"""
    pro_i = [i for i, (_, e) in enumerate(exps) if e["verdict"] == "fun"]
    con_i = [i for i, (_, e) in enumerate(exps) if e["verdict"] == "frustration"]
    if not pro_i or not con_i:
        return []
    items = "\n".join(f"[{i}] {'[+]' if e['verdict'] == 'fun' else '[-]'} {e['did']} → {e['happened']}" for i, (_, e) in enumerate(exps) if i in set(pro_i + con_i))
    pairs, seen = [], set()
    for g in _json_array(ask(DIVIDE_PROMPT.format(title=title, items=items))):
        if not isinstance(g, dict):
            continue
        point = str(g.get("point") or "").strip()[:30]
        if not point or not KANA.search(point) and not re.search(r"[\u4e00-\u9fff]", point) or HANZI_ONLY.search(point) or POINT_BAD.search(point):
            continue
        ids = lambda k, ok: sorted({int(i) for i in g.get(k) or [] if str(i).isdigit() and int(i) in ok})
        pro, con = ids("pro", set(pro_i)), ids("con", set(con_i))
        if not pro or not con or (tuple(pro), tuple(con)) in seen:
            continue
        seen.add((tuple(pro), tuple(con)))
        ev = lambda i: {"did": exps[i][1]["did"], "happened": exps[i][1]["happened"]}
        people = lambda xs: len({authors.get(exps[i][0]) or exps[i][0] for i in xs})   # 同じ人の複数の発言は 1 人
        who = lambda xs: {authors.get(exps[i][0]) or exps[i][0] for i in xs}
        if not (who(pro) - who(con)) or not (who(con) - who(pro)):   # 同じ人だけが両方の側にいる: 意見が分かれたとは言わない
            continue
        # 確かめ（#2 2026-11-11）: 組のいちばん目の体験どうしが、本当に同じ性質の良し悪しか、もう一度だけ問う。no・答えなしは組にしない
        try:
            ok = '"yes"' in ask(CHECK_PROMPT.format(point=point, pro=f"{exps[pro[0]][1]['did']} → {exps[pro[0]][1]['happened']}",
                                                     con=f"{exps[con[0]][1]['did']} → {exps[con[0]][1]['happened']}")).replace(" ", "").lower()
        except Exception:  # noqa: BLE001 — 確かめられない組は出さない
            ok = False
        if not ok:
            continue
        pairs.append({"point": point, "pro": [ev(i) for i in pro[:3]], "con": [ev(i) for i in con[:3]], "pro_people": people(pro), "con_people": people(con)})
    return pairs


def _json_array(text: str) -> list:
    try:
        v = json.loads(text[text.find("["):text.rfind("]") + 1])
        return v if isinstance(v, list) else []
    except (ValueError, TypeError):
        return []


EXAMPLES = ("畑を広げるほど毎朝やることが増えて、やめ時を失う", "コーナーぎりぎりでドリフトが決まる瞬間がたまらない")   # 指示の例の写しは使わない
STIFF = re.compile(r"(性|な点|の点|点|を楽しめる|が楽しめる|を楽しむ)。?$")   # 硬い・評論の言い方の醍醐味は使わない
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
    sy, ip, ca, ak, se = (str(e.get(k) or "").strip() for k in ("style", "input", "caution", "appeal_kind", "session"))
    ap = str(e.get("appeal") or "").strip()[:40]
    if v == "frustration" or not KANA.search(ap) or HANZI_ONLY.search(ap) or STIFF.search(ap) or ap in EXAMPLES:   # 不満だけの体験・訳されていない句には醍醐味を付けない
        ap, ak = "", ""
    return {**out, "verdict": v, "appeal": ap, "appeal_kind": ak if ak in APPEALS and ap else None, "style": sy if sy in STYLES else None, "input": ip if ip in INPUTS else None, "caution": ca if ca in CAUTIONS else None,
            "session": se if se in SESSIONS else None}


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
        fits, ap = str(g.get("fits") or "").strip()[:40], str(g.get("appeal") or "").strip()[:40]
        if fits and (not KANA.search(fits) or HANZI_ONLY.search(fits)):
            fits = ""
        if ap and (not KANA.search(ap) or HANZI_ONLY.search(ap) or ABSTRACT.search(ap) or STIFF.search(ap) or ap in EXAMPLES):
            ap = ""
        if ids:
            out.append({"title": str(g["title"]).strip()[:80], "fits": fits, "appeal": ap, "members": [exps[i][0] for i in ids]})
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
        kind = _major(cur, exps, "appeal_kind")
        ap = g.get("appeal") or next((exps[m]["appeal"] for m in cur if exps[m].get("appeal") and exps[m].get("appeal_kind") == kind), "")
        finds.append({"title": g["title"], "fits": g.get("fits") or "", "appeal": ap if _verdict(v) != "frustration" else "", "appeal_kind": kind if _verdict(v) != "frustration" else None, "verdict": _verdict(v), "people": people, "prev": before, "trend": trend,
                      "style": _major(cur, exps, "style"), "input": _major(cur, exps, "input"), "caution": _major(cur, exps, "caution"), "session": _major(cur, exps, "session"),
                      "fun": v["fun"], "frustration": v["frustration"], "mixed": v["mixed"],
                      "langs": [lg for lg, _ in Counter(posts[m]["lang"] for m in cur if posts[m]["lang"]).most_common()],
                      "examples": [{"did": exps[m]["did"], "happened": exps[m]["happened"], "verdict": exps[m]["verdict"]} for m in cur[:3]]})
    return sorted(finds, key=lambda f: (-f["people"], f["title"]))


def singles(posts: dict[str, dict], exps: dict[str, dict], finds_members: set[str], since, limit: int = 6) -> list[dict]:
    """まだほかの人の声と重ならない、ひとりの具体的な体験（直近の窓）。発見ではなく「ひとりの体験」として、そう明記して出す。"""
    out = [{"did": e["did"], "happened": e["happened"], "verdict": e["verdict"], "topic": e["topic"], "appeal": e.get("appeal") or "", "appeal_kind": e.get("appeal_kind"), "style": e.get("style"), "input": e.get("input"),
            "caution": e.get("caution"), "session": e.get("session"), "lang": posts[k]["lang"]}
           for k, e in sorted(exps.items(), key=lambda kv: posts[kv[0]]["at"], reverse=True) if k not in finds_members and posts[k]["at"] >= since]
    return out[:limit]


EN_BATCH = 16
JA_CHARS = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")
EN_PROMPT = """Translate each Japanese line about the video game "{title}" into natural, concise English for an English-speaking player.
Keep the exact meaning: do not add, drop or soften anything. Keep every number, unit, negation and uncertainty. Keep game, item and place names as they are.
Lines are short notes of what a player did, what happened, or what was fun. Keep the same short note style (no quotation marks).
Return only JSON: {{"items": [{{"id": number, "en": "English"}}, ...]}}

Lines:
{lines}"""


def public_texts(body: dict) -> list[str]:
    """画面に出す日本語の文（面白さの一文・したこと・起きたこと・向いている人）。英語の表示のために訳す対象。"""
    out: list[str] = []
    for f in (body or {}).get("finds") or []:
        ex = (f.get("examples") or [{}])[0]
        out += [f.get("appeal") or "", ex.get("did") or "", ex.get("happened") or "", f.get("fits") or ""]   # fits: 向いている人（遊びたい体験の入口。#2 2026-11-11）
    for e in (body or {}).get("singles") or []:
        out += [e.get("appeal") or "", e.get("did") or "", e.get("happened") or ""]
    for d in (body or {}).get("divided") or []:   # 同じ論点で賛否が分かれた体験（#2 2026-11-11）
        out += [d.get("point") or ""] + [x.get(k) or "" for x in (d.get("pro") or []) + (d.get("con") or []) for k in ("did", "happened")]
    return list(dict.fromkeys(t for t in out if t))


def _en_ok(ja: str, en: str) -> bool:
    """訳文の検査: 空でない・日本語の文字が残っていない・長すぎない・元の数字を落としていない。"""
    if not en or JA_CHARS.search(en) or len(en) > max(160, len(ja) * 6):
        return False
    return set(re.findall(r"\d+", ja)) <= set(re.findall(r"\d+", en))


def translate_en(ask, title: str, texts: list[str], known: dict | None = None, limit: int | None = None) -> dict[str, str]:
    """日本語の文 → 英語の訳（同じ文は訳し直さない: known）。検査に通らなかった文・読めなかった束は入れない（次の回に訳し直す）。
    返すのは今の texts の分だけ（もう出さない文の訳は持たない）。limit = 1 回に訳す文の数の上限（共有の LLM の枠を長く使わない）。"""
    known = known or {}
    out = {t: known[t] for t in texts if known.get(t)}
    todo = [t for t in texts if t not in out][: limit if limit is not None else None]
    for i in range(0, len(todo), EN_BATCH):
        b = todo[i:i + EN_BATCH]
        lines = "\n".join(f"[{j}] {t}" for j, t in enumerate(b))
        try:
            raw = ask(EN_PROMPT.format(title=title, lines=lines))
            arr = json.loads(raw[raw.find("{"):raw.rfind("}") + 1]).get("items") or []
        except Exception:  # noqa: BLE001 — 一時的な失敗・壊れた応答: この束は次の回に訳す
            continue
        for it in arr if isinstance(arr, list) else []:
            if not isinstance(it, dict):
                continue
            try:
                j = int(it.get("id"))
            except (TypeError, ValueError):
                continue
            en = str(it.get("en") or "").strip().strip('"「」')
            if 0 <= j < len(b) and _en_ok(b[j], en):
                out[b[j]] = en
    return out


def ask_for(cfg: dict):
    """共有の LLM の枠での 1 回の問い合わせ（JSON で返す）。文脈の長さ・出力の長さ・温度は設定（config/daily.toml [insight]）から読む（#3: コードに数字を書かない）。"""
    from game_signal_scout import llm
    opts = {"temperature": float(cfg["temperature"]), "num_ctx": int(cfg["num_ctx"]), "num_predict": int(cfg["num_predict"])}
    return lambda p: llm.chat(cfg["model"], "", p, format="json", think=False, options=opts, timeout=float(cfg.get("timeout_seconds", 1800))).content


def input_hash(rows: list[dict]) -> str:
    return hashlib.sha256("|".join(sorted(r["item_id"] for r in rows)).encode()).hexdigest()[:16]


def read_game(conn, work_id: str, title: str, model: str, cfg: dict, prev_body: dict | None = None, ask=None) -> dict | None:
    """作品 1 つの発見。prev_body（前の回の body）の reads を使い、新しい発言だけを読む。"""
    from game_signal_scout.repositories import insight as repo
    days = int(cfg.get("window_days", 7))
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    from game_signal_scout import observations
    srcs = list(observations.sources())   # 集計に入れている取得元（有効で、利用条件で止まっていないもの。保留・停止の取得元の保存済みの発言は使わない）
    rows = repo.statements_by_author(conn, work_id, days * 2, int(cfg.get("max_per_window", 60)), since, srcs)
    if not rows:
        return None
    if ask is None:
        from game_signal_scout import llm
        ask = ask_for({**cfg, "model": model})
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
    body_public = {"finds": finds, "singles": singles(posts, exps, members, since)}
    # 英語の表示（#2 2026-11-09 オーナー）: 画面に出す日本語の文の英訳。前の回に訳した文は訳し直さない
    en = translate_en(ask, title, public_texts(body_public), (prev_body or {}).get("en"))
    return {"work_id": work_id, "generated_at": now, "model": model, "input_hash": input_hash(rows),
            "body": {"kind": KIND, "en": en, "window_days": days, "since": since.isoformat(), "read_people": n_cur, "min_people": mp,
                     "experiences": cur_exps, "finds": finds, "singles": body_public["singles"], "stages": stages, "reads": reads}}


def divide_game(conn, work_id: str, title: str, body: dict, cfg: dict, ask) -> list[dict]:
    """保存済みの読み取り（body の reads）から、同じ論点で賛否が分かれた体験を作る（読み直さない）。窓は読み取りを作ったときの直近の窓（body の since）。"""
    from game_signal_scout.repositories import insight as repo
    from game_signal_scout import observations
    since = datetime.fromisoformat(body["since"]) if body.get("since") else datetime.now(timezone.utc) - timedelta(days=int(cfg.get("window_days", 7)))
    days = int(body.get("window_days") or cfg.get("window_days", 7))
    rows = repo.statements_by_author(conn, work_id, days * 2, int(cfg.get("max_per_window", 60)), since, list(observations.sources()))
    posts = {r["item_id"]: r for r in rows}
    exps = sorted([(k, v) for k, v in (body.get("reads") or {}).items() if v and k in posts and posts[k]["at"] >= since], key=lambda kv: posts[kv[0]]["at"])
    return divide(ask, title, exps, {k: posts[k]["author"] for k in posts})
