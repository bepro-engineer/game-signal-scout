"""作品の情報の取得元: Steam のストアの作品情報（store.steampowered.com/api/appdetails。キー不要・日本語）。レビューは取らない。

- 読むのは「作品の情報を揃える対象の作品」だけ（repositories/catalog.targets: プレイヤーの報告・発言の多い作品のうち、情報がない・古いもの）。
  対象は収集の Service が渡す接続（self.conn）から引く。取得元の名前で共通の処理を分けない。
- 1 作品 1 回の取得（最小の間隔は Fetcher の min_interval）。束は batch_size 件ごと（途中で落ちても、保存した作品は取り直さない）。
- 保存するのは、作品を選ぶのに使う項目だけ（名前・種類・短い説明・ゲーム内容〔日本語・英語〕・画像の URL・ジャンル・カテゴリ・機種・発売日・言語）。
- 作品でない・取れなかった app ID も「取れなかった」として保存する（毎日取りに行かない。refresh_days の後に取り直す）。
画像は Steam の CDN の URL を持つだけで、複製しない（表示は利用者のブラウザが Steam から読む）。利用条件は Issue #2 の調査のとおり未確定（非公開の試作）。
"""
from __future__ import annotations

import hashlib
import re
import json
from collections.abc import Iterator
from datetime import datetime, timezone

from game_signal_scout.sources.contract import Batch, SourceItem, SourceReader

URL = "https://store.steampowered.com/api/appdetails?appids={appid}&l=japanese&cc=jp"
URL_EN = "https://store.steampowered.com/api/appdetails?appids={appid}&l=english&cc=us&filters=basic"   # ゲーム内容の英語の文だけ
URL_NAME = "https://store.steampowered.com/api/appdetails?appids={appid}&l={l}&cc=us&filters=basic"   # その言語の表示名
NAME_LANGS = {"tchinese": "zh-Hant", "schinese": "zh-Hans", "koreana": "ko"}
KEEP = ("type", "name", "short_description", "header_image", "genres", "categories", "platforms", "release_date", "supported_languages", "controller_support")
ABOUT_MAX = 4000


def about_text(html: str | None) -> str | None:
    """「このゲームについて」の HTML を文にする（画像・動画・装飾を除き、段落と見出しは改行で残す）。長すぎる文は ABOUT_MAX 字で切る。"""
    import html as h
    import re
    if not html:
        return None
    t = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", "", html)
    t = re.sub(r"(?i)<br\s*/?>|</(p|h\d|li|div|ul|ol)>", "\n", t)
    t = re.sub(r"(?i)<li[^>]*>", "・", t)
    t = h.unescape(re.sub(r"<[^>]+>", "", t)).replace("\u00a0", " ")
    t = "\n".join(x.strip() for x in t.splitlines())
    t = re.sub(r"\n{3,}", "\n\n", t).strip()
    t = re.sub(r"(?m)^(・[^\n]*)\n\n(?=・)", r"\1\n", t)   # 箇条書きの項目の間の空行（li と br の重なり）を詰める（#7）
    if len(t) > ABOUT_MAX:
        t = t[:ABOUT_MAX].rsplit("\n", 1)[0].rstrip() + "…"
    return t or None


def pick(data: dict) -> dict:
    out = {k: data.get(k) for k in KEEP if k in data}
    out["genres"] = [g.get("description") for g in data.get("genres") or [] if g.get("description")]
    out["categories"] = [{"id": c.get("id"), "description": c.get("description")} for c in data.get("categories") or []]
    out["release_date"] = (data.get("release_date") or {}).get("date")
    out["coming_soon"] = bool((data.get("release_date") or {}).get("coming_soon"))
    out["about"] = about_text(data.get("about_the_game"))
    return out


# ---- ストアの項目を共通の作品の情報（game_profile）の形へ直す
# 遊び方（Steam のカテゴリの ID → 利用者の言葉）。作品を選ぶ切り口の正本はこの言葉で、取得元のカテゴリの名前を画面に出さない
STEAM_MODES = {2: "ひとりで遊べる", 9: "協力プレイ", 38: "協力プレイ", 39: "協力プレイ", 24: "画面分割・同じ画面で", 37: "画面分割・同じ画面で",
               49: "対戦", 36: "対戦", 47: "対戦", 28: "コントローラーで遊べる"}
