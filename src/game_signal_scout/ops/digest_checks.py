"""今日の兆しの文章の検査（DB も LLM も使わない純粋な関数）。4 つの区分（構造・根拠との一致・ページの目的との一致・読者への情報価値）で
誤りを返し、LLM への書き直しの指示を作る（ADR 0052。docs/TODAYS-SIGNAL-PAGES.md §0.6）。ops/dashboard_digest の段 6 が使う。"""
from __future__ import annotations

import json
import re

from game_signal_scout.languages import NAMES
from game_signal_scout.ops.digest_verbatim import normalize

LEAD_MAX = {"ja": 56, "en": 140}   # ダッシュボードの 1 文目（見出し）の長さの上限


def cite_pool(f: dict) -> list[dict]:
    """文章に添える引用の候補（主な論点・中心の出来事・言語ごと・違う方向の声 / ほかの論点）。訳の対象。"""
    xs = list(f["excerpts"][:3]) + ([f["anchor"]] if f.get("anchor") else [])
    xs += [b["excerpt"] for b in (f.get("by_lang") or {}).values() if b.get("excerpt")]
    xs += [x for k in ("contrast", "also") if f.get(k) for x in f[k]["excerpts"][:1]]
    return xs


QUOTED = {"ja": re.compile(r"「([^」]+)」"), "en": re.compile(r"[\"“]([^\"”]+)[\"”]")}
BANNED = {"ja": re.compile(r"注目|必見|魅力|ぜひ|でしょう|今後|話題沸騰|ふだんの水準|短い時間に集ま|見ておく価値|さまざまな|小さな変化|重なって"),
          "en": re.compile(r"traction|attention|buzz|must-see|\bwill\b|usual level|in a short time|worth seeing|various titles|small changes", re.I)}
# どこまで言えるか（claim）が many でないときに使えない、全体の傾向に見せる言い方（ADR 0052。少数の声を一般化しない）
GENERAL = {"ja": re.compile(r"プレイヤーの間で|多くの(プレイヤー|人)|続出|相次|殺到|大きな反響|反響を呼|広く|声が上が|意見が出て|声が集ま"),
           "en": re.compile(r"many fans|fans (are|were) (widely|all)|widespread|wave of|across the fandom|fans everywhere|backlash", re.I)}
SPELLED = re.compile(r"\b(two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|several|many|a few)\b", re.I)
CAUSAL = {"ja": re.compile(r"広ま|伝わ|伝播|波及|飛び火|(から|より)[^。、]{0,8}(語|圏)(へ|に)(も)?(移|渡|届)"),
          "en": re.compile(r"spread (from|to|into)|made (its|their) way|carried over|travel+ed (from|to)|jumped (from|to)", re.I)}
ACRONYMS = {"OP", "ED", "PV", "MV", "CM", "BD", "DVD", "TV", "SNS", "AI", "CG", "OVA", "OAD", "BGM", "VTuber", "SF", "Blu", "ray"}

NUM = re.compile(r"\d+(?:\.\d+)?")
UNIT_NUM = re.compile(r"(第?\d+(?:話|期|巻|章|部|日目|周年|年|回|期目|クール|シーズン))")


def _source_text(f: dict) -> str:
    """根拠の原文（その論点・違う方向の声・ほかの論点の投稿の本文）と、確かめた訳・作品名。LLM の部品の言葉はここにあるものだけ。"""
    return " ".join(list(f.get("source_texts") or []) + [x["text"] for x in cite_pool(f)])


def _grounding_errors(p: dict, f: dict, loc: str, meanings: dict) -> list[str]:
    """LLM の部品の事実の言葉（数・話数・ラテン文字の固有名・『』の中の語）が原文・訳・作品名にあるか（数字を一律に禁じない。2026-10-16:
    10/15 の「第3話」は 4 件の投稿にあったのに、数字の禁止で落ちていた）。人数は規模の言葉（fans_label）だけに認める。"""
    src = _source_text(f) + " " + " ".join(meanings.values()) + " " + " ".join(w for x in f["works"] for w in x.values() if w)
    srcn = normalize(src)
    e = []
    for k in ("point", "contrast_point", "also_point"):
        t = str((p or {}).get(k) or "")
        if not t:
            continue
        work_free = t
        for x in f["works"]:
            for w in x.values():
                if w:
                    work_free = work_free.replace(w, " ")
        for m in UNIT_NUM.finditer(work_free):
            num = re.search(r"\d+", m.group(1)).group(0)
            if not re.search(rf"(?<!\d){num}(?!\d)\s*(話|期|巻|章|部|日目|周年|年|回|クール|シーズン|th|st|nd|rd|episode|ep)", src, re.I) and \
               not re.search(rf"(episode|ep\.?|season|part|第)\s*{num}(?!\d)", src, re.I):   # 英語は番号が後ろ（season 2 → 第2シーズン。10/22）
                e.append(f"not_in_source:{m.group(1)}")
            work_free = work_free.replace(m.group(1), " ")
        for n in NUM.findall(work_free):
            if not re.search(rf"(?<!\d){re.escape(n)}(?!\d)", src):
                e.append(f"not_in_source:{n}")
        for q in re.findall(r"『([^』]+)』", t):
            if q not in (w for x in f["works"] for w in x.values()) and normalize(q) not in srcn:
                e.append(f"not_in_source:{q[:20]}")
    return list(dict.fromkeys(e))


