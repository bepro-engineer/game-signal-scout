"""Steam のユーザーレビュー（公式 API IUserReviewsService/GetAppReviews）の取得元。

**実際の取得は本人の承認まで無効**（config/sources.toml の enabled = false。Issue #1 の指示 6705736617 の B）。
今は固定の偽の応答による試験だけで動作を確かめる。応答の形は実取得の前に公式文書で確かめる（ここでは response の中に
reviews と cursor がある形と、旧来の直下にある形の両方を読む）。

- 投稿者の Steam ID は保存しない（人数の数え方が必要になったら、Scout の鍵で HMAC にする）。
- 版は timestamp_updated。編集されたレビューは保存を置き換え、正規化をやり直す。
- 作品ごとに cursor で続きを読み、cursor が変わらない・レビューが空になったら、その作品を終える。
"""
from __future__ import annotations

import json
import urllib.parse
from collections.abc import Iterator
from datetime import datetime, timezone

from game_signal_scout.errors import RetryableError
from game_signal_scout.sources.contract import Batch, SourceCorruptError, SourceItem, SourceNotConfiguredError, SourceReader

KEEP = ("recommendationid", "language", "review", "timestamp_created", "timestamp_updated", "voted_up", "votes_up", "steam_purchase",
        "received_for_free", "written_during_early_access", "primarily_steam_deck", "refunded")


class SteamReviews(SourceReader):
    def _url(self, appid: str, cursor: str) -> str:
        q = {"appid": int(appid), "filter": int(self.settings.get("filter", 1)), "languages": list(self.settings.get("languages", ["all"])),
             "num_per_page": int(self.settings.get("num_per_page", 100)), "cursor": cursor}
        for k in ("date_range_start", "date_range_end"):
            if self.settings.get(k):
                q[k] = int(self.settings[k])
        return self.settings["endpoint"] + "?" + urllib.parse.urlencode({"input_json": json.dumps(q, separators=(",", ":"))})

    def read(self, cursor: dict | None) -> Iterator[Batch]:
        appids = [str(a) for a in self.settings.get("appids") or []]
        if not appids or not self.settings.get("endpoint"):
            raise SourceNotConfiguredError("steam_reviews: appids と endpoint がない")
        # 前回、全作品を読み終えていれば、今回は最初から（新しい・編集されたレビューを拾う）。途中なら続きから
        state = {} if not cursor or cursor.get("complete") else dict(cursor)
        pages = int(self.settings.get("max_pages_per_app", 3))
        for appid in appids:
            if state.get(appid, {}).get("done"):
                continue
            pos = state.get(appid, {}).get("cursor", "*")
            for _ in range(pages):
                data = self.http.get_json(self.name, self._url(appid, pos))
                if data is None:
                    raise RetryableError(f"steam_reviews: {appid} の応答を取れない", "network")
                body = data.get("response", data) if isinstance(data, dict) else None
                if not isinstance(body, dict) or not isinstance(body.get("reviews", []), list):
                    raise SourceCorruptError(f"steam_reviews: {appid} の応答の形が違う")
                reviews, nxt = body.get("reviews") or [], body.get("cursor")
                items = [self._item(appid, r) for r in reviews if r.get("recommendationid")]
                done = not reviews or not nxt or nxt == pos
                state[appid] = {"cursor": nxt or pos, "done": done}
                yield Batch(items, dict(state))
                if done:
                    break
                pos = nxt
        yield Batch([], {**state, "complete": all(state.get(a, {}).get("done") for a in appids)})

    def _item(self, appid: str, r: dict) -> SourceItem:
        payload = {"appid": appid, **{k: r.get(k) for k in KEEP if k in r},
                   "playtime_at_review": (r.get("author") or {}).get("playtime_at_review")}
        ts = int(r.get("timestamp_created") or 0)
        return SourceItem(self.name, str(r["recommendationid"]), datetime.fromtimestamp(ts, timezone.utc), payload,
                          version=str(r.get("timestamp_updated") or ts))
