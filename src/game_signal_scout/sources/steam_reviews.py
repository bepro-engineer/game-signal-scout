"""Steam のユーザーレビュー（公式 API IUserReviewsService/GetAppReviews）の取得元。

2026-11-08 から使う（Issue #2 の本人の指示「権利に振り回されすぎ、一切気にするな」を受けた判断。非公開・非商用の試作、対象と件数を絞る）。
止めるときは config/sources.toml の enabled = false にし、保存した項目を消す。
対象の作品は、設定の appids があればそれ、なければ「プレイヤーの報告・発言・遊ばれている規模の多い作品」（repositories/catalog.active_apps）。
応答は response の中に reviews と cursor がある形と、旧来の直下にある形の両方を読む。

- 投稿者の Steam ID は保存しない（人数の数え方が必要になったら、Scout の鍵で HMAC にする）。
- 版は timestamp_updated。編集されたレビューは保存を置き換え、正規化をやり直す。
- 作品ごとに cursor で続きを読み、cursor が変わらない・レビューが空になったら、その作品を終える。
- 量の多い作品で途中を取りこぼさない（2026-11-08: 1 作品 1,000 件の上限で 42 作品の過去が欠け、「初めて話題に」と誤って出た）:
  max_age_days の日数分のレビューがそろっている作品は、保存済みのレビューだけのページに届いたら終える（毎日の差分）。
  そろっていない作品は、max_age_days より古いレビューに届くまで遡る（max_pages_per_app が上限）。
"""
from __future__ import annotations

import json
import time
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

    conn = None     # 収集の Service が渡す（対象の作品を引く）

    def read(self, cursor: dict | None) -> Iterator[Batch]:
        appids = [str(a) for a in self.settings.get("appids") or []]
        if not appids and self.conn is not None:
            from game_signal_scout.repositories import catalog
            appids = [a for a, _ in catalog.active_apps(self.conn, int(self.settings.get("active_days", 90)), int(self.settings.get("max_games", 60)))]
        if not appids or not self.settings.get("endpoint"):
            raise SourceNotConfiguredError("steam_reviews: appids と endpoint がない")
        # 前回、全作品を読み終えていれば、今回は最初から（新しい・編集されたレビューを拾う）。途中なら続きから
        state = {} if not cursor or cursor.get("complete") else dict(cursor)
        pages = int(self.settings.get("max_pages_per_app", 3))
        age = int(self.settings.get("max_age_days") or 0)
        covered = self._covered(appids, age)
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
                # 新しい順に読み、この日数より古いレビューに届いたらその作品を終える
                if age and reviews and min(int(r.get("timestamp_created") or 0) for r in reviews) < time.time() - age * 86400:
                    done = True
                if appid in covered and items and self._all_known([i.item_id for i in items]):
                    done = True                                          # 過去はそろっている: 保存済みに届いた
                state[appid] = {"cursor": nxt or pos, "done": done}
                yield Batch(items, dict(state))
                if done:
                    break
                pos = nxt
        yield Batch([], {**state, "complete": all(state.get(a, {}).get("done") for a in appids)})

    def _covered(self, appids: list[str], age: int) -> set[str]:
        """max_age_days の日数分のレビューがそろっている作品（保存したいちばん古いレビューが、その日数より前）。"""
        if self.conn is None or not age:
            return set()
        rows = self.conn.execute("SELECT payload->>'appid' FROM source_item WHERE source = %s AND payload->>'appid' = ANY(%s) GROUP BY 1 "
                                 "HAVING min(occurred_at) < now() - make_interval(days => %s)", (self.name, appids, age)).fetchall()
        return {r[0] for r in rows}

    def _all_known(self, ids: list[str]) -> bool:
        if self.conn is None:
            return False
        n = self.conn.execute("SELECT count(*) FROM source_item WHERE source = %s AND item_id = ANY(%s)", (self.name, ids)).fetchone()[0]
        return n == len(ids)

    def _item(self, appid: str, r: dict) -> SourceItem:
        payload = {"appid": appid, **{k: r.get(k) for k in KEEP if k in r},
                   "playtime_at_review": (r.get("author") or {}).get("playtime_at_review")}
        ts = int(r.get("timestamp_created") or 0)
        return SourceItem(self.name, str(r["recommendationid"]), datetime.fromtimestamp(ts, timezone.utc), payload,
                          version=str(r.get("timestamp_updated") or ts))