def _foreign_words(text: str, f: dict, loc: str) -> list[str]:
    """読者の言語に訳されていない言葉（日本語の文章の中のラテン文字の語・英語の文章の中の日本語）。作品名・略語・日本語のプレイヤー自身が書いた語は除く。"""
    t = text
    for x in f["works"]:
        for w in x.values():
            if w:
                t = t.replace(w, " ")
    if loc == "ja":
        ja_src = " ".join(x["text"] for x in cite_pool(f) if x["lang"] == "ja") + " " + " ".join(s for s in f.get("source_texts_ja") or [])
        return [w for w in re.findall(r"[A-Za-z][A-Za-z'\-]{2,}", t) if w not in ACRONYMS and w.lower() not in ja_src.lower()]
    return re.findall(r"[぀-ヿ一-鿿]+", t)


def validate(out: dict, f: dict, loc: str, all_work_names: set[str], parts: dict | None = None) -> dict:
    """文章の検査（4 区分。classify）。errors は書き直しの指示にそのまま使う。"""
    sents = [str(s).strip() for s in ((out or {}).get("sentences") or []) if str(s).strip()]
    cites = (out or {}).get("cites") or []
    p = parts or {}
    meanings = {str(m.get("quote")): str(m.get("meaning") or "") for m in (p.get("meanings") or []) if isinstance(m, dict)}
    e: list[str] = []
    spread = f.get("page") == "spread"
    work = f["works"][0][loc]
    full = (" " if loc == "en" else "").join(sents)
    a = f.get("assessment") or {}
    claim = a.get("claim")
    if not sents or len(sents) < 2:
        e.append("sentence_count")
    if work not in (sents[0] if sents else ""):
        e.append("work_name_missing")
    if loc == "ja" and sents and f"「{work}」" not in sents[0]:
        e.append("work_name_brackets")
    if any(not re.search(r"[。！？.!?]$", s) or len(s) < 12 for s in sents):
        e.append("fragment")
    if not spread and sents and len(sents[0]) > LEAD_MAX[loc]:
        e.append("lead_too_long")
    # どこまで言えるか: 少数の声を全体の傾向に見せない（見出しに規模・一般化の言い方）
    if not spread and claim and claim != "many" and sents:
        from game_signal_scout.ops.finding_assess import fans_label
        if fans_label(f["people_on_topic"], loc) not in sents[0]:
            e.append("scale_missing")
        if GENERAL[loc].search(full):
            e.append("overgeneralized")
    if not spread and not f.get("sides") and sents and not re.search(r"プレイヤー" if loc == "ja" else r"\bplayers?\b", sents[0], re.I):
        e.append("lead_without_fans")
    # 根拠との一致: 文章の数は記録の数だけ・部品の事実の言葉は原文にある・訳されていない言葉がない・引用は記録の抜粋で訳がある
    allowed = {f["people_on_topic"]} | set((f.get("topic_lang_counts") or {}).values()) | {b["people"] for b in (f.get("by_lang") or {}).values()}
    allowed.add(f["people_on_topic"] - sum((f.get("topic_lang_counts") or {}).values()))   # 言語を判定できない投稿の人数
    allowed |= {f[k]["people_on_topic"] for k in ("contrast", "also") if f.get(k)}
    allowed |= {x.get("people") for x in f.get("added") or [] if x.get("people")} | ({2} if spread or (a.get("change") or {}).get("kind") == "new_language" else set())
    if f.get("sides"):
        allowed |= {f["sides"]["for"], f["sides"]["against"]}
    ch = a.get("change") or {}
    allowed |= {x for x in (ch.get("n"), ch.get("streak")) if x} | ({int(ch["base"] + 0.5)} if ch.get("base") is not None and ch.get("base") >= 1 else set())
    full_wo = UNIT_NUM.sub(" ", re.sub(r"(episode|ep\.?|season|part)\s*\d+|\bday\s*\d+(?= after)", " ", full.replace("の1日", "の").replace("1日あたり", ""), flags=re.I))
    for x in f["works"]:
        for w in x.values():
            full_wo = full_wo.replace(w or "\0", " ")
    # LLM の部品の中の、原文・訳にある数（年・作品の番号など。部品の根拠の検査 _grounding_errors と同じ規則）は、人数でなければ認める
    # （2026-10-17: 英語の「1994 anime movie」が、原文に 1994 があるのに文章全体の数の検査で落ち、日本語だけ合格 → 両方とも文章のない日になった）
    parts_text = " ".join(str(p.get(k) or "") for k in ("lead", "point", "contrast_point", "also_point"))
    src_nums = set(NUM.findall(_source_text(f) + " " + " ".join(meanings.values())))
    people_nums = set(re.findall(r"(\d+)\s*(?:人|fans?|people)", full))
    for n in re.findall(r"\d+", full_wo):
        if int(n) not in allowed and not (n in src_nums and n in parts_text and n not in people_nums):
            e.append(f"number_not_in_finding:{n}")
    e += _grounding_errors(p, f, loc, meanings)
    fw = _foreign_words(full, f, loc)
    if fw:
        e.append(f"untranslated_word:{fw[0]}")
    names_all = {w for x in f["works"] for w in x.values() if w} | set(all_work_names or [])
    srcn = normalize(_source_text(f) + " " + " ".join(meanings.values()) + " " + (f["topic"].get(loc) or ""))
    for q in QUOTED[loc].findall(full) + re.findall(r"『([^』]+)』", full):
        if q not in names_all and normalize(q) not in srcn:
            e.append(f"not_in_source:{q[:20]}")   # 文章の中で引用した言葉は、原文・訳にあるものだけ（外国語の原文は訳されていない語の検査で落ちる）
    pool = {normalize(x["text"]) for x in cite_pool(f)}
    for c in cites:
        if normalize(c["quote"]) not in pool:
            e.append(f"quote_not_in_finding:{c['quote'][:30]}")
        if c["lang"] != loc and not c.get("meaning"):
            e.append(f"quote_without_meaning:{c['quote'][:20]}")
    if not any(c["role"] in ("main", "for", "against") for c in cites):
        e.append("no_main_quote")
    if f.get("sides") and {c["role"] for c in cites} & {"for", "against"} != {"for", "against"}:
        e.append("one_side_only")
    # ページの目的との一致
    if CAUSAL[loc].search(full):
        e.append("causal_claim")
    if loc == "ja" and re.search(r"海外|国内|(国|地域)の(プレイヤー|人)", full):
        e.append("language_as_country")
    if loc == "en" and SPELLED.search(full):
        e.append("spelled_number")
    if spread:
        k = 0 if loc == "ja" else 1
        names_ok = {NAMES[c][k] for c in f["languages"] if c in NAMES}
        for c, nm in NAMES.items():
            if c != "und" and nm[k] in full and nm[k] not in names_ok:
                e.append(f"language_not_in_finding:{nm[k]}")
        if sents and not all(NAMES[x["code"]][k] in sents[0] for x in f["added"] if x["code"] in NAMES):
            e.append("added_language_missing")
    # 読者への情報価値
    plain = full
    for t in [f["topic"][loc]] + [f[k]["topic"][loc] for k in ("contrast", "also") if f.get(k)]:
        plain = plain.replace(t or "\0", "")
    src_all = _source_text(f) + " " + " ".join(meanings.values())
    bad_words = [m.group(0) for m in BANNED[loc].finditer(plain) if m.group(0) not in src_all]   # プレイヤーの原文にある語（「魅力的なキャラ達」）は宣伝の語にしない
    if bad_words:
        e.append(f"banned_phrase:{bad_words[0]}")   # 落ちた語を書き直しの指示に添える（10/23: 論点名の「魅力」を 4 回とも書き続けた）
    for k in ("point", "contrast_point", "also_point"):
        if k in p and (f.get(k.replace("_point", "")) or k == "point") and not str(p.get(k) or "").strip():
            e.append(f"parts_{k}_missing")
        if loc == "ja" and re.search(r"[うくすつぬむゆるぐぶ]$|(た|ない|てる|ている)$", str(p.get(k) or "").strip()):
            e.append(f"point_not_noun:{k}")   # 「〜について書いたプレイヤー」に入る名詞句でない（「〜を好むについて」: 10/11）
        if re.search(r"について書|プレイヤーが" if loc == "ja" else r"\bfans? (who|wrote|writing)\b|\bwrote about\b", str(p.get(k) or ""), re.I):
            e.append(f"point_repeats_frame:{k}")   # 見出しの枠の言葉を point に入れた（10/24: "wrote about players who wrote about fanart"）
    return {"passed": not e, "errors": list(dict.fromkeys(e)), "sentences": [{"text": s} for s in sents], "cites": cites}


