"""Q1・Q2 の作品ごとの「その日に何が起きたか」（Issue #28。仕様 docs/TODAYS-SIGNAL-PAGES.md §1 の Q1・Q2）。

行の人数（A: 共通の集計が数えた投稿者）と同じ投稿の集合から、次を分けて作る。作品名・取得元の名前で分岐しない。
- B 中心の出来事: その投稿の多くが何についてのものか（記念日・発表・予告・放送・配信・催し・ニュース…）を 1 文と、それを書いた人数（同じ母数の中で）
- C 独立したファンの反応: 知らせ・共有・公式・まとめの投稿を除いた、自分の言葉の投稿だけで 1 文と人数
段 1（規則）: 行の人数に数えた投稿（observations の読み取りの counted）を 1 人 1 つ読む。
段 2（LLM）: 投稿だけを材料に、出来事と反応を日本語で 1 文ずつと、すべての投稿の分類（E = 出来事を伝える・紹介するだけ / ER = 出来事について自分の
  感想・意見・期待・実況がある / R = この作品の、出来事以外の点への自分の感想 / - = どちらでもない）を書かせる。人数は書かせない。
  根拠の番号を列挙させると、取りこぼし（記念日の挨拶・放送の実況）と取り違え（記念日の紹介を反応に）が多かった（#28 の 10/25 の突き合わせ）。
段 3（規則）: 根拠の投稿が数えた集合にあるか・人数（根拠の投稿の投稿者を規則で数える）・反応の根拠から知らせ・共有・公式・まとめを外す・
  文の数・括弧の言葉・片仮名の名前は根拠の原文にあるか・作品名を書いていないか・人気や急上昇のような根拠のない言葉がないか。
  落ちた点を伝えて 1 回だけ書き直させ、それでも通らない文は出さない（推測で埋めない）。
段 4（LLM）: 通った日本語の文を、根拠の原文を見ながら英語へ訳す（訳にも数・規模の言葉の検査をかける。訳が落ちた文は日英とも出さない）。
動かす場所: 常駐の worker（ops/worker.py の 6。Observation の処理待ちがない周に、[work_events] every_minutes ごと・max_works 作品まで。
  LLM の排他の鍵を取ってから）。1 作品に数十秒かかるので、日次処理の公開を待たせない。対象は確定した最新の日と、その前 days_back 日。
保存: job_artifact（job = "work_events"。1 日 1 行に置き換える。画面はその日のいちばん新しい記録を読む）。作品ごとの入力の鍵が前と同じなら作り直さない。
指示文や規則を変えたときは `job work_events --force` で作り直す（版の名前は持たない）。
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date

from game_signal_scout.repositories import foundation as foundation_repo

JOB = "work_events"
MAX_POSTS, POST_CHARS = 24, 200        # 1 作品で読む投稿の上限（1 人 1 つ・長い順）と、1 投稿の文字数（件数に比例して伸びないように）
MIN_EVENT_PEOPLE = 2                   # 中心の出来事として書く人数（1 人の投稿を中心の出来事にしない）
SENT_MAX = {"ja": 45, "en": 130}      # カードで一目で読める長さ
TEMPLATE_HEAD = 30                     # 別の人と書き出しがこの文字数まで同じ投稿は定型（挨拶・紹介の使い回し）: 反応に数えない
KINDS = ("anniversary", "announcement", "trailer", "broadcast", "release", "event", "news", "discussion", "mixed", "unclear")
NOT_OWN = ("share", "official")        # 声の役割の判定で、自分の言葉の反応でない投稿（共有・公式の発信）
NOT_OWN_KIND = ("share",)              # 投稿の種類の判定で、共有
HYPE = {"ja": re.compile(r"人気|急上昇|話題沸騰|殺到|大反響|反響を呼|ブーム|熱狂|続出|相次|多くの|多数の|ファンの間で|盛り上が|注目を集"),
        "en": re.compile(r"\b(popular|popularity|surge|surging|viral|hype|hyped|trending|buzz|craze|many|numerous|widely)\b", re.I)}
NUM = re.compile(r"\d+")
QUOTED = re.compile(r"[「『\"“]([^」』\"”]{2,60})[」』\"”]")
KATAKANA = re.compile(r"[ァ-ヴー]{3,}")
# 片仮名の検査で、原文になくてよい一般の言葉（名前の書き誤りを捕まえるための検査で、一般の外来語は対象にしない）
COMMON_KANA = {"アニメ", "アニメーション", "コスプレ", "パートナー", "エンディング", "オープニング", "シーズン", "キャラクター", "イベント", "コラボ",
               "ティザー", "トレーラー", "ストーリー", "シーン", "ファン", "デザイン", "ニュース", "スタジオ", "キャスト", "ポスター", "テーマ", "ドラマ",
               "シリーズ", "エピソード", "コメント", "グッズ", "ゲーム", "テレビ", "パート", "テンポ", "ビジュアル", "メインビジュアル", "プロモーション",
               "スタッフ", "キャラ", "ヒロイン", "ストリーミング", "サービス", "リメイク", "コミック", "マンガ", "タイトル", "ミュージック", "テーマソング"}
FIX = {"quote_not_in_posts": "「」『』で囲んだ言葉が posts にそのまま書かれていない。posts のとおりに写すか、括弧を使わない。",
       "katakana_not_in_posts": "片仮名の名前・言葉が posts にそのままない。posts の書き方のとおりに書く。",
       "work_name": "作品名を書いている。作品名は書かない。", "too_long": "長すぎる。30 字ほどの短い文にする（説明や由来を足さない）。",
       "hype": "人気・多くの・話題沸騰のような、投稿から確かめられない評価や規模の言葉がある。消す。",
       "number_not_in_posts": "posts にない数（日付・話数など）がある。posts にある数だけを書く。",
       "labels_missing": "labels に分けていない posts がある。すべての posts の id を E・ER・R・- のどれかに分ける。"}
LABELS = ("E", "ER", "R", "-")

SYSTEM = """あなたはアニメの作品について、ある日に投稿された文章（posts）を読む分析者です。posts は、その日にその作品に触れた投稿で、1 つが 1 人です。
読者の問いは「この日、この作品について実際に何が起きたのか」です。人数や人気を推測するのではなく、投稿に書かれている事実だけで答えてください。
- event: posts の多くが何についての投稿か（中心の出来事）。kind は次から 1 つ:
  anniversary（記念日・周年の紹介）/ announcement（放送・配信・続編などの発表）/ trailer（予告映像・紹介映像の公開）/ broadcast（放送・配信の日の実況や視聴）/
  release（発売・公開）/ event（催し・コラボ・展示の告知）/ news（そのほかのニュースの転載）/ discussion（ファン同士の具体的な話題）/
  mixed（中心が 1 つに決まらず、別々の話題が混ざっている）/ unclear（投稿から分からない）。
  ja は、その出来事を日本語の 30 字ほどの短い文で（例:「アニメの日」の紹介の投稿／第17話の放送と配信／予告映像の公開と2027年の放送の発表）。
  説明・理由・由来は足さない。日付・話数などは posts に書いてあるものだけを書く。
