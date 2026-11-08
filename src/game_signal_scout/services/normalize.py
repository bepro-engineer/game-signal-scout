"""正規化の Service: 取得元の形の項目を、分析に使う共通の行にする。どの正規化を使うかは取得元の記述（config/sources.toml の normalizer）で選ぶ
（取得元の名前で分岐しない）。normalizer のない取得元は正規化しない。正規化は種類ごとで、取得元の形を共通の形へ直すのは
その取得元のクラスの hook（sources/contract.SourceReader の voice・profile・report）。

- voices: 発言 → player_post（宣伝などの印・言語・ストアのリンクの app ID・作品の同定は、どの取得元にも同じに当てる）
- profiles: 作品の情報 → game_profile
- reports: 動作の報告 → player_report
- attributes: 作品の属性 → game_attribute（日本語の UI・字幕・音声、開発元、開発元の国・地域。出典・取得の時刻つき）
- upcoming・assets・activity: これから発売・作品の画像・遊ばれている規模（取得元が共通の形で渡す）

1 つの取得元の正規化の失敗で、ほかの取得元を止めない（取得元ごとに記録する。Anime と同じ）。
"""
from __future__ import annotations

import json

import re

from game_signal_scout.repositories import report as repo

def _reader(source: str, settings: dict | None = None):
    """取得元のクラス（記述の adapter）。取得元の形を共通の形へ直す hook（voice・profile・report）を持つ。"""
    from game_signal_scout.sources import factory
    from game_signal_scout.sources.contract import SourceReader
    spec = (settings or {}).get("adapter")
    try:
        return factory.reader_class(source, {source: {"adapter": spec}} if spec else None)
    except ValueError:   # 記述のない取得元（項目がすでに共通の形）: 直さずに使う
        return SourceReader


def normalize_all(conn, cfg: dict | None = None) -> dict:
    """記述に normalizer のある取得元をすべて正規化する。counts: 取得元ごとの入れた数、errors: 失敗した取得元と誤り。"""
    import importlib
    from game_signal_scout.sources import factory
    cfg = cfg or factory.load_sources_config()
    out, errors = {}, {}
    for name, sc in cfg.items():
        ref = sc.get("normalizer") if isinstance(sc, dict) else None
        if not ref:
            continue
        mod, fn = ref.split(":")
        try:
            out[name] = getattr(importlib.import_module(mod), fn)(conn, name, sc)
        except Exception as e:  # noqa: BLE001 — 1 つの取得元の失敗で、ほかの取得元を止めない
            conn.rollback()
            errors[name] = f"{type(e).__name__}: {str(e)[:200]}"
    if errors and not out:
        raise RuntimeError(f"すべての取得元の正規化に失敗: {errors}")
    # 今使っていない取得元（無効・利用条件で停止）の保存済みの発言は、どの集計・発見・画面にも使わない（印で外す。消さない）
    from game_signal_scout import source_terms
    from game_signal_scout.repositories import post as post_repo
    in_use = [k for k, sc in cfg.items() if isinstance(sc, dict) and sc.get("enabled", True) and source_terms.allowed(k)]
    with conn.transaction():
        out_of_use = post_repo.mark_not_in_use(conn, in_use)
    conn.commit()
    return {"counts": out, "errors": errors, **({"marked_not_in_use": out_of_use} if out_of_use else {})}


def reports(conn, source: str, settings: dict | None = None) -> int:
    """動作の報告 → player_report（取得元の形は、その取得元のクラスの report が直す）。"""
    return normalize(conn, source, settings=settings)


STEAM_APP = re.compile(r"store\.steampowered\.com/app/(\d{1,10})")   # ストアのリンクの app ID（どの取得元の本文にも同じに当てる）


def voices(conn, source: str, settings: dict | None = None, batch: int = 2000) -> int:
    """どの取得元の発言も同じ手順で player_post にする（取得元の payload: author・text・lang、作品が決まるなら appid、ストアのリンクがあれば steam_appids）。
    作品の辞書は作品の情報の題名（各言語の表示名を含む）。payload に appid があれば、作品は取得元で決まる（matched_by = source）。取得元の名前で分けない。"""
    from game_signal_scout.repositories import post as post_repo
    from game_signal_scout.services.identify import TitleIndex, identify
    from game_signal_scout.discovery.flags import flags_for
    from game_signal_scout.discovery.text import PostText
    from game_signal_scout.languages_detect import detect as detect_lang
    settings = settings or {}
    from game_signal_scout.services.identify import version as id_version
    titles = post_repo.known_titles(conn)
    args = (settings.get("ambiguous_titles") or [], settings.get("title_context_words") or settings.get("context_words") or [],
            int(settings.get("min_title_chars", 8)), bool(settings.get("game_only")))
    ver = id_version(titles, *args)
    # 同定の規則・作品の辞書が変わったら、本文の題名で同定する発言を今の版で作り直す（Anime の §5.3・§21）
    from game_signal_scout import source_terms
    with conn.transaction():
        post_repo.forget_stale_identification(conn, source, ver)
        post_repo.mark_terms_excluded(conn, source, source_terms.excluded_hosts(source))   # 利用条件で禁止のサイトの発言を外す（#3 G2）
    conn.commit()
    index = None
    total = 0
    shape = _reader(source, settings).voice
    banned = [f"//{h}" for h in source_terms.excluded_hosts(source)]
    while rows := post_repo.unnormalized(conn, source, batch):
        if index is None:
            index = TitleIndex(titles, args[0], args[1], args[2], game_only=args[3])
        out = []
        for item_id, occurred_at, raw in rows:
            p = shape(item_id, raw)
            # どの取得元の発言にも同じ処理（取得元の名前・種類で分けない。Adapter が渡すのは取得元の形を直した素材だけ）:
            # ① 本文・リンクの中のストアのリンクの app ID ② 宣伝・告知・ニュースなどの印 ③ 言語（取得元が示さなければ共通の判定器）
            text, link = p.get("text") or "", p.get("link") or p.get("url") or ""
            p = {**p, "steam_appids": sorted({m for s in (text, link) for m in STEAM_APP.findall(s)})}
            flags = list(dict.fromkeys([*(p.get("flags") or []), *flags_for(PostText(text=text, link_title=p.get("link_title") or "", tags=p.get("tags") or [], has_link=bool(p.get("link"))))]))
            if any(b in str(item_id) or b in str(p.get("url") or "") for b in banned):
                flags.append("terms_excluded")
            lang = p.get("lang") or detect_lang(text)
            # 作品が取得元で決まる発言（作品ごとの掲示板・作品のページのコメント）は、その作品。ほかは本文から同定する
            appid, title, how = (str(p["appid"]), None, "source") if p.get("appid") else identify(p, index)
            out.append({"source": source, "item_id": item_id, "at": occurred_at, "author": p.get("author") or "", "lang": lang,
                        "appid": appid, "title": title, "matched_by": how, "flags": flags, "text": text,
                        "url": p.get("url") if str(p.get("url") or "").startswith("https://") else None, "id_version": ver,
                        "stance": p.get("stance"), "playtime_minutes": p.get("playtime_minutes")})
        with conn.transaction():
            total += post_repo.insert(conn, out)
        conn.commit()
    return total


