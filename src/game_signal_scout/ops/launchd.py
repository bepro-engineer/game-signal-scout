"""起動の定義（launchd の plist）を作る（Anime の ops/launchd の render・write をそのまま移植し、仕事の一覧を Game に替えた）。

- services(): daily-run（時刻で起動。config/daily.toml [launchd] hour・minute）・web（Viewer。常駐）・
  collect-<取得元>（config/sources.toml で resident = true の取得元。どの取得元も同じ形。命令 source-collect。ops/collector。Anime の collect-<source> と同じ）。
- write(): plist を書く（命令 launchd の既定の置き場所は runtime/launchd。見るだけ）。
- apply(): Anime の apply（agent の形）を移植: ~/Library/LaunchAgents に書き、変わった・新しい定義を bootout → bootstrap、
  一覧にないこのアプリの定義を bootout して消す。変わっていない定義には触れない。常駐は 2026-11-08 に本人が承認（Issue #1）。
  Anime の daemon の形（/Library/LaunchDaemons。root が要る）は移植していない。
- 起動は python の 1 プロセス（Anime と同じ _python）。二重起動は launchd（同じ名前は 1 つだけ）と DB の advisory lock が防ぐ。
- 秘密は持たない。ログは runtime/logs。名前の接頭辞は com.bepro.game-signal-scout（Anime の com.bepro.anime-signal-scout と重ならない）。
"""
from __future__ import annotations

import plistlib
import subprocess
from pathlib import Path

PREFIX = "com.bepro.game-signal-scout"


def _python(*args: str) -> list[str]:
    """このアプリの命令を、動いている版のフォルダの python で起動する引数（Anime と同じ）。"""
    return ["/bin/zsh", "-c", 'cd -P . && exec .venv/bin/python -m game_signal_scout "$@"', "game-signal-scout", *args]


def services(root: Path) -> dict[str, dict]:
    from game_signal_scout.config import load_daily_config
    from game_signal_scout.sources.factory import load_sources_config
    lc = load_daily_config()["launchd"]
    logs = root / "runtime" / "logs"
    out = {
        # 日次の 4 段（collect → normalize → analyze → publish）。常駐しない。機械が寝ていた回は、起きたときに 1 回まとめて動く（launchd の仕様）
        "daily-run": {"args": _python("daily-run", "--retry"), "log": logs / "daily-run.launchd.log",
                      "calendar": {"Hour": int(lc["hour"]), "Minute": int(lc["minute"])}, "exit_timeout": 3600},
        # Viewer（自分の機械だけで待ち受ける）
        "web": {"args": _python("web"), "log": logs / "web.launchd.log", "keepalive": True, "throttle": 60, "exit_timeout": 10},
    }
    # 常駐の受信（Anime と同じ: 取得元ごとに 1 つ。どの取得元も同じ形。異常終了のときだけ起動し直す。使えない取得元は 0 で終わり、起動し直さない）
    from game_signal_scout.ops.collector import residents
    for s in residents(load_sources_config()):
        out[f"collect-{s}"] = {"args": _python("source-collect", "--source", s), "log": logs / f"collect-{s}.launchd.log",
                               "keepalive": {"SuccessfulExit": False}, "throttle": 60, "exit_timeout": 60}
    return out


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


def _launchctl(*args: str) -> tuple[int, str]:
    r = subprocess.run(["launchctl", *args], capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr).strip()


def apply(root: Path, agents: Path, uid: int, log=print, launchctl=None) -> dict:
    """書いて反映する（Anime の apply の agent の形と同じ）。変わった・新しい定義は bootout → bootstrap、一覧にない定義は bootout して消す。"""
    lc = launchctl or _launchctl
    r = write(root, agents)
    domain = f"gui/{uid}"
    for name in r["stale"]:
        lc("bootout", f"{domain}/{label(name)}")
        (agents / f"{label(name)}.plist").unlink(missing_ok=True)
        log(f"removed {name}")
    for name in r["changed"]:
        lc("bootout", f"{domain}/{label(name)}")
        rc, msg = lc("bootstrap", domain, str(agents / f"{label(name)}.plist"))
        log(f"{'started' if rc == 0 else 'failed'} {name}{(' ' + msg) if msg else ''}")
    # 定義は同じでも launchd に載っていないもの（前回の bootstrap の失敗・ログインし直し）は載せる（Anime と同じ）
    for name in r["written"]:
        if name in r["changed"] or lc("print", f"{domain}/{label(name)}")[0] == 0:
            continue
        rc, msg = lc("bootstrap", domain, str(agents / f"{label(name)}.plist"))
        log(f"{'loaded' if rc == 0 else 'failed'} {name}{(' ' + msg) if msg else ''}")
    return r