- reaction: 自分の言葉で感想・意見・期待・不満・実況を書いた posts（labels が ER か R）がいちばん多く言っていること。ja は日本語の 30 字ほどの短い文で
  （例: 短縮版はテンポが良いのでおすすめ／父親のつらさと過酷な展開への声／予告を見て放送が楽しみ）。「感想を述べている」のような言い回しは書かない。
  具体的に（どの場面・人物・点について、どう感じたか）。人物の名前は posts の書き方のとおりに。そういう posts がなければ null。
- labels: posts の id をすべて 1 つずつ、次のどれかに分ける（抜かさない）:
  E = 中心の出来事を伝える・紹介する・挨拶で触れるだけ（自分の感想・意見がない。定型の紹介や記念日の挨拶、ニュースの転載、放送の告知はここ。
      挨拶や紹介に添えた、どの作品にも言える一言〔「心に残っていますよね」「素敵な一日を」など〕は感想ではないので E）
  ER = 中心の出来事について、作品そのものへの自分の感想・意見・評価・体験・期待・実況がある（放送を見ながらの実況、予告を見た感想など）
  R = この作品の、中心の出来事以外の点（場面・人物・前の話・原作など）について、自分の感想・意見・期待がある
  - = どちらでもない（別の話題の知らせ・作品名の一覧だけ・別の作品の話・人への挨拶や返事・作品と関係のない話）
