"""起動の定義（ops/launchd。Anime の tests/test_launchd を移植）。書くだけで、launchd には反映しない。"""
import plistlib
from pathlib import Path

from game_signal_scout.ops import launchd


RES = {"src_a": {"adapter": "x:Y", "resident": True}, "src_b": {"adapter": "x:Y", "resident": True}, "cat": {"adapter": "x:Y"}}


def test_write_renders_plists_and_finds_stale_ones(monkeypatch, tmp_path):
    from game_signal_scout import config
    from game_signal_scout.sources import factory
    monkeypatch.setattr(config, "load_daily_config", lambda: {"launchd": {"hour": 6, "minute": 15}})
    monkeypatch.setattr(factory, "load_sources_config", lambda: RES)
    out = tmp_path / "launchd"
    out.mkdir()
    (out / f"{launchd.PREFIX}.old-thing.plist").write_bytes(b"x")
    (out / "com.bepro.anime-signal-scout.worker.plist").write_bytes(b"y")       # 他の Scout の定義には触れない
    r = launchd.write(tmp_path, out)
    assert set(r["written"]) == {"daily-run", "web", "collect-src_a", "collect-src_b"} and set(r["changed"]) == set(r["written"]) and r["stale"] == ["old-thing"]
    d = plistlib.loads((out / f"{launchd.PREFIX}.daily-run.plist").read_bytes())
    assert d["Label"] == "com.bepro.game-signal-scout.daily-run" and d["StartCalendarInterval"] == {"Hour": 6, "Minute": 15}
    assert d["RunAtLoad"] is False and "KeepAlive" not in d and d["ProgramArguments"][-2:] == ["daily-run", "--retry"]
    assert "game_signal_scout" in d["ProgramArguments"][2] and "anime" not in d["ProgramArguments"][2]
    w = plistlib.loads((out / f"{launchd.PREFIX}.web.plist").read_bytes())
    assert w["KeepAlive"] is True and w["StandardOutPath"].endswith("runtime/logs/web.launchd.log")
    for name in ("src_a", "src_b"):                                            # 常駐の取得元はどれも同じ形（Anime の collect-<source>）
        c = plistlib.loads((out / f"{launchd.PREFIX}.collect-{name}.plist").read_bytes())
        assert c["KeepAlive"] == {"SuccessfulExit": False} and c["ProgramArguments"][-3:] == ["source-collect", "--source", name]
    assert (out / "com.bepro.anime-signal-scout.worker.plist").read_bytes() == b"y"
    assert launchd.write(tmp_path, out)["changed"] == []                       # 同じ内容なら変わらない


def test_apply_bootstraps_changed_removes_stale_and_loads_missing(monkeypatch, tmp_path):
    """Anime の apply（agent の形）と同じ手順。launchctl は偽物で、本物の launchd には触れない。"""
    from game_signal_scout import config
    from game_signal_scout.sources import factory
    monkeypatch.setattr(factory, "load_sources_config", lambda: {})
    monkeypatch.setattr(config, "load_daily_config", lambda: {"launchd": {"hour": 6, "minute": 15}})
    agents = tmp_path / "LaunchAgents"
    agents.mkdir()
    (agents / f"{launchd.PREFIX}.old-thing.plist").write_bytes(b"x")
    calls, loaded = [], set()

    def lc(*args):
        calls.append(args)
        if args[0] == "bootstrap":
            loaded.add(args[2].rsplit("/", 1)[1][:-6])
        return (0 if args[0] != "print" or args[1].split("/")[-1] in loaded else 113), ""
    r = launchd.apply(tmp_path, agents, 501, log=lambda m: None, launchctl=lc)
    assert r["stale"] == ["old-thing"] and not (agents / f"{launchd.PREFIX}.old-thing.plist").exists()
    assert ("bootout", f"gui/501/{launchd.PREFIX}.old-thing") in calls
    assert sorted(a[2].rsplit(".", 2)[-2] for a in calls if a[0] == "bootstrap") == ["daily-run", "web"]
    calls.clear()
    launchd.apply(tmp_path, agents, 501, log=lambda m: None, launchctl=lc)     # 変わっていない・載っている定義には触れない
    assert [a[0] for a in calls] == ["print"] * 2
    loaded.discard(f"{launchd.PREFIX}.web")
    calls.clear()
    launchd.apply(tmp_path, agents, 501, log=lambda m: None, launchctl=lc)     # 載っていない定義（ログインし直しなど）は載せる
    assert [a for a in calls if a[0] == "bootstrap"] == [("bootstrap", "gui/501", str(agents / f"{launchd.PREFIX}.web.plist"))]



def test_daily_run_retries_retryable_failures(monkeypatch, capsys):
    """日次は再試行できる失敗（75）を max_attempts まで繰り返す（Anime の §22。待ちは retry_after_minutes）。"""
    import time
    from game_signal_scout import cli
    from game_signal_scout.ops import runner
    calls = []
    def fake(day, only, attempt):
        calls.append(attempt)
        return (runner.EXIT_RETRY if attempt < 3 else runner.EXIT_OK), {"max_attempts": 3, "retry_after_minutes": 0}
    monkeypatch.setattr(runner, "daily_run", fake)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    assert cli.main(["daily-run", "--retry"]) == runner.EXIT_OK and calls == [1, 2, 3]
    calls.clear()
    monkeypatch.setattr(runner, "daily_run", lambda d, o, a: (calls.append(a) or runner.EXIT_RETRY, {"max_attempts": 3, "retry_after_minutes": 0}))
    assert cli.main(["daily-run"]) == runner.EXIT_RETRY and calls == [1]          # --retry なしは 1 回だけ
