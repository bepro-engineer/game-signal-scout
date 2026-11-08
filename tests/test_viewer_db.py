"""Viewer の試験（一時の DB）: 収集 → 正規化 → 分析 → 文書の置き換えの結果が画面に出ること、根拠の記述が escape されること、誤った入力と DB の不在。"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from conftest import make_dump, report
from game_signal_scout import config
from game_signal_scout.ops import runner
from game_signal_scout.sources import factory

DAY = 86400
T0 = int(datetime(2026, 6, 1, tzinfo=timezone.utc).timestamp())


@pytest.fixture
def client(conn, tmp_path):
    from fastapi.testclient import TestClient
    from psycopg_pool import ConnectionPool
    from game_signal_scout import db
    from game_signal_scout.web.app import create_app
    reps = [report("100", T0 - 50 * DAY + i * DAY, False, i) for i in range(10)]
    reps += [report("100", T0 + i * DAY, True, 100 + i, note="<script>x</script> crashes after update") for i in range(7)]
    reps += [report("200", T0 + i * 3600, False, i) for i in range(20)]
    path = make_dump(tmp_path / "reports_nov1_2026.tar.gz", reps)
    cfg = {"protondb": {"adapter": "game_signal_scout.sources.protondb:ProtonDBDump", "local_path": str(path)}}
    code, _ = runner.daily_run(date(2026, 10, 31), reader_factory=lambda name: factory.create("protondb", None, cfg))
    assert code == runner.EXIT_OK
    pool = ConnectionPool(config.db_dsn(), min_size=1, max_size=2, kwargs={"autocommit": True}, configure=db.verify_identity, open=True)
    with TestClient(create_app(pool=pool)) as c:
        yield c
    pool.close()


def test_overview_shows_freshness_and_detected_change(client):
    r = client.get("/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    assert "default-src 'none'" in r.headers["content-security-policy"] and r.headers["x-frame-options"] == "DENY"
    body = r.text
    assert 'href="/games/100"' in body and "Game 100" in body       # 最近「遊べなくなった」作品は「買う前に知っておきたいこと」に出る
    assert "遊び方から選ぶ" in body and "買う前に知っておきたいこと" in body and "まだお届けできないこと" in body
    assert "/games/200" not in body                                 # 変化のない作品は一覧に出ない
    assert "内容を作った時刻: 20" in body
    assert "多かった内容: 更新・パッチの後から" in body
    caution = client.get("/cautions").text
    assert "更新・パッチの後から<em>7/7</em>" in caution and "6月1日ごろから" in caution          # 根拠の報告に書かれていた内容と件数
    assert "publish:" not in body                                   # 作っている最中の段は出さない


def test_game_page_shows_weekly_trend_and_escaped_evidence(client):
    body = client.get("/games/100").text
    assert "Game 100" in body and "6月1日ごろから" in body and "買う前の注意" in body
    assert "6月1日ごろから、Linux（Proton）で「遊べない」という報告が増えた" in body          # 何が・いつから（日本語の 1 文）
    assert "0%（10 件）から、続く 14 日で 100%（7 件）" in body and "まだ途中（最新の報告は 6月7日）" in body   # 以前との違い・期間の途中
    assert body.count("crashes after update") == 7                  # 根拠の報告 7 件
    assert "<script>x</script>" not in body and "&lt;script&gt;" in body
    assert "100%" in body                                            # 窓の遊べない割合


def test_about_page_shows_method_sources_and_freshness(client):
    body = client.get("/about").text
    assert "載せていること" in body and "分からないこと" in body and "p-2026-11-07" in body      # 規則の版
    assert "ProtonDB の動作の報告" in body and "2026-06-07" in body                             # 取得元と最新の報告の日（鮮度）
    assert 'aria-current="page"' in body and "publish:" not in body


def test_unknown_or_invalid_game_is_404(client):
    assert client.get("/games/999").status_code == 404
    assert client.get("/games/abc").status_code == 404
    assert client.get("/games/200").status_code == 404              # 変化のない作品の文書は作らない


def test_api_returns_documents_without_private_fields(client):
    o = client.get("/api/overview").json()
    assert o["counts"] == {"fail": 1, "fix": 0} and o["sources"]["protondb"]["items"] == 37
    g = client.get("/api/games/100").json()
    r = g["events"][0]["reports"][0]
    assert set(r) == {"at", "failed", "proton", "notes"}            # item_id・機材構成の hash は出さない
    assert o["events"][0]["themes"] == [{"key": "update", "label": "更新・パッチの後から", "n": 7}] and "item_ids" not in o["events"][0]
    h = client.get("/healthz").json()
    assert h["ok"] is True and h["latest"] == "2026-06-07" and h["stale"] is False


def test_viewer_reads_only_the_document_tables(client, conn):
    """Viewer は public_document と public_build だけを読む（分析の表を消しても画面は前の内容のまま出る）。"""
    conn.execute("TRUNCATE shift_event, player_report, job_run, source_state")
    conn.commit()
    assert "Game 100" in client.get("/").text and client.get("/games/100").status_code == 200


def test_database_unavailable_is_503(conn):
    import psycopg
    from fastapi.testclient import TestClient
    from game_signal_scout.web.app import create_app

    class DownPool:
        def connection(self):
            raise psycopg.OperationalError("接続できない（試験）")
    with TestClient(create_app(pool=DownPool())) as c:
        assert c.get("/").status_code == 503