STEAM_PLATFORMS = {"windows": "Windows", "mac": "Mac", "linux": "Linux・Steam Deck"}


def profile_row(item_id: str, received_at, p: dict) -> dict | None:
    if p.get("type") != "game" or not p.get("name"):
        return None
    modes = list(dict.fromkeys(STEAM_MODES[c["id"]] for c in p.get("categories") or [] if c.get("id") in STEAM_MODES))
    langs = p.get("supported_languages") or ""
    ja_text = "日本語" in langs if langs else None
    ja_voice = None
    if ja_text:
        i = langs.find("日本語")
        ja_voice = langs[i + 3:i + 40].lstrip().startswith("<strong>*</strong>")   # 「*」の印は音声も対応
    return {"appid": p.get("appid") or item_id, "source": "", "item_id": item_id, "title": p["name"], "summary": (p.get("short_description") or "").strip() or None,
            "image_url": p.get("header_image"), "genres": p.get("genres") or [], "modes": modes,
            "platforms": [label for k, label in STEAM_PLATFORMS.items() if (p.get("platforms") or {}).get(k)],
            "ja_text": ja_text, "ja_voice": ja_voice, "released": p.get("release_date"),
            "store_url": f"https://store.steampowered.com/app/{p.get('appid') or item_id}/", "fetched_at": received_at,
            "coming_soon": p.get("coming_soon"),
            "names": {**({"en": p["name_en"]} if p.get("name_en") else {}), **(p.get("names") or {})} or None,
            # ゲーム内容: 日本語の取得で返った文が日本語ならそれ（日本語の文がない作品は英語の文が返る）、英語は英語の取得の文
            "about_ja": p.get("about") if JA_CHARS.search(p.get("about") or "") else None,
            "about_en": p.get("about_en") or (p.get("about") if p.get("about") and not JA_CHARS.search(p["about"]) else None)}


JA_CHARS = re.compile(r"[\u3040-\u30ff]")   # かな（漢字だけの中国語の文を日本語と取らない）


class SteamStore(SourceReader):
    conn = None     # 収集の Service が渡す（対象の作品を引く）

    def read(self, cursor: dict | None) -> Iterator[Batch]:
        from game_signal_scout.repositories import catalog
        s = self.settings
        todo = catalog.targets(self.conn, int(s.get("active_days", 90)), int(s.get("max_games", 150)), int(s.get("refresh_days", 30)), self.name) if self.conn else []
        size = int(s.get("batch_size", 20))
        items: list[SourceItem] = []
        for i, appid in enumerate(todo, 1):
            body = self.http.get_json(self.name, URL.format(appid=appid))
            if body is None:
                continue                      # 通信の失敗（記録は Fetcher.log）。次の回に取り直す
            entry = (body or {}).get(str(appid)) or {}
            payload = pick(entry["data"]) if entry.get("success") and isinstance(entry.get("data"), dict) else {"type": None, "unavailable": True}
            payload["appid"] = str(appid)
            if not payload.get("unavailable"):     # ゲーム内容の英語の文（英語の画面に出す）
                en = self.http.get_json(self.name, URL_EN.format(appid=appid)) or {}
                ed = (en.get(str(appid)) or {}).get("data")
                payload["about_en"] = about_text(ed.get("about_the_game")) if isinstance(ed, dict) else None
                if isinstance(ed, dict) and ed.get("name"):
                    payload["name_en"] = ed["name"]
                names = {}
                for l, code in NAME_LANGS.items():              # 中国語・韓国語の掲示板の発言を作品に結び付ける題名
                    nd = ((self.http.get_json(self.name, URL_NAME.format(appid=appid, l=l)) or {}).get(str(appid)) or {}).get("data")
                    if isinstance(nd, dict) and nd.get("name"):
                        names[code] = nd["name"]
                payload["names"] = names
            version = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
            items.append(SourceItem(self.name, str(appid), datetime.now(timezone.utc), payload, version))
            if len(items) >= size or i == len(todo):
                yield Batch(items, {"last_appid": str(appid), "done": i, "total": len(todo)})
                items = []
        if items:
            yield Batch(items, {"done": len(todo), "total": len(todo)})

    @staticmethod
    def profile(item_id: str, received_at, payload: dict) -> dict | None:
        return profile_row(item_id, received_at, payload)
