"""起動の定義（ops/launchd。Anime の tests/test_launchd を移植）。書くだけで、launchd には反映しない。"""
import plistlib

from game_signal_scout.ops import launchd


def test_write_renders_plists_and_finds_stale_ones(monkeypatch, tmp_path):
    from game_signal_scout import config
    monkeypatch.setattr(config, "load_daily_config", lambda: {"launchd": {"hour": 6, "minute": 15}})
    out = tmp_path / "launchd"
    out.mkdir()
    (out / f"{launchd.PREFIX}.old-thing.plist").write_bytes(b"x")
    (out / "com.bepro.anime-signal-scout.worker.plist").write_bytes(b"y")       # 他の Scout の定義には触れない
    r = launchd.write(tmp_path, out)
    assert set(r["written"]) == {"daily-run", "web"} and set(r["changed"]) == set(r["written"]) and r["stale"] == ["old-thing"]
    d = plistlib.loads((out / f"{launchd.PREFIX}.daily-run.plist").read_bytes())
    assert d["Label"] == "com.bepro.game-signal-scout.daily-run" and d["StartCalendarInterval"] == {"Hour": 6, "Minute": 15}
    assert d["RunAtLoad"] is False and "KeepAlive" not in d and d["ProgramArguments"][-1] == "daily-run"
    assert "game_signal_scout" in d["ProgramArguments"][2] and "anime" not in d["ProgramArguments"][2]
    w = plistlib.loads((out / f"{launchd.PREFIX}.web.plist").read_bytes())
    assert w["KeepAlive"] is True and w["StandardOutPath"].endswith("runtime/logs/web.launchd.log")
    assert (out / "com.bepro.anime-signal-scout.worker.plist").read_bytes() == b"y"
    assert launchd.write(tmp_path, out)["changed"] == []                       # 同じ内容なら変わらない


def test_no_apply_to_launchd_is_ported_yet():
    """Game の本番の稼働・常駐は本人の承認が要る。launchctl を呼ぶ処理はまだ持たない。"""
    assert "subprocess" not in open(launchd.__file__).read()
