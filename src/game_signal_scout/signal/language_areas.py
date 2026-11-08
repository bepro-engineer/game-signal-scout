"""言語圏 → 世界地図の国・地域（config/language_areas.toml。ADR 0049・2026-10-15 改訂）。

世界地図は投稿者の所在地ではなく、観測した言語が使われる地域の広がりを示す。国・地域と言語圏は多対多。国ごとの言語の役割は
primary（主要な社会言語: 塗り）/ shared（共通語・第二言語: 細い斜線）/ regional・uncertain（塗らない）。公用語かどうかでは決めない。
集計は言語圏の単位で、国で人数・作品を足さない。
"""
from __future__ import annotations

import tomllib
from functools import lru_cache
from pathlib import Path

from game_signal_scout import config

CONFIG = config.CONFIG / "language_areas.toml"
PAINTED = ("primary", "shared")
ROLE_CODE = {"primary": "p", "shared": "s"}


@lru_cache(maxsize=1)
def load(path: str | None = None) -> dict:
    return tomllib.loads(Path(path or CONFIG).read_text())


def enabled() -> bool:
    return bool(load().get("enabled", False))


def countries() -> dict[str, list[str]]:
    """言語圏 → 地図で示す国・地域（primary と shared。regional・uncertain は含めない）。"""
    return {a: list(dict.fromkeys(v.get("primary", []) + v.get("shared", []))) for a, v in load()["areas"].items()}


def roles() -> dict[str, dict[str, str]]:
    """言語圏 → 国 → p（主要な社会言語）/ s（共通語・第二言語）。"""
    out: dict[str, dict[str, str]] = {}
    for a, v in load()["areas"].items():
        for r in PAINTED:
            for cc in v.get(r, []):
                out.setdefault(a, {}).setdefault(cc, ROLE_CODE[r])
    return out


def why() -> dict[str, dict[str, str]]:
    """言語圏 → 国 → その役割にした理由（出典つき。地図で指を乗せたときに出す）。"""
    return {a: dict(v.get("why") or {}) for a, v in load()["areas"].items() if v.get("why")}


def area_of(code: str) -> str:
    """投稿の言語コード → 言語圏（方言・文字の区別のコードは aliases でまとめる。対応表にないコードはそのまま）。"""
    for a, v in load()["areas"].items():
        if code == a or code in (v.get("aliases") or []):
            return a
    return code


def for_view(codes: list[str]) -> dict:
    """画面に渡す: 観測した言語圏の国・役割・理由だけ（データを小さく）。"""
    c, r, w = countries(), roles(), why()
    return {"countries": {a: c[a] for a in codes if a in c}, "roles": {a: r[a] for a in codes if a in r}, "why": {a: w[a] for a in codes if a in w}}