CHECK_CLASS = {   # 検査の区分。合格 = 4 区分すべてに誤りがない
    "structure": ("sentence_count", "fragment", "work_name_brackets", "lead_too_long", "parts_point_missing",
                  "parts_contrast_point_missing", "parts_also_point_missing", "work_name_missing"),
    "evidence": ("number_not_in_finding", "not_in_source", "quote_not_in_finding", "quote_without_meaning", "no_main_quote", "one_side_only",
                 "ja_en_mismatch", "untranslated_word", "llm_error"),
    "purpose": ("causal_claim", "language_as_country", "language_not_in_finding", "added_language_missing", "scale_missing", "overgeneralized"),
    "value": ("lead_without_fans", "banned_phrase", "spelled_number", "point_not_noun", "point_repeats_frame"),
}

def classify(errors: list[str]) -> dict[str, list[str]]:
    out = {k: [] for k in CHECK_CLASS}
    for x in errors:
        code = x.split(":")[0]
        out[next((k for k, v in CHECK_CLASS.items() if code in v), "structure")].append(x)
    return out


FIX = {   # 書き直しの指示（LLM が書くのは論点の名詞句 point・contrast_point・also_point だけ。見出しは規則で組む）
    "ja": {"lead_too_long": "見出しが 56 字を超える。point を、次の字数以内の短い名詞句にする",
           "not_in_source": "原文にない数・話数・名前を書かない。", "untranslated_word": "外国語の言葉をそのまま書かず、日本語で書く（人名・作中の固有名詞は excerpts の meaning の表記。カタカナなど）。",
           "causal_claim": "ある言語から別の言語へ広まった・伝わったと書かない。", "language_as_country": "言語圏を国・地域（海外・国内）として書かない。",
           "banned_phrase": "次の語を point などに書かず、原文に書かれた具体的な言葉に言い換える", "overgeneralized": "人数を大きく見せる言い方（プレイヤーの間で・多くの・続出）を使わない。",
           "parts_point_missing": "point を書く。", "parts_contrast_point_missing": "contrast_point を書く。", "parts_also_point_missing": "also_point を書く。",
           "number_not_in_finding": "point に人数・数字を書かない（原文にある話数だけ）。",
           "point_not_noun": "point などは「〜について書いたプレイヤー」に入る名詞句にする（動詞で終えない）。",
           "point_repeats_frame": "point に「〜について書いた」「プレイヤーが」を入れない（見出しの枠は組み立て側が付ける）。"},
    "en": {"lead_too_long": "The headline is over 140 characters. Make point a shorter noun phrase within this many characters",
           "not_in_source": "No numbers, episode numbers or names that are not in the posts.", "untranslated_word": "Do not leave Japanese words untranslated.",
           "causal_claim": "Do not say the topic spread or moved between languages.", "banned_phrase": "Do not use this word; rephrase it with the concrete words in the posts",
           "overgeneralized": "Do not make it sound bigger (no many fans, widespread, backlash).",
           "parts_point_missing": "Write point.", "parts_contrast_point_missing": "Write contrast_point.", "parts_also_point_missing": "Write also_point.",
           "spelled_number": "Write numbers as digits.", "number_not_in_finding": "No numbers in point other than episode numbers in the posts.",
           "point_repeats_frame": "Do not put \"fans who wrote about\" or \"wrote about\" in point; the headline frame is added for you. Give only the subject."}}

