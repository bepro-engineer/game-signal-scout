"""作品の属性の取得元: Wikidata（CC0）の、Steam の app ID（P1733）を持つ作品の開発元（P178）と、その国（P17）。

問い合わせは Wikidata Query Service（公式の文書がプログラムからの GET を案内。名前と連絡先を名乗る・60 秒あたり 60 秒の処理まで・同時 5 まで）。
1 回に 100 作品まで。Wikidata に作品・開発元・国の記載がなければ、その項目は作らない（画面は不明・未確認）。推定しない。
"""
from __future__ import annotations

import json
import urllib.parse
from collections.abc import Iterator
from datetime import datetime, timezone

from game_signal_scout.sources.contract import Batch, SourceItem, SourceReader

URL = "https://query.wikidata.org/sparql?format=json&query={q}"
# 名前は日本語（なければ英語）と、英語の表示のための英語の名前（devEn・countryEn。#2）
QUERY = """SELECT ?app ?game ?dev ?devLabel ?devEn ?country ?countryLabel ?countryEn WHERE {
 VALUES ?app { %s }
 ?game wdt:P1733 ?app .
 OPTIONAL { ?game wdt:P178 ?dev . OPTIONAL { ?dev rdfs:label ?devEn FILTER(lang(?devEn) IN ("en", "mul")) }
   OPTIONAL { ?dev wdt:P17 ?country . OPTIONAL { ?country rdfs:label ?countryEn FILTER(lang(?countryEn) IN ("en", "mul")) } } }
 SERVICE wikibase:label { bd:serviceParam wikibase:language "ja,en". } }"""


def entity(uri: str | None) -> str | None:
    return uri.rsplit("/", 1)[-1] if uri else None


class WikidataWorks(SourceReader):
    conn = None

    def read(self, cursor: dict | None) -> Iterator[Batch]:
        from game_signal_scout.repositories import catalog
        apps = [str(a) for a in self.settings.get("appids") or []] or (
            catalog.attribute_targets(self.conn, self.name, int(self.settings.get("refresh_days", 30)), self.settings.get("work_keyspace") or "") if self.conn is not None else [])
        now = datetime.now(timezone.utc)
        for i in range(0, len(apps), 100):
            chunk = apps[i:i + 100]
            q = QUERY % " ".join(f'"{a}"' for a in chunk if a.isdigit())
            body = self.http.get_json(self.name, URL.format(q=urllib.parse.quote(q)))
            if body is None:
                yield Batch([], {"done": i, "total": len(apps), "failed": True})
                return
            found: dict[str, dict] = {}
            for b in (body.get("results") or {}).get("bindings") or []:
                a = b["app"]["value"]
                w = found.setdefault(a, {"appid": a, "entity": entity(b["game"]["value"]), "developers": {}})
                if "dev" in b:
                    d = w["developers"].setdefault(entity(b["dev"]["value"]), {"name": b.get("devLabel", {}).get("value"), "name_en": b.get("devEn", {}).get("value"),
                                                                              "countries": [], "countries_en": []})
                    if not d.get("name_en") and b.get("devEn", {}).get("value"):
                        d["name_en"] = b["devEn"]["value"]
                    c = b.get("countryLabel", {}).get("value")
                    if c and c not in d["countries"]:
                        d["countries"].append(c)
                        d["countries_en"].append(b.get("countryEn", {}).get("value") or c)
            items = []
            for a in chunk:   # Wikidata にない作品も「確かめた」記録を残す（取り直しの間隔のため。属性は作らない）
                w = found.get(a) or {"appid": a, "entity": None, "developers": {}, "no_attributes": True}
                w = {**w, "developers": [{"id": k, **v} for k, v in sorted(w["developers"].items())]}
                items.append(SourceItem(self.name, a, now, w, json.dumps(w, sort_keys=True, ensure_ascii=False)))
            yield Batch(items, {"done": i + len(chunk), "total": len(apps)})

    @staticmethod
    def attributes(item_id: str, received_at, payload: dict) -> list[tuple[str, str, object]]:
        a = str(payload.get("appid") or item_id)
        devs = [d for d in payload.get("developers") or [] if d.get("name")]
        if not devs:
            return []
        return [(a, "developer_countries", [{"developer": d["name"], "countries": d.get("countries") or [], "ref": f"https://www.wikidata.org/wiki/{d['id']}",
                                             **({"developer_en": d["name_en"]} if d.get("name_en") else {}),
                                             **({"countries_en": d["countries_en"]} if d.get("countries_en") else {})}
                                            for d in devs])]
