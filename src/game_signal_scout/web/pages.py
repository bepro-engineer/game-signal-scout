"""ページの骨組み（View）。テンプレート（web/templates。Jinja2）から HTML を作り、処理の層のアプリ（web/routers/pages）が返す。
画面の部品（JavaScript・CSS・画像）は static/ に置き、Apache が直接配る（開発ではアプリも配る）。

- 共通の枠: templates/base.html。ページごとの本文: templates/pages/<名前>.html（本文は画面の部品が接続口から読んで描く）。
- 説明のページの本文: templates/info/<名前>.html。運営者・連絡先・日付・システム構成は config/site_info.toml。
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from game_signal_scout import config
from game_signal_scout.days import MON_EN

WEB = Path(__file__).resolve().parent
STATIC = WEB / "static"
TEMPLATES = WEB / "templates"
ALWAYS_CSS = ["base.css", "foot.css", "palette.css"]   # すべてのページ。配色（palette）は最後に読む
CSS_BASE = ["style.css", "gaze.css"]
CSS_PAGE = ["style.css", "gaze.css", "spread.css", "revival.css", "postair.css"]
CSS_INFO = ["style.css", "info.css"]


@dataclass(frozen=True)
class Page:
    title_ja: str
    title_en: str
    stylesheets: list[str]
    data: str = ""                   # 画面の部品（boot.js）が先に読む接続口（day / pages / search / work）。説明のページは空
    script: str = ""                 # ページの部品（static/<名前>.js）。説明のページは空
    extra_scripts: tuple[str, ...] = ()
    info: bool = False               # 説明のページ（本文は templates/info/<名前>.html）


PAGES: dict[str, Page] = {
    "index": Page("ダッシュボード", "Dashboard", CSS_BASE, "day", "dashboard.js", ("world.js",)),
    "spread": Page("世界で広がる作品", "Spreading worldwide", CSS_BASE + ["spread.css"], "day", "spread.js"),
    "lang": Page("言語別の作品", "Titles by language", CSS_BASE, "day", "lang.js"),
    "revival": Page("再燃している作品", "Heating up again", CSS_PAGE, "pages", "revival.js"),
    "langspread": Page("言語圏の広がり", "Language spread", CSS_PAGE + ["langspread.css"], "pages", "langspread.js"),
    # 作品詳細・作品を探す: 追加の作品情報の表示の語（タグ・役割・視聴状況の日本語。ADR 0041）は extra.js
    "search": Page("作品を探す", "Find titles", CSS_PAGE + ["search.css", "extra.css"], "search", "search.js", ("extra.js",)),
    # Game: 遊び方のページ（作品を探すと同じ部品。ページの名前で遊び方を絞る: search.js の MODE_PAGES）
    "solo": Page("一人（ソロ）で遊べる", "Single-player", CSS_PAGE + ["search.css", "extra.css"], "search", "search.js", ("extra.js",)),
    "coop": Page("協力プレイで遊べる", "Co-op", CSS_PAGE + ["search.css", "extra.css"], "search", "search.js", ("extra.js",)),
    "versus": Page("対戦プレイで遊べる", "Versus", CSS_PAGE + ["search.css", "extra.css"], "search", "search.js", ("extra.js",)),
    "pad": Page("コントローラで遊べる", "Controller", CSS_PAGE + ["search.css", "extra.css"], "search", "search.js", ("extra.js",)),
    "work": Page("作品詳細", "Title details", CSS_PAGE + ["work.css", "extra.css"], "work", "work.js", ("extra.js",)),
    "about": Page("このサイトについて", "About", CSS_INFO, info=True),
    "guide": Page("データの見方", "How to read the data", CSS_INFO, info=True),
    "rights": Page("出典と権利について", "Sources and rights", CSS_INFO, info=True),
    "terms": Page("利用規約・データ利用ポリシー", "Terms of use and data policy", CSS_INFO, info=True),
    "privacy": Page("プライバシーポリシー", "Privacy policy", CSS_INFO, info=True),
}

_ENV = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=select_autoescape(["html"]), keep_trailing_newline=True)


@lru_cache(maxsize=1)
def asset_version() -> str:
    """画面の部品の版の印（中身の hash。ブラウザに古い部品が残らないように URL に付ける）。版を入れ替えると常駐が起動し直すので 1 回だけ計算する。"""
    h = hashlib.sha1()
    for f in sorted(STATIC.iterdir()):
        if f.is_file():
            h.update(f.read_bytes())
    return h.hexdigest()[:10]


def _format_date(d: date, ja: bool) -> str:
    return f"{d.year}年{d.month}月{d.day}日" if ja else f"{MON_EN[d.month - 1]} {d.day}, {d.year}"


def _contact(contact: str, ja: bool) -> Markup:
    """連絡先（未設定なら「準備中」。無い窓口を書かない）。"""
    if not contact:
        return Markup("準備中です（一般公開の前に、このページに掲載します）" if ja else
                      "Being prepared (it will be posted on this page before the site opens to the public)")
    href = contact if contact.startswith(("https://", "mailto:")) else f"mailto:{contact}"
    return Markup('<a href="{}">{}</a>').format(href, contact.removeprefix("mailto:"))


def info_values() -> dict:
    """説明のページの差し込みの値（config/site_info.toml）。"""
    info = config.load_toml("site_info.toml")
    op, dt = info.get("operator", {}), info.get("dates", {})
    contact = str(op.get("contact") or "").strip()
    out = {"OPERATOR_JA": op.get("name_ja", ""), "OPERATOR_EN": op.get("name_en", ""), "CONTACT_JA": _contact(contact, True), "CONTACT_EN": _contact(contact, False)}
    for k in ("established", "updated"):
        d = date.fromisoformat(str(dt[k]))
        out[f"{k.upper()}_JA"], out[f"{k.upper()}_EN"] = _format_date(d, True), _format_date(d, False)
    return out


def info_main(name: str) -> str:
    """説明のページの本文（templates/info/<名前>.html）。作業用の注記（HTML の注釈）は公開しない。"""
    body = re.sub(r"<!--.*?-->", "", _ENV.get_template(f"info/{name}.html").render(**info_values()), flags=re.S)
    return f'<main class="info" id="info-{name}">\n{body}\n</main>'


def page_html(name: str, plain: str = "") -> str:
    """plain: JavaScript を動かさない読み手のための文だけの要約（web/plain.py）。<main> の最後に置く。"""
    page = PAGES[name]
    main = info_main(name) if page.info else _ENV.get_template(f"pages/{name}.html").render().rstrip("\n")
    if plain and main.endswith("</main>"):
        main = main[: -len("</main>")] + "\n" + str(plain) + "\n</main>"
    return _ENV.get_template("base.html").render(page=page, ver=asset_version(), main=Markup(main),
                                                 stylesheets=list(dict.fromkeys(page.stylesheets + ALWAYS_CSS)))
