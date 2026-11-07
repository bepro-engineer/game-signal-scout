"""公開用の文書の Service（publication/publishing。Anime の tests/test_web_publishing を移植）: 材料の版が変わったときだけ作り、
検査に通った文書だけを表 public_document に置き換える。検査に通らなければ表は前の回のまま。この回にない鍵は消える。
日中の定期の起動（interval）は日次処理の実行中は作らない。中身の作り方（build_documents）は架空に差し替える。"""
from game_signal_scout.publication import content, publishing
from game_signal_scout.repositories import job as job_repo, public_document as public_document_repo
from game_signal_scout.web import public_content

CFG = {"daily_run": {"max_running_hours": 6}, "analysis": {"version": "t"}}


def _docs(latest: str, games=("1",)):
    return {"overview": {"events": [{"appid": g} for g in games]}, **{f"game/{g}": {"appid": g, "events": []} for g in games}}, \
        {"seconds": 1, "latest": latest}


def _setup(monkeypatch, version, build):
    monkeypatch.setattr(publishing, "input_version", lambda conn, cfg: version[0])
    monkeypatch.setattr(publishing, "build_documents", lambda conn, cfg: build[0]())


def test_publish_only_when_the_input_changes_and_keep_the_previous_documents_when_rejected(conn, monkeypatch):
    version, build = ["a"], [lambda: _docs("2031-05-20", ("1", "2"))]
    _setup(monkeypatch, version, build)
    r = publishing.publish(conn, conn, CFG, "daily")
    assert r["status"] == "published" and r["latest"] == "2031-05-20" and r["documents"] == 3
    assert public_document_repo.get_document(conn, "game/2") == {"appid": "2", "events": []} and public_content.get_health(conn)["latest"] == "2031-05-20"

    assert publishing.publish(conn, conn, CFG, "interval")["status"] == "unchanged"   # 材料が同じなら作らない

    version[0] = "b"
    build[0] = lambda: (_ for _ in ()).throw(publishing.PublishRejectedError("公開用の文書の検査に通らなかった: game/1"))
    r = publishing.publish(conn, conn, CFG, "interval")
    assert r["status"] == "rejected"
    assert public_document_repo.get_document(conn, "game/2") is not None                 # 表は前の回のまま
    h = public_content.get_health(conn)
    assert h["ok"] and h["stale"] is True and "game/1" not in str(h)                      # 理由は返さない

    build[0] = lambda: _docs("2031-05-21", ("1",))
    assert publishing.publish(conn, conn, CFG, "interval")["status"] == "published"
    assert public_document_repo.get_document(conn, "game/2") is None                     # この回にない鍵は消える
    assert public_content.get_health(conn)["stale"] is False and public_content.get_health(conn)["latest"] == "2031-05-21"

    assert publishing.publish(conn, conn, CFG, "manual", force=True)["status"] == "published"   # force なら同じ材料でも作り直す


def test_failure_to_build_is_recorded_and_the_table_is_unchanged(conn, monkeypatch):
    version, build = ["a"], [lambda: _docs("2031-05-20")]
    _setup(monkeypatch, version, build)
    publishing.publish(conn, conn, CFG, "daily")
    version[0], build[0] = "b", (lambda: (_ for _ in ()).throw(RuntimeError("データベースの一時的な失敗")))
    assert publishing.publish(conn, conn, CFG, "daily")["status"] == "failed"
    assert public_document_repo.get_document(conn, "game/1") is not None and public_document_repo.get_last_finished_build(conn)["status"] == "failed"


def test_interval_does_not_build_while_the_daily_run_is_running(conn, monkeypatch):
    _setup(monkeypatch, ["a"], [lambda: (_ for _ in ()).throw(AssertionError("作らない"))])
    monkeypatch.setattr(job_repo, "is_daily_run_active", lambda conn, within_hours: True)
    assert publishing.publish(conn, conn, CFG, "interval")["status"] == "daily_running"


def test_audit_rejects_private_fields_and_missing_game_documents():
    """Game 固有の検査: 一覧の作品に作品の文書がない、許していない項目（item_id など）が入っている、記述が長すぎる。"""
    ok = {"overview": {"events": [{"appid": "1"}]},
          "game/1": {"events": [{"side": "fail", "reports": [{"at": "x", "failed": True, "proton": None, "notes": "n"}]}]}}
    assert content.audit(ok) == []
    bad = {"overview": {"events": [{"appid": "1"}, {"appid": "2"}]},
           "game/1": {"events": [{"side": "fail", "item_ids": [], "reports": [{"at": "x", "failed": True, "proton": None, "notes": "n" * 500,
                                                                             "config_hash": "h"}]}]}}
    p = " ".join(content.audit(bad))
    assert "game/2 がない" in p and "item_ids" in p and "config_hash" in p and "長すぎる" in p
