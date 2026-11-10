"""作品の価格の取得元: Steam のストアの日本向けの販売価格（store.steampowered.com/api/appdetails。cc=jp。キー不要）。#2 2026-11-10。

- 価格（filters=price_overview）は複数の作品を 1 回で問い合わせられる（batch 件ずつ）。値は円（応答は 100 倍の整数）。
- 価格が返らない作品だけ、1 作品ずつ基本の情報（無料か・発売前か・作品か）を問い合わせて区別する（最大 max_detail 件。残りは次の回）。
- 区別（status）:
  paid = 価格が返った（通常価格・現在価格・割引率。割引率は応答の値で、通常価格と現在価格から計算した値と食い違えば割引なしとして扱わない＝そのまま記録しない）
  free = ストアが無料と示した / coming_soon = 発売前と示した / unknown = 価格も無料の印もない（販売されていない・地域の制限など）
  取得できなかった作品は記録しない（前の値は取得の時刻つきで残り、画面は古ければ出さない）。架空の価格・0 円は作らない。
- 毎回、作品の情報のあるすべての作品を問い合わせる（取得の間隔は min_interval_hours。価格は変わりやすいので毎日）。
利用条件は sources.steam_store と同じ経路（config/source_terms.toml）。
"""
from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime, timezone

from game_signal_scout.sources.contract import Batch, SourceItem, SourceReader

PRICES = "https://store.steampowered.com/api/appdetails?appids={ids}&cc={cc}&filters=price_overview"
DETAIL = "https://store.steampowered.com/api/appdetails?appids={appid}&cc={cc}&l=japanese&filters=basic,release_date"
STORE = "https://store.steampowered.com/app/{appid}/"


def price_value(appid: str, data, detail: dict | None, country: str, at: str) -> dict | None:
    """応答から共通の価格の形を作る。区別できなければ None（記録しない）。"""
    base = {"country": country, "url": STORE.format(appid=appid), "checked_at": at}
    po = data.get("price_overview") if isinstance(data, dict) else None
    if isinstance(po, dict) and po.get("currency") and isinstance(po.get("final"), int) and isinstance(po.get("initial"), int):
        ini, fin = po["initial"] / 100, po["final"] / 100
        off = int(po.get("discount_percent") or 0)
        calc = round((1 - fin / ini) * 100) if ini > 0 else 0
        if off and abs(off - calc) > 1:          # 応答の割引率が価格と合わない: 割引率を出さない
            off = 0
        if not off:
            ini = fin                            # 割引中でなければ通常価格 = 現在価格
        num = lambda v: int(v) if float(v).is_integer() else v
        return {**base, "status": "paid", "currency": po["currency"], "initial": num(ini), "final": num(fin), "discount": off}
    if detail is None:
        return None
    if detail.get("is_free") is True:
        return {**base, "status": "free"}
    if (detail.get("release_date") or {}).get("coming_soon") is True:
        return {**base, "status": "coming_soon"}
    return {**base, "status": "unknown"}


class SteamPrices(SourceReader):
    conn = None     # 収集の Service が渡す（対象の作品を引く）

    def read(self, cursor: dict | None) -> Iterator[Batch]:
        from game_signal_scout.repositories import catalog
        s = self.settings
        cc, size, max_detail = str(s.get("country", "jp")), int(s.get("batch_size", 50)), int(s.get("max_detail", 300))
        apps = [str(a) for a in s.get("appids") or []] or (catalog.all_appids(self.conn) if self.conn is not None else [])
        detail_left = max_detail
        for i in range(0, len(apps), size):
            chunk = apps[i:i + size]
            body = self.http.get_json(self.name, PRICES.format(ids=",".join(chunk), cc=cc))
            if body is None:
                continue                          # 通信の失敗（記録は Fetcher.log）。次の回に取り直す
            now = datetime.now(timezone.utc)
            items = []
            for a in chunk:
                e = body.get(a) or {}
                if not e.get("success"):
                    continue
                data, detail = e.get("data"), None
                if not (isinstance(data, dict) and data.get("price_overview")):
                    if detail_left <= 0:
                        continue
                    detail_left -= 1
                    d = ((self.http.get_json(self.name, DETAIL.format(appid=a, cc=cc)) or {}).get(a) or {})
                    if not d.get("success") or not isinstance(d.get("data"), dict):
                        continue
                    detail = d["data"]
                    if detail.get("type") not in (None, "game"):
                        continue
                v = price_value(a, data, detail, cc.upper(), now.isoformat())
                if v is None:
                    continue
                p = {"appid": a, "price": v}
                # 版に確かめた時刻を含める: 価格が同じでも、確かめた時刻（鮮度）を毎回更新する
                items.append(SourceItem(self.name, a, now, p, json.dumps(p, sort_keys=True)))
            yield Batch(items, {"done": i + len(chunk), "total": len(apps)})

    @staticmethod
    def attributes(item_id: str, received_at, payload: dict) -> list[tuple[str, str, object]]:
        return [(str(payload.get("appid") or item_id), "price", payload["price"])] if payload.get("price") else []
