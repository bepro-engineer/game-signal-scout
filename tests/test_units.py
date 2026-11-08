"""DB を使わない試験: 配布ファイルの読み方・取得元の Factory・接続先の名前の規則・変化の検出・失敗の分類・取得の backoff。"""
from __future__ import annotations

import io
import json
from datetime import datetime, timezone

import pytest

from conftest import make_dump, report
from game_signal_scout import config
from game_signal_scout.errors import LockedError, classify
from game_signal_scout.services import normalize, shift
from game_signal_scout.sources import factory, protondb
from game_signal_scout.sources.contract import SourceCorruptError
from game_signal_scout.sources.http import Fetcher

DAY = 86400
T0 = int(datetime(2026, 6, 1, tzinfo=timezone.utc).timestamp())
P = {"window_days": 14, "prev_days": 60, "min_key_reports": 5, "min_distinct_configs": 5, "min_prev_reports": 5, "min_jump": 0.30}


def test_json_array_is_streamed_across_chunk_boundaries():
    records = [{"i": i, "s": "x" * (i % 7), "nested": {"a": [1, {"b": "]"}]}} for i in range(500)]
    got = list(protondb.iter_json_array(io.BytesIO(json.dumps(records, indent=1).encode()), chunk_size=17))
    assert got == records
    assert list(protondb.iter_json_array(io.BytesIO(b"[]"))) == []


def test_item_id_is_stable_and_content_based():
    a = report("1", T0, True, 1)
    assert protondb.item_id(a) == protondb.item_id(json.loads(json.dumps(a)))
    assert protondb.item_id(a) != protondb.item_id(report("1", T0 + 1, True, 1))


def test_latest_dump_is_chosen_by_date_not_by_name():
    names = ["reports_dec1_2025.tar.gz", "reports_nov1_2026.tar.gz", "reports_feb1_2026.tar.gz", "README.md"]
    assert max((n for n in names if protondb.dump_date(n)), key=protondb.dump_date) == "reports_nov1_2026.tar.gz"


def test_reader_resumes_from_offset(tmp_path):
    path = make_dump(tmp_path / "reports_nov1_2026.tar.gz", [report("1", T0 + i, False, i) for i in range(5)])
    r = factory.create("protondb", None, {"protondb": {"adapter": "game_signal_scout.sources.protondb:ProtonDBDump",
                                                      "local_path": str(path), "batch_size": 2}})
    batches = list(r.read(None))
    assert [len(b.items) for b in batches] == [2, 2, 1]
    assert batches[-1].cursor == {"dump": path.name, "snapshot": path.name, "offset": 5, "complete": True}
    assert [len(b.items) for b in r.read(batches[-1].cursor)] == [0]          # 読み終えた配布物は読み直さない
    rest = list(r.read({"dump": path.name, "offset": 2}))
    assert [i.item_id for b in rest for i in b.items] == [i.item_id for b in batches[1:] for i in b.items]
    assert sum(len(b.items) for b in r.read({"dump": "reports_oct1_2026.tar.gz", "offset": 4})) == 5   # 別の月のファイルは最初から


