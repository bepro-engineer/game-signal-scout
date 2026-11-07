"""ProtonDB の公開配布データ（GitHub bdefore/protondb-data。ODbL 1.0 / DbCL 1.0）の取得元。

- 本体のサイトは取得しない（robots.txt が AI のクローラーを拒否している）。読むのは月ごとの配布ファイルだけ。
- 配布ファイルは累積（毎月、過去の報告も全部入る）。項目の ID は報告の内容から作るので、別の月のファイルを読んでも同じ報告は 1 件になる。
- 続きの位置は (配布ファイルの名前, 何件目まで保存したか)。途中で止まっても、次は続きから読む。
"""
from __future__ import annotations

import hashlib
import json
import re
import tarfile
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

from game_signal_scout import config
from game_signal_scout.errors import RetryableError
from game_signal_scout.sources.contract import Batch, SourceItem, SourceNotConfiguredError, SourceReader

MEMBER = "reports_piiremoved.json"
_MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
_NAME = re.compile(r"reports_([a-z]{3})(\d{1,2})_(\d{4})\.tar\.gz$")


def dump_date(name: str) -> tuple[int, int, int] | None:
    m = _NAME.search(name)
    if not m or m.group(1) not in _MONTHS:
        return None
    return int(m.group(3)), _MONTHS[m.group(1)], int(m.group(2))


def item_id(record: dict) -> str:
    """報告の ID（配布データに ID がないので、内容の正規化した JSON の hash）。"""
    return hashlib.sha256(json.dumps(record, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:32]


def iter_json_array(f, chunk_size: int = 1 << 20) -> Iterator[dict]:
    """大きな JSON の配列を、全体を読み込まずに 1 要素ずつ返す（配布ファイルは展開すると 500MB を超える）。"""
    dec = json.JSONDecoder()
    buf, pos, started, eof = "", 0, False, False
    reader = _text(f)
    while True:
        if not eof and len(buf) - pos < chunk_size:
            chunk = reader.read(chunk_size)
            buf, pos = buf[pos:] + chunk, 0
            eof = not chunk
        while pos < len(buf) and buf[pos] in " \t\r\n,":
            pos += 1
        if not started:
            if pos >= len(buf):
                if eof:
                    return
                continue
            if buf[pos] != "[":
                raise ValueError("配布ファイルが JSON の配列でない")
            started, pos = True, pos + 1
            continue
        if pos < len(buf) and buf[pos] == "]":
            return
        try:
            obj, end = dec.raw_decode(buf, pos)
        except json.JSONDecodeError:
            if eof:
                raise
            buf, pos = buf[pos:] + reader.read(chunk_size), 0
            continue
        pos = end
        yield obj


def _text(f):
    import io
    return io.TextIOWrapper(f, encoding="utf-8")


class ProtonDBDump(SourceReader):
    def _dump_path(self) -> Path:
        local = self.settings.get("local_path")
        if local:
            p = Path(local)
            if not p.exists():
                raise SourceNotConfiguredError(f"配布ファイルがない: {p}")
            return p
        name = self.settings.get("dump") or "latest"
        if name == "latest":
            listing = self.http.get_json(self.name, self.settings["listing_url"])
            if not listing:
                raise RetryableError("配布ファイルの一覧を取れない", "network")
            names = [x["name"] for x in listing if dump_date(x.get("name", ""))]
            if not names:
                raise RetryableError("配布ファイルの一覧に月のファイルがない", "network")
            name = max(names, key=dump_date)
        dest = config.RUNTIME / "protondb" / name
        if not dest.exists() and not self.http.download(self.name, self.settings["file_url"].format(name=name), dest):
            raise RetryableError(f"配布ファイルを取れない: {name}", "network")
        return dest

    def read(self, cursor: dict | None) -> Iterator[Batch]:
        path = self._dump_path()
        dump = path.name
        skip = int(cursor.get("offset", 0)) if cursor and cursor.get("dump") == dump else 0
        size = int(self.settings.get("batch_size") or 2000)
        items: list[SourceItem] = []
        n = 0
        with tarfile.open(path, "r:gz") as tar:
            f = tar.extractfile(MEMBER)
            if f is None:
                raise ValueError(f"配布ファイルに {MEMBER} がない")
            for record in iter_json_array(f):
                n += 1
                if n <= skip:
                    continue
                ts = record.get("timestamp")
                if not isinstance(ts, int):
                    continue
                items.append(SourceItem(self.name, item_id(record), datetime.fromtimestamp(ts, timezone.utc), record))
                if len(items) >= size:
                    yield Batch(items, {"dump": dump, "offset": n})
                    items = []
        yield Batch(items, {"dump": dump, "offset": n, "complete": True})