def feedback_for(errors: list[str], loc: str, previous: dict | None = None) -> str:
    """書き直しの指示。前の部品をそのまま示す（指摘の語だけでは、LLM が論点名の言葉を書き続けた: 10/23 の「魅力」を 4 回）。"""
    out = []
    if previous:
        shown = json.dumps({k: previous.get(k) for k in ("point", "contrast_point", "also_point") if previous.get(k)}, ensure_ascii=False)
        out.append((f"前の部品 {shown} を直す:" if loc == "ja" else f"Fix your previous parts {shown}:"))
    for x in errors[:8]:
        code, _, arg = x.partition(":")
        if code in FIX[loc]:
            out.append(FIX[loc][code] + (f"（{arg}）" if arg and loc == "ja" else (f" ({arg})" if arg else "")))
        else:
            out.append(x)
    return " ".join(dict.fromkeys(out))


YEAR_MIN, YEAR_MAX = 1900, 2100


def count_numbers(text: str, loc: str) -> list[int]:
    """文章の数字（日英で同じ事実を書いているかの照合用。話数などの単位つきの数と、年〔日本語は「1994年」で単位つき、英語は裸の 1994〕は除く）。"""
    return sorted(int(n) for n in re.findall(r"\d+", UNIT_NUM.sub(" ", re.sub(r"(episode|ep\.?|season|part)\s*\d+|\bday\s*\d+(?= after)", " ", text.replace("の1日", "の"), flags=re.I)))
                  if not YEAR_MIN <= int(n) <= YEAR_MAX)