def profiles(conn, source: str, settings: dict | None = None, batch: int = 500) -> int:
    """作品の情報 → game_profile（取得元の形は、その取得元のクラスの profile が直す）。作品でない項目は飛ばす（行を作らない）。"""
    from game_signal_scout.repositories import catalog
    row_of = _reader(source, settings).profile
    total, seen = 0, set()
    while rows := [r for r in catalog.unnormalized(conn, source, batch) if r[0] not in seen]:
        out = []
        for item_id, received_at, p in rows:
            seen.add(item_id)
            if row := row_of(item_id, received_at, p):
                out.append({**row, "source": source})
        with conn.transaction():
            total += catalog.upsert(conn, out)
        conn.commit()
    return total


def upcoming(conn, source: str, settings: dict | None = None, batch: int = 1000) -> int:
    """これから発売の作品の一覧 → game_upcoming。"""
    from datetime import date
    from game_signal_scout.repositories import catalog
    total = 0
    while rows := catalog.upcoming_rows(conn, source, batch):
        out = [(p["appid"], date.fromisoformat(p["day"]), source, item_id, p.get("rank")) for item_id, p in rows]
        with conn.transaction():
            total += catalog.insert_upcoming(conn, out)
        conn.commit()
    return total


def assets(conn, source: str, settings: dict | None = None, batch: int = 1000) -> int:
    """作品の画像の場所 → game_assets（版が変われば置き換える）。場面の画像は作品の属性 shots へ。"""
    from game_signal_scout.repositories import catalog
    total = 0
    while rows := catalog.asset_rows(conn, source, batch):
        with conn.transaction():
            total += catalog.upsert_assets(conn, [(p["appid"], source, item_id, p.get("capsule"), p.get("hero"), received_at) for item_id, received_at, p in rows])
            # 場面の画像（スクリーンショット）は作品の属性 shots に（画面の大きな絵・面白さの札・発見のカード）
            catalog.upsert_attributes(conn, [(p["appid"], "shots", source, item_id, p["shots"], received_at) for item_id, received_at, p in rows if p.get("shots")])
        conn.commit()
    return total


def activity(conn, source: str, settings: dict | None = None, batch: int = 1000) -> int:
    """遊ばれている規模（Steam の順位）→ game_activity。"""
    from datetime import date
    from game_signal_scout.repositories import catalog
    total = 0
    while rows := catalog.activity_rows(conn, source, batch):
        out = [(p["appid"], date.fromisoformat(p["day"]), source, item_id, p.get("rank"), p.get("prev_rank"), p.get("peak_players")) for item_id, p in rows]
        with conn.transaction():
            total += catalog.insert_activity(conn, out)
        conn.commit()
        if len(rows) < batch:
            break
    return total


def normalize(conn, source: str, batch: int = 5000, settings: dict | None = None) -> int:
    """動作の報告: まだ正規化していない項目をすべて正規化する。入れた数（何度流しても、新しい項目がなければ 0）。"""
    row_of = _reader(source, settings).report
    total = 0
    while rows := repo.unnormalized(conn, source, batch):
        with conn.transaction():
            total += repo.normalize_new(conn, source, (row_of(i, p) for i, p in rows))
        conn.commit()
    return total


def attributes(conn, source: str, settings: dict | None = None, batch: int = 500) -> int:
    """作品の属性 → game_attribute（取得元の形は、その取得元のクラスの attributes が直す）。"""
    from game_signal_scout.repositories import catalog
    rows_of = _reader(source, settings).attributes
    total = 0
    while rows := catalog.attribute_rows(conn, source, batch):
        out = [(a, k, source, item_id, v, received_at) for item_id, received_at, p in rows for a, k, v in rows_of(item_id, received_at, p)]
        with conn.transaction():
            total += catalog.upsert_attributes(conn, out)
            if not out:
                break
        conn.commit()
        if len(rows) < batch:
            break
    return total
