"""遊ばれている規模の取得元: Steam の「最も遊ばれているゲーム」（ISteamChartsService/GetMostPlayedGames。キー不要。Oshi Charts と同じ種類のデータ）。

1 日 1 回の集計（rollup_date）の上位 100 作品の順位・前の週の順位・同時に遊んだ人数の最大を、その日の 1 件として保存する。
規模の補助で、満足度・自分に合うかの根拠にはしない（Issue #2）。
"""
from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone

from game_signal_scout.sources.contract import Batch, SourceCorruptError, SourceItem, SourceReader

URL = "https://api.steampowered.com/ISteamChartsService/GetMostPlayedGames/v1/"


class SteamCharts(SourceReader):
    def read(self, cursor: dict | None) -> Iterator[Batch]:
        body = self.http.get_json(self.name, URL)
        if body is None:
            raise ConnectionError("Steam の順位を取れなかった（記録は source_fetch）")
        r = (body or {}).get("response") or {}
        if not isinstance(r.get("ranks"), list) or not r.get("rollup_date"):
            raise SourceCorruptError("Steam の順位の形が違う", retryable=True)
        day = datetime.fromtimestamp(int(r["rollup_date"]), timezone.utc)
        items = [SourceItem(self.name, f"{day.date()}:{x['appid']}", day,
                            {"appid": str(x["appid"]), "day": day.date().isoformat(), "rank": x.get("rank"), "prev_rank": x.get("last_week_rank"),
                             "peak_players": x.get("peak_in_game")}, None)
                 for x in r["ranks"] if x.get("appid")]
        yield Batch(items, {"rollup_date": int(r["rollup_date"])})