- 作品名は書かない（画面の行に作品名がある。「この作品は」とも書かず、出来事・反応の中身から書き始める）。
- 「」『』で囲むのは、posts に書いてあるとおりの言葉だけ。
- 書いてはいけないこと: 人気・急上昇・話題沸騰・多くの・ファンの間で のような、投稿から確かめられない評価や規模の言葉。人数（人数は別に数える）。投稿にない原因や因果。
出力は JSON だけ: {"event": {"kind": "…", "ja": "…"}, "reaction": {"ja": "…"}, "labels": {"P1": "E", "P2": "ER", "P3": "R", "P4": "-"}}"""

TRANSLATE = """次の日本語の文（あるアニメ作品について、その日の投稿から書いた文）を、それぞれ英語の短い文に訳してください（15 語ほど）。
人物・会社の名前は、posts に英語やローマ字の書き方があればそれを使う。作品名は書かない（日本語の文にない作品名を足さない）。
第三者の文で書く（I・we・you を使わない。例: Viewers…, Posts…）。意味を足さない・規模や評価の言葉（popular, many, viral など）を足さない。引用符は使わない。
出力は JSON だけ: {"event": "…", "reaction": "…"}（文が null のものは null）"""


# ---------------------------------------------------------------- 段 1 投稿（規則）
def counted(conn, source: str, day: date) -> dict[int, list[str]]:
    """その日にその取得元で、共通の集計が行の人数に数えた投稿（作品 → 発言の ID）。人数の母数と同じ集合。"""
    from game_signal_scout import observations
    prof = observations.sources().get(source) or {}
    r = observations.READERS[prof.get("reader", "foundation")](conn, source, day, prof)
    out: dict[int, list[str]] = {}
    for o in r.obs:
        if o.status == "counted" and o.work_id is not None and o.actor:
            out.setdefault(int(o.work_id), []).append(o.unit)
    return out


def posts(conn, source: str, ids: list[str]) -> list[dict]:
    """数えた投稿の本文と判定（1 人 1 つ、長い順に MAX_POSTS まで）。own = 自分の言葉の反応になりうる投稿（共有・公式の発信・まとめ・情報の発信の投稿者でなく、別の人と書き出しが同じ定型でない）。"""
    from game_signal_scout.foundation.signals import info_roles
    if not ids:
        return []
    rows = foundation_repo.list_longest_posts_with_roles(conn, source, ids)
    conn.rollback()
    info = set(info_roles()) | {"aggregator"}
    head = lambda t: re.sub(r"\W+", "", t)[:TEMPLATE_HEAD]   # noqa: E731
    heads: dict[str, set] = {}
    for actor, _uid, _lang, body, *_ in rows:
        if len(head(body)) >= TEMPLATE_HEAD:
            heads.setdefault(head(body), set()).add(actor)
    out = []
    for actor, uid, lang, body, kind, role, arole in sorted(rows, key=lambda r: (-len(r[3]), r[1]))[:MAX_POSTS]:
        own = role not in NOT_OWN and kind not in NOT_OWN_KIND and arole not in info and len(heads.get(head(body), ())) < 2
        out.append({"id": f"P{len(out) + 1}", "uri": uid, "actor": actor, "lang": lang, "text": re.sub(r"\s+", " ", body).strip()[:POST_CHARS], "own": own})
    return out


def input_key(ps: list[dict]) -> str:
    return hashlib.sha256(json.dumps([(p["uri"], p["text"], p["own"]) for p in ps], ensure_ascii=False).encode()).hexdigest()[:16]


# ---------------------------------------------------------------- 段 2・段 4（LLM）
def _chat(llm, model: str, system: str, user: str, predict: int) -> dict:
    from game_signal_scout.ops import dashboard_digest
    return (llm or dashboard_digest._chat)(model, system, user, predict)


def ask(model: str, ps: list[dict], llm=None, feedback: list[str] | None = None) -> dict:
    user = json.dumps({"posts": [{"id": p["id"], "lang": p["lang"], "text": p["text"]} for p in ps]}, ensure_ascii=False)
    if feedback:
        user += "\n\n前の答えは次の点で使えなかった。直して答え直す:\n" + "\n".join(f"- {f}" for f in feedback)
    return _chat(llm, model, SYSTEM, user, 400)


def translate(model: str, rec: dict, grounds: list[str], llm=None) -> dict:
    user = json.dumps({"event": (rec.get("event") or {}).get("ja"), "reaction": (rec.get("reaction") or {}).get("ja"), "posts": grounds[:8]}, ensure_ascii=False)
    return _chat(llm, model, TRANSLATE, user, 320)


# ---------------------------------------------------------------- 段 3 確かめ（規則）
def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s).lower()


def _mostly_japanese(t: str) -> bool:
    """原文の文字の半分以上が仮名・漢字（片仮名の名前は原文の書き方と比べられる。英語などの原文の名前の片仮名書きは比べない）。"""
    letters = [ch for ch in t if ch.isalpha()]
    return bool(letters) and sum(1 for ch in letters if "\u3040" <= ch <= "\u30ff" or "\u4e00" <= ch <= "\u9fff") * 2 >= len(letters)


def sentence_errors(s: str | None, loc: str, ground: str, names: tuple[str, ...] = ()) -> list[str]:
    """1 文の検査（ground = 根拠の投稿の原文。英語は訳した元の日本語の文も含める）。"""
    if not s or not s.strip():
        return ["empty"]
    g, err = _norm(ground), []
    if loc == "ja" and any(_norm(q) not in g for q in QUOTED.findall(s)):
        err.append("quote_not_in_posts")
    if loc == "ja" and _mostly_japanese(ground) and any(k not in ground and k not in COMMON_KANA for k in KATAKANA.findall(s)):
        err.append("katakana_not_in_posts")
    if any(_norm(n) in _norm(s) for n in names):
        err.append("work_name")
    if len(s) > SENT_MAX[loc]:
        err.append("too_long")
    if HYPE[loc].search(s):
        err.append("hype")
    if any(n not in ground for n in NUM.findall(s)):
        err.append("number_not_in_posts")
    return err


def verify(raw: dict, ps: list[dict], n: int, names: tuple[str, ...] = ()) -> dict:
    """LLM の答えを、数えた投稿で確かめる。根拠は投稿ごとの分類（出来事 = E・ER、反応 = ER・R の自分の言葉の投稿）。人数は根拠の投稿者を規則で数える。"""
    by = {p["id"]: p for p in ps}
    got = raw.get("labels") if isinstance(raw.get("labels"), dict) else {}
    labels = {i: (got.get(i) if got.get(i) in LABELS else "-") for i in by}
    missing = [i for i in by if got.get(i) not in LABELS]

    def part(x, own_only: bool):
        if not isinstance(x, dict) or not x.get("ja"):
            return None, ["none"]
        want = ("ER", "R") if own_only else ("E", "ER")
        ids = [i for i in by if labels[i] in want and (by[i]["own"] or not own_only)]
        if not ids:
            return None, ["no_own_posts" if own_only else "no_posts"]
        ja = x["ja"].strip().rstrip("。.")
        return {"ja": ja, "people": len({by[i]["actor"] for i in ids}), "uris": [by[i]["uri"] for i in ids], "ground": [by[i]["text"] for i in ids]}, \
            sentence_errors(ja, "ja", " ".join(by[i]["text"] for i in ids), names)
    ev_raw = raw.get("event") if isinstance(raw.get("event"), dict) else {}
    kind = ev_raw.get("kind") if ev_raw.get("kind") in KINDS else "unclear"
    ev, ev_bad = part(ev_raw, False)
    if kind in ("mixed", "unclear"):
        ev, ev_bad = None, [kind]
    elif ev and ev["people"] < MIN_EVENT_PEOPLE:
        ev, ev_bad = None, ["few_people"]
    re_, re_bad = part(raw.get("reaction"), True)
    return {"labels": {by[i]["uri"]: labels[i] for i in by}, "missing": len(missing), "n": n, "read": len({p["actor"] for p in ps}), "own": len({p["actor"] for p in ps if p["own"]}), "kind": kind,
            "event": ev if not ev_bad else None, "event_rejected": ev_bad,
            "reaction": re_ if not re_bad else None, "reaction_rejected": re_bad}


def fixable(v: dict) -> list[str]:
    """書き直させれば直る誤り（文の検査で落ちたもの・分けていない投稿。分けていない投稿は、書き直しでも直らなければ「-」として数える）。"""
    return sorted({e for e in v["event_rejected"] + v["reaction_rejected"] if e in FIX} | ({"labels_missing"} if v.get("missing") else set()))


def add_english(v: dict, raw: dict, names: tuple[str, ...] = ()) -> dict:
    """訳を記録に入れる。訳が検査で落ちた文は、日英の片方だけを出さないように両方とも外す。"""
    for k in ("event", "reaction"):
        x = v.get(k)
        if not x:
            continue
        en = re.sub(r"[\"“”]", "", raw.get(k) or "").strip().rstrip(".") if isinstance(raw.get(k), str) else ""
        bad = sentence_errors(en, "en", x["ja"] + " " + " ".join(x["ground"]), names)
        if bad:
            v[k], v[f"{k}_rejected"] = None, [f"en:{e}" for e in bad]
        else:
            x["en"] = en
    return v


# ---------------------------------------------------------------- 1 日分
def rows_of(mv: dict) -> list[dict]:
    """「いつもより話題が増えた作品」に載る作品の行（全件。画面は初めの数件と「もっと見る」）。"""
    return ((mv or {}).get("q1") or {}).get("featured") or []


def one(model: str, row: dict, ps: list[dict], llm=None) -> tuple[dict, int]:
    """1 作品の出来事と反応（記録と、LLM を呼んだ回数）。"""
    names = tuple(x for x in ((row.get("name") or {}).get("ja"), (row.get("name") or {}).get("en")) if x and len(x) >= 2)
    if not ps:
        return {**verify({}, [], row.get("n") or 0), "reason": "no_text"}, 0
    asked, fb = 0, None
    for _ in range(2):   # 検査で落ちた点を伝えて 1 回だけ書き直させる
        v = verify(ask(model, ps, llm, [FIX[e] for e in fb] if fb else None), ps, row.get("n") or 0, names)
        asked += 1
        fb = fixable(v)
        if not fb:
            break
    if v["event"] or v["reaction"]:
        add_english(v, translate(model, v, [t for k in ("event", "reaction") if v[k] for t in v[k]["ground"]], llm), names)
        asked += 1
    for k in ("event", "reaction"):
        if v[k]:
            v[k].pop("ground")
    return v, asked


def generate_day(conn, cfg: dict, day: date, mv: dict, prev: dict | None = None, llm=None, log=print, max_new: int | None = None,
                 should_stop=lambda: False) -> dict:
    """その日の Q1・Q2 の行の作品ごとに、出来事と反応を作る。前の記録（prev）と入力の鍵が同じ作品は作り直さない。
    max_new 作品を作ったら（または止める合図で）残りは前の記録のまま（pending に数える。次の周で続ける）。"""
    import time
    model = (cfg.get("dashboard_digest") or {}).get("model")
    old = {(w["source"], w["work_id"]): w for w in (prev or {}).get("works") or [] if w.get("key")}
    cnt: dict[str, dict[int, list[str]]] = {}
    works, t0, asked, done, made, pending = [], time.monotonic(), 0, set(), 0, 0
    for r in rows_of(mv):
        src, wid = r.get("src"), int(str(r["id"]).lstrip("w"))
        if not src or (src, wid) in done:
            continue
        done.add((src, wid))
        if src not in cnt:
            cnt[src] = counted(conn, src, day)
        ps = posts(conn, src, cnt[src].get(wid, []))
        key = input_key(ps)
        o = old.get((src, wid))
        if o and o["key"] == key:
            works.append(o)
            continue
        if (max_new is not None and made >= max_new) or should_stop():
            pending += 1
            if o:
                works.append(o)
            continue
        made += 1
        try:
            v, k = one(model, r, ps, llm)
            asked += k
        except Exception as e:  # noqa: BLE001 — 1 作品の失敗で残りを止めない（その作品は出来事なし。次の日次処理で作り直す）
            conn.rollback()
            v, key = {**verify({}, ps, r.get("n") or 0), "reason": f"error:{type(e).__name__}"}, None
        log(f"work_events {day} {src} w{wid}: {v.get('kind')} event={bool(v.get('event'))} reaction={bool(v.get('reaction'))}")
        works.append({"source": src, "work_id": wid, "key": key, **v})
    return {"day": day.isoformat(), "works": works, "made": made, "pending": pending, "asked": asked,
            "seconds": round(time.monotonic() - t0, 1)}


def save(conn, day: date, out: dict) -> None:
    """その日の記録を 1 行に置き換える（画面は最新の 1 行を読む。古い行を残さない）。"""
    ih = hashlib.sha256(json.dumps([w.get("key") for w in out["works"]]).encode()).hexdigest()[:16]
    from game_signal_scout.repositories import job as job_repo
    job_repo.replace_artifact(conn, JOB, day, ih, JOB, out)
    conn.commit()


def step(conn, cfg: dict, should_stop=lambda: False, llm=None, log=print) -> list[dict]:
    """worker の 1 回: 確定した最新の日から前へ、作り直しの要る作品を合わせて max_works まで作り、変わった日だけ保存する。"""
    from datetime import timedelta
    from game_signal_scout.signal import content, movement
    ec = cfg.get("work_events") or {}
    from game_signal_scout.repositories import observation as observation_repo
    top = observation_repo.latest_complete_day(conn)[0]
    conn.rollback()
    if top is None:
        return []
    budget, out = int(ec["max_works"]), []
    for d in [top - timedelta(days=i) for i in range(int(ec["days_back"]) + 1)]:
        if budget <= 0 or should_stop():
            break
        vc = content.day_ctx(cfg, d)
        try:
            mv = movement.analyze(vc, d)
        finally:
            vc.conn.close()
        prev = latest(conn, d)
        r = generate_day(conn, cfg, d, mv, prev, llm=llm, log=log, max_new=budget, should_stop=should_stop)
        budget -= r["made"]
        if r["made"] or prev is None or len(r["works"]) != len(prev.get("works") or []):
            save(conn, d, r)
        out.append({k: r[k] for k in ("day", "made", "pending", "asked", "seconds")})
    return out


def latest(conn, day: date) -> dict | None:
    from game_signal_scout.repositories import job as job_repo
    o = job_repo.latest_artifact(conn, JOB, day)
    conn.rollback()
    return o


def _links(conn, source: str, uris: list[str]) -> dict[str, str]:
    """発言の ID → 元の投稿の公開の URL（取得元の permalink。https の形だけ）。消えた投稿・公開してよいと言わない投稿は含めない。"""
    from game_signal_scout.sources import factory
    from game_signal_scout.signal.content import QUOTE_URL
    if not uris:
        return {}
    rows = foundation_repo.list_utterance_items(conn, source, uris)
    ad = factory.reader_for(source)
    ok = ad.quotable(conn, list({r[1] for r in rows})) if ad else set()
    conn.rollback()
    out = {}
    for uid, item, url in rows:
        link = factory.permalink(source, item, url) if item in ok else None
        if link and QUOTE_URL.match(link):
            out[uid] = link
    return out


def for_rows(conn, day: date) -> dict[tuple[str, int], dict]:
    """画面用: （取得元・作品）→ 出来事と反応（確かめて通ったものだけ）と、根拠の投稿への link（公開してよい・消えていない投稿の permalink だけ）。
    why = 中心の出来事を書かなかった理由（mixed = 別々の話題が混ざっている / unclear = 投稿から分からない / few_people = 1 人だけ /
    no_text = 行の投稿の本文を読めない〔本文を保存しない取得元など〕）。"""
    out = {}
    for w in (latest(conn, day) or {}).get("works") or []:
        links = _links(conn, w["source"], [u for x in (w.get("event"), w.get("reaction")) if x for u in x["uris"]])

        def view(x):
            if not x or not x.get("en"):
                return None
            return {"ja": x["ja"], "en": x["en"], "people": x["people"], "post_url": next((links[u] for u in x["uris"] if u in links), None)}
        why = "no_text" if not w.get("read") else next((e for e in w.get("event_rejected") or [] if e in ("mixed", "unclear", "few_people")), None)
        # ファン同士の話題（discussion）は外の出来事ではなく反応そのもの: 出来事の行を出さず、反応の行だけ（同じ中身を 2 行にしない）
        out[(w["source"], int(w["work_id"]))] = {"kind": w.get("kind"), "read": w.get("read"), "own": w.get("own"), "why": why,
                                                 "event": None if w.get("kind") == "discussion" else view(w.get("event")), "reaction": view(w.get("reaction"))}
    return out
