"""公開用の文書を作る Service（書く側）。Anime の publication/publishing の publish をそのまま移植し、中身の作り方だけ Game に替えた。

- 材料の版（input_version）が最後に作った回と同じなら作らない（force なら作る）。
- 作った中身が検査（publication/content.audit）に通らなければ表を変えない（前の回のまま）。記録は public_build。
- 同時に 2 つ作らない（advisory lock）。
- ここでの「公開」は、表 public_document に置き換えること。Viewer は自分の機械だけで待ち受けていて、外への公開はしていない。
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime, timezone

from game_signal_scout.publication import content
from game_signal_scout.repositories import job as job_repo, public_document as public_document_repo, report, session

log = logging.getLogger(__name__)
LOCK = "publish"          # repositories/session が game_signal_scout: を付ける


class PublishRejectedError(Exception):
    """作った内容が公開の前の検査に通らない（表は前の回のまま）。"""


def code_version() -> str:
    """文書を作るプログラム（publication/content.py・themes.py）の中身の指紋。Game には Anime の「反映のときに force で作り直す」手順がないので、
    プログラムを替えたら次の回で作り直されるように、材料の版に含める。"""
    import hashlib
    from pathlib import Path
    h = hashlib.sha256()
    for name in ("content.py", "themes.py"):
        h.update((Path(__file__).parent / name).read_bytes())
    from game_signal_scout import config as _cfg
    pkg = Path(__file__).parent.parent
    for f in sorted((pkg / "signal").glob("*.py")) + [pkg / "ops" / "work_display.py", pkg / "catalog" / "profile.py", pkg / "languages.py"] + [
            _cfg.CONFIG / n for n in ("daily.toml", "pages.toml", "signal_cards.toml", "language_areas.toml")]:
        h.update(f.read_bytes())   # Anime の流用の文書（signal/）と、その設定を替えたら作り直す
    from game_signal_scout.repositories import insight as insight_repo   # noqa: F401  （AI の読み取りは材料の版に入る: input_version）
    return h.hexdigest()[:12]


def input_version(conn, cfg: dict) -> str:
    """材料の版: 分析の規則の版・最後に成功した正規化と分析の時刻・最新の発言の時刻・作品の情報の最新の時刻・文書を作るプログラムの指紋。どれかが変われば作り直す。"""
    from game_signal_scout.repositories import post
    from game_signal_scout.repositories import insight
    from game_signal_scout.repositories import catalog
    newest_insight = insight.newest_generated_at(conn)
    return "|".join(str(x) for x in (cfg["analysis"]["version"], job_repo.last_ok_finished_at(conn, "normalize"),
                                       job_repo.last_ok_finished_at(conn, "analyze"), post.newest_at(conn), newest_insight,
                                       catalog.newest_catalog_at(conn), code_version()))   # 作品の情報・画像・属性が新しくなれば作り直す


def build_documents(conn, cfg: dict) -> tuple[dict[str, object], dict]:
    t0 = time.perf_counter()
    docs = content.build(conn, cfg["analysis"]["version"])
    conn.rollback()
    from game_signal_scout.signal import publishing as signal_publishing   # Anime の画面の流用が読む文書（day/・pages・search・soon・work/・days）
    # 画面の文書（day/・pages・search・soon・work/・days）が作れない・検査に通らないときは、公開を止めて前の回のままにする
    # （Anime の §16.1・REQ-OPS-006。2026-11-08 Issue #3: 例外を握りつぶして続け、画面の文書が消えうる形だった）
    sdocs, sstats = signal_publishing.build_documents(conn, cfg)
    docs.update(sdocs)
    conn.rollback()
    if sstats.get("audit"):
        raise PublishRejectedError("画面の文書の検査に通らなかった: " + "; ".join(str(x) for x in sstats["audit"][:10]))
    if not any(k.startswith("day/") for k in sdocs) or "days" not in sdocs:
        raise PublishRejectedError("画面の文書（日・日の一覧）が空")
    problems = content.audit(docs)
    if problems:
        raise PublishRejectedError("公開用の文書の検査に通らなかった: " + "; ".join(problems[:10]))
    newest = report.newest_report_at(conn)
    conn.rollback()
    docs_latest = newest.date().isoformat() if newest else None
    return docs, {"seconds": round(time.perf_counter() - t0, 1), "games": len(docs) - 1, "latest": docs_latest}


def publish(read_conn, write_conn, cfg: dict, trigger: str, force: bool = False) -> dict:
    """材料が変わっていれば（force なら必ず）公開用の文書を作って置き換える。
    返り値: {status: published / unchanged / rejected / failed / busy / daily_running, build_id?, latest?, ...}。"""
    if trigger == "interval" and job_repo.is_daily_run_active(write_conn, int(cfg["daily_run"]["max_running_hours"])):
        write_conn.rollback()
        return {"status": "daily_running"}
    if not session.try_advisory_lock(write_conn, LOCK):
        write_conn.rollback()
        return {"status": "busy"}
    try:
        v = input_version(read_conn, cfg)
        read_conn.rollback()
        last = public_document_repo.get_last_published_build(write_conn)
        if not force and last and last["input_version"] == v:
            write_conn.rollback()
            return {"status": "unchanged", "build_id": last["build_id"], "latest": str(last["latest_day"])}
        now = datetime.now(timezone.utc)
        build_id = public_document_repo.create_build(write_conn, v, trigger, now)
        write_conn.commit()
        try:
            docs, stats = build_documents(read_conn, cfg)
        except Exception as e:  # noqa: BLE001 — 作れない・検査に通らない: 表は前の回のまま。理由は記録に残す
            read_conn.rollback()
            status = "rejected" if isinstance(e, PublishRejectedError) else "failed"
            public_document_repo.finish_build(write_conn, build_id, status, datetime.now(timezone.utc), detail={"error": f"{type(e).__name__}: {str(e)[:1000]}"})
            write_conn.commit()
            log.error("公開用の文書を置き換えなかった（%s）: %s", status, e)
            return {"status": status, "build_id": build_id, "error": f"{type(e).__name__}: {str(e)[:300]}"}
        latest = date.fromisoformat(stats["latest"]) if stats["latest"] else None
        done = datetime.now(timezone.utc)
        public_document_repo.replace_documents(write_conn, build_id, docs, done)
        public_document_repo.finish_build(write_conn, build_id, "published", done, latest, len(docs), stats)
        write_conn.commit()
        return {"status": "published", "build_id": build_id, "latest": stats["latest"], "documents": len(docs), **stats}
    finally:
        try:
            session.advisory_unlock(write_conn, LOCK)
            write_conn.commit()
        except Exception:  # noqa: BLE001 — 接続が切れていれば lock も外れている
            pass