def test_corrupt_local_dump_is_not_retryable(tmp_path):
    good = make_dump(tmp_path / "g.tar.gz", [report("1", T0 + i, False, i) for i in range(50)]).read_bytes()
    bad = tmp_path / "reports_nov1_2026.tar.gz"
    bad.write_bytes(good[: len(good) // 2])                                    # 途中で切れた配布物
    r = factory.create("protondb", None, {"protondb": {"adapter": "game_signal_scout.sources.protondb:ProtonDBDump", "local_path": str(bad)}})
    with pytest.raises(SourceCorruptError) as e:
        list(r.read(None))
    assert classify(e.value) == (False, "source_corrupt")
    assert bad.exists()                                                        # 手元のファイルは消さない


def test_factory_reads_adapter_from_config():
    assert factory.sources() == ["protondb", "steam_reviews", "steam_charts", "steam_upcoming", "steam_store"]   # bluesky は常駐（resident）なので日次では読まない
    assert factory.reader_class("protondb") is protondb.ProtonDBDump
    with pytest.raises(ValueError):
        factory.reader_class("nope", {})


@pytest.mark.parametrize("name", ["anime_signal_scout", "anime_signal_scout_test", "postgres", "", None])
def test_only_game_databases_are_accepted(name):
    with pytest.raises(config.WrongDatabaseError):
        config.check_dbname(name)


def test_anime_dsn_variable_is_never_used(monkeypatch, tmp_path):
    monkeypatch.delenv("GSS_DB_DSN", raising=False)
    monkeypatch.delenv("GSS_TEST_DATABASE", raising=False)
    monkeypatch.setenv("ASS_DB_DSN", "postgresql://x@127.0.0.1/anime_signal_scout")
    monkeypatch.setattr(config, "DB_ENV", tmp_path / "missing.env")
    with pytest.raises(RuntimeError, match="GSS_DB_DSN"):
        config.db_dsn()
    monkeypatch.setenv("GSS_DB_DSN", "postgresql://x@127.0.0.1/anime_signal_scout")
    with pytest.raises(config.WrongDatabaseError):
        config.db_dsn()


def test_normalize_definition_of_failure():
    assert normalize.failed(report("1", T0, True, 1))
    r = report("1", T0, False, 1)
    r["responses"]["startsPlay"] = "no"
    assert normalize.failed(r)
    assert not normalize.failed(report("1", T0, False, 1))
    assert normalize.config_hash(report("1", T0, False, 1)) != normalize.config_hash(report("1", T0, False, 2))


def _rows(reps):
    return [(r["app"]["steam"]["appId"], r["timestamp"], normalize.failed(r), normalize.config_hash(r), str(i)) for i, r in enumerate(reps)]


def test_shift_detects_breakage_and_merges_overlapping_windows():
    reps = [report("A", T0 - 50 * DAY + i * DAY, False, i) for i in range(10)]           # 前の 60 日: 全部遊べた
    reps += [report("A", T0 + i * DAY, True, 100 + i) for i in range(7)]                  # 7 日で 7 件の失敗（機材は全部別）
    reps += [report("B", T0 - 50 * DAY + i * DAY, False, i) for i in range(10)]
    reps += [report("B", T0 + i * DAY, True, 1) for i in range(7)]                        # 失敗は多いが機材が 1 種類 → 事象にしない
    ev = shift.detect(_rows(reps), datetime(2026, 5, 1, tzinfo=timezone.utc), datetime(2026, 11, 1, tzinfo=timezone.utc), P)
    assert [(e["side"], e["appid"], e["n_key"]) for e in ev] == [("fail", "A", 7)]
    assert ev[0]["share_prev"] == 0 and ev[0]["share_window"] == 1


def test_shift_requires_enough_history():
    # 前の報告が 4 件しかない最初の窓は対象外。2 件目からの窓は前の報告が 5 件になるが、失敗が 4 件しか残らない
    reps = [report("A", T0 - 50 * DAY + i * DAY, False, i) for i in range(4)] + [report("A", T0 + i * DAY, True, 100 + i) for i in range(5)]
    assert shift.detect(_rows(reps), datetime(2026, 5, 1, tzinfo=timezone.utc), datetime(2026, 11, 1, tzinfo=timezone.utc), P) == []


def test_classify():
    assert classify(LockedError("x")) == (True, "locked")
    assert classify(ConnectionError()) == (True, "network")
    assert classify(config.WrongDatabaseError("x")) == (False, "wrong_database")
    assert classify(KeyError("x")) == (False, "unexpected")


def test_fetcher_backs_off_on_429_and_records(tmp_path):
    import urllib.error
    calls = []

    def opener(req, timeout):
        calls.append(req.full_url)
        raise urllib.error.HTTPError(req.full_url, 429, "too many", {}, None)
    f = Fetcher("t", min_interval=0, opener=opener)
    assert f.get_json("protondb", "https://example.invalid/x") is None
    assert f.log[-1]["status"] == 429 and not f.log[-1]["ok"]
    assert f._backoff["example.invalid"] > 0
    assert not (tmp_path / "f").exists()
