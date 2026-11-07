"""コマンドの入口（Controller）。業務の処理は services、実行の管理は ops/runner。出力は 1 行の JSON。"""
from __future__ import annotations

import argparse
import json
from datetime import date


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="game_signal_scout")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("daily-run", help="段（collect → normalize → analyze）を順に実行する")
    d.add_argument("--day", type=date.fromisoformat)
    d.add_argument("--only", nargs="*")
    d.add_argument("--attempt", type=int, default=1)
    e = sub.add_parser("events", help="検出した変化を表示する")
    e.add_argument("--side", default="fail", choices=["fail", "fix"])
    e.add_argument("--limit", type=int, default=10)
    sub.add_parser("status", help="監視が読む状態（段・取得元・分析・公開を分けて返す）")
    w = sub.add_parser("web", help="Viewer（読むだけの画面）を動かす。待ち受けの既定は config/daily.toml [web]（自分の機械だけ）")
    w.add_argument("--host")
    w.add_argument("--port", type=int)
    sub.add_parser("init-author-key", help="投稿者の HMAC の鍵（runtime/author_hmac.key）を初回だけ作る（あれば作らない）")
    a = ap.parse_args(argv)
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
        from game_signal_scout.ops.runner import daily_run
        code, out = daily_run(a.day, a.only, a.attempt)
        print(json.dumps(out, ensure_ascii=False, default=str))
        return code
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
