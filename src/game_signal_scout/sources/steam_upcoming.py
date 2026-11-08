"""これから発売の作品の取得元: Steam のストアの「人気の近日発売」の一覧（store.steampowered.com/search/results?filter=popularcomingsoon&json=1。キー不要）。

Anime の「まもなく放送」（AniList の放送予定）に当たる。1 日 1 回、一覧の上位 max_items 作品の app ID と順位を、その日の 1 件として保存する。
発売日・画像・説明は作品の情報（steam_store）が取る（一覧の作品も作品の情報を揃える対象になる: repositories/catalog.active_apps）。
"""
from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import datetime, timezone

from game_signal_scout.days import default_day
from game_signal_scout.sources.contract import Batch, SourceCorruptError, SourceItem, SourceReader

URL = "https://store.steampowered.com/search/results/?filter=popularcomingsoon&json=1&cc=jp&l=japanese&start={start}&count={count}"
APP = re.compile(r"/apps/(\d+)/")


class SteamUpcoming(SourceReader):
    def read(self, cursor: dict | None) -> Iterator[Batch]:
        n, page = int(self.settings.get("max_items", 100)), 50
        got: list[tuple[str, str]] = []
        for start in range(0, n, page):
            body = self.http.get_json(self.name, URL.format(start=start, count=min(page, n - start)))
            if body is None:
                raise ConnectionError("Steam の近日発売の一覧を取れなかった（記録は source_fetch）")
            if not isinstance((body or {}).get("items"), list):
                raise SourceCorruptError("Steam の近日発売の一覧の形が違う", retryable=True)
            for x in body["items"]:
                m = APP.search(x.get("logo") or "")
                if m and m.group(1) not in {a for a, _ in got}:
                    got.append((m.group(1), x.get("name") or ""))
            if len(body["items"]) < page:
                break
        day = default_day()
        now = datetime.now(timezone.utc)
        items = [SourceItem(self.name, f"{day}:{a}", now, {"appid": a, "day": day.isoformat(), "rank": i, "name": name}, None)
                 for i, (a, name) in enumerate(got, 1)]
        yield Batch(items, {"day": day.isoformat(), "n": len(items)})
