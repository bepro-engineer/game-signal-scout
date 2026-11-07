"""起動の定義（launchd の plist）を作る（Anime の ops/launchd の render・write をそのまま移植し、仕事の一覧を Game に替えた）。

- services(): daily-run（時刻で起動。config/daily.toml [launchd] hour・minute）と web（Viewer。常駐）。
  Bluesky の常駐の受信は、Game に常駐の受信の命令がまだないので入れていない（入れるときはここに足す）。
- write(): plist を書くだけ（既定の置き場所は runtime/launchd。~/Library/LaunchAgents には書かない）。
  launchd への反映（Anime の apply・apply_daemons）は移植していない: Game の本番の稼働・常駐は本人の承認が要るため。承認の後に Anime から移す。
- 起動は python の 1 プロセス（Anime と同じ _python）。二重起動は launchd（同じ名前は 1 つだけ）と DB の advisory lock が防ぐ。
- 秘密は持たない。ログは runtime/logs。名前の接頭辞は com.bepro.game-signal-scout（Anime の com.bepro.anime-signal-scout と重ならない）。
"""
from __future__ import annotations

import plistlib
from pathlib import Path

PREFIX = "com.bepro.game-signal-scout"


def _python(*args: str) -> list[str]:
    """このアプリの命令を、動いている版のフォルダの python で起動する引数（Anime と同じ）。"""
    return ["/bin/zsh", "-c", 'cd -P . && exec .venv/bin/python -m game_signal_scout "$@"', "game-signal-scout", *args]


def services(root: Path) -> dict[str, dict]:
    from game_signal_scout.config import load_daily_config
    lc = load_daily_config()["launchd"]
    logs = root / "runtime" / "logs"
    return {
        # 日次の 4 段（collect → normalize → analyze → publish）。常駐しない。機械が寝ていた回は、起きたときに 1 回まとめて動く（launchd の仕様）
        "daily-run": {"args": _python("daily-run"), "log": logs / "daily-run.launchd.log",
                      "calendar": {"Hour": int(lc["hour"]), "Minute": int(lc["minute"])}, "exit_timeout": 3600},
        # Viewer（自分の機械だけで待ち受ける）
        "web": {"args": _python("web"), "log": logs / "web.launchd.log", "keepalive": True, "throttle": 60, "exit_timeout": 10},
    }


def label(name: str) -> str:
    return f"{PREFIX}.{name}"


def render(name: str, spec: dict, root: Path, user: str | None = None) -> bytes:
    """Anime の render と同じ。user を渡すと daemon の定義（その利用者で動かす）。"""
    d = {"Label": label(name), "ProgramArguments": spec["args"], "WorkingDirectory": str(root),
         "ExitTimeOut": spec["exit_timeout"], "StandardOutPath": str(spec["log"]), "StandardErrorPath": str(spec["log"])}
    if user:
        d |= {"UserName": user, "EnvironmentVariables": {"HOME": str(Path("~" + user).expanduser())}}
    if "calendar" in spec:
        d |= {"StartCalendarInterval": spec["calendar"], "RunAtLoad": False}
    elif "interval" in spec:
        d |= {"StartInterval": spec["interval"], "RunAtLoad": True}
    else:
        d |= {"RunAtLoad": True, "KeepAlive": spec["keepalive"], "ThrottleInterval": spec["throttle"]}
    return plistlib.dumps(d, sort_keys=False)


def write(root: Path, out: Path, user: str | None = None) -> dict:
    """plist を書く（Anime の write と同じ）。返り値: 書いた名前・内容の変わった名前・一覧にないこのアプリの plist（stale）。"""
    out.mkdir(parents=True, exist_ok=True)
    svc = services(root)
    written, changed = [], []
    for name, spec in svc.items():
        p = out / f"{label(name)}.plist"
        spec["log"].parent.mkdir(parents=True, exist_ok=True)   # launchd はログのフォルダを作らない
        body = render(name, spec, root, user)
        if not p.exists() or p.read_bytes() != body:
            changed.append(name)
        p.write_bytes(body)
        written.append(name)
    stale = sorted(p.name[len(PREFIX) + 1:-6] for p in out.glob(f"{PREFIX}.*.plist") if p.name[len(PREFIX) + 1:-6] not in svc)
    return {"written": written, "changed": changed, "stale": stale}
