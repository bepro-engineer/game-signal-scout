"""コマンドの入口（Controller）。業務の処理は services、実行の管理は ops/runner。出力は 1 行の JSON。"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="game_signal_scout")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("daily-run", help="段（collect → normalize → analyze）を順に実行する")
    d.add_argument("--day", type=date.fromisoformat)
    d.add_argument("--only", nargs="*")
    d.add_argument("--attempt", type=int, default=1)
    d.add_argument("--retry", action="store_true", help="再試行できる失敗（終了コード 75）なら retry_after_minutes の後に max_attempts まで繰り返す（launchd の日次はこれを使う）")
    e = sub.add_parser("events", help="検出した変化を表示する")
    e.add_argument("--side", default="fail", choices=["fail", "fix"])
    e.add_argument("--limit", type=int, default=10)
    sub.add_parser("status", help="監視が読む状態（段・取得元・分析・公開を分けて返す）")
    w = sub.add_parser("web", help="Viewer（読むだけの画面）を動かす。待ち受けの既定は config/daily.toml [web]（自分の機械だけ）")
    w.add_argument("--host")
    w.add_argument("--port", type=int)
    ld = sub.add_parser("launchd", help="起動の定義（launchd の plist）を書く（既定 runtime/launchd）。--apply で ~/Library/LaunchAgents に書いて反映")
    ld.add_argument("--dir")
    ld.add_argument("--apply", action="store_true", help="変わった・新しい定義を bootout → bootstrap し、一覧にない定義を消す（Anime の apply と同じ）")
    sub.add_parser("poll", help="短い間隔の収集（config/sources.toml の poll = true の取得元を collect → 正規化。launchd の poll が動かす）")
    sub.add_parser("init-author-key", help="投稿者の HMAC の鍵（runtime/author_hmac.key）を初回だけ作る（あれば作らない）")
    a = ap.parse_args(argv)
    if a.cmd == "launchd":
        from pathlib import Path
        from game_signal_scout import config
        from game_signal_scout.ops import launchd
        if a.apply:
            import os
            agents = Path(a.dir) if a.dir else Path.home() / "Library" / "LaunchAgents"
            print(json.dumps(launchd.apply(config.REPO, agents, os.getuid(), log=lambda m: print(m, file=sys.stderr))))
            return 0
        print(json.dumps(launchd.write(config.REPO, Path(a.dir) if a.dir else config.RUNTIME / "launchd")))
        return 0
    if a.cmd == "poll":
        from game_signal_scout.ops import poll
        return poll.main()
    if a.cmd == "init-author-key":
        from game_signal_scout import actor_key
        print(json.dumps({"created": actor_key.create_key()}))
        return 0
    if a.cmd == "web":
        import uvicorn
        from game_signal_scout import config
        wc = config.load_daily_config()["web"]
        uvicorn.run("game_signal_scout.web.app:create_app", factory=True, host=a.host or wc["host"], port=a.port or int(wc["port"]),
                    server_header=False)
        return 0
    if a.cmd == "daily-run":
        from game_signal_scout.ops.runner import EXIT_RETRY, daily_run
        attempt = a.attempt
        while True:
            code, out = daily_run(a.day, a.only, attempt)
            print(json.dumps(out, ensure_ascii=False, default=str), flush=True)
            # 再試行は呼ぶ側の 1 層だけ（Anime の §22）: 上限と待ちは config/daily.toml の [daily_run]
            if not a.retry or code != EXIT_RETRY or attempt >= int(out.get("max_attempts") or 1):
                return code
            import time
            time.sleep(int(out.get("retry_after_minutes") or 30) * 60)
            attempt += 1
    from game_signal_scout import config, db
    from game_signal_scout.repositories import report
    with db.connect() as conn:
        if a.cmd == "status":
            from game_signal_scout.ops.status import status
            print(json.dumps(status(conn), ensure_ascii=False, default=str))
            return 0
        version = config.load_daily_config()["analysis"]["version"]
        for row in report.events(conn, version, a.side)[: a.limit]:
            print(json.dumps(dict(zip(("appid", "window_start", "n_key", "n_window", "share_prev", "share_window"), row)), default=str))
    return 0
