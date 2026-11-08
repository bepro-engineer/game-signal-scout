"""節度のある取得（Anime の sources/http から移植）: ホストごとの最小間隔・429/5xx の backoff・取得の記録。通信は urllib だけ。"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


class Fetcher:
    def __init__(self, user_agent: str, min_interval: float = 1.2, timeout: float = 60.0, opener=None):
        self.ua, self.min_interval, self.timeout = user_agent, min_interval, timeout
        self._last: dict[str, float] = {}
        self._backoff: dict[str, float] = {}
        self._open = opener or urllib.request.urlopen
        self.log: list[dict] = []
        self.should_stop = lambda: False

    def _wait(self, host: str) -> None:
        until = max(self._last.get(host, 0) + self.min_interval, self._backoff.get(host, 0))
        while (left := until - time.monotonic()) > 0 and not self.should_stop():
            time.sleep(min(1.0, left))

    def get_json(self, source: str, url: str):
        """JSON を取る。失敗は例外にせず None（記録は self.log）。"""
        body = self._get(source, url, "application/json", None)
        return json.loads(body) if body is not None else None

    def get_text(self, source: str, url: str) -> str | None:
        """HTML などの文を取る。失敗は例外にせず None（記録は self.log）。"""
        return self._get(source, url, "text/html,application/xhtml+xml", None)

    def download(self, source: str, url: str, dest: Path) -> bool:
        """ファイルに保存する（途中の失敗で壊れたファイルを残さない: .part に書いてから名前を替える）。"""
        return self._get(source, url, "application/octet-stream", Path(dest)) is not None

    def _get(self, source: str, url: str, accept: str, dest: Path | None):
        host = urllib.parse.urlsplit(url).netloc
        self._wait(host)
        req = urllib.request.Request(url, headers={"User-Agent": self.ua, "Accept": accept})
        t0, status, ok, err, out, size = time.monotonic(), None, False, None, None, None
        try:
            with self._open(req, timeout=self.timeout) as r:
                status = getattr(r, "status", 200)
                if dest is None:
                    out = r.read().decode("utf-8", "replace")
                    size = len(out)
                else:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    part = dest.with_name(dest.name + ".part")
                    with open(part, "wb") as f:
                        while chunk := r.read(1 << 20):
                            f.write(chunk)
                    size = part.stat().st_size
                    os.replace(part, dest)
                    out = dest
                ok = True
            self._backoff.pop(host, None)
        except urllib.error.HTTPError as e:
            status, err = e.code, f"http {e.code}"
            if e.code == 429 or e.code >= 500:
                prev = self._backoff.get(host, 0) - time.monotonic()
                self._backoff[host] = time.monotonic() + min(600, max(30, prev * 2 if prev > 0 else 30))
        except Exception as e:  # noqa: BLE001 — 通信の失敗は記録して続ける
            err = f"{type(e).__name__}: {str(e)[:120]}"
        finally:
            self._last[host] = time.monotonic()
        self.log.append({"ts": datetime.now(timezone.utc), "source": source, "host": host, "endpoint": urllib.parse.urlsplit(url).path,
                         "status": status, "ok": ok, "ms": int((time.monotonic() - t0) * 1000), "bytes": size, "error": err})
        return out if ok else None
