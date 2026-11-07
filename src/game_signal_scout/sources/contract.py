"""取得元の契約（Anime の sources/contract を Game の最小の形にしたもの）。

取得元のクラス（SourceReader の子）が書くのは「どこから・どう読むか」だけ。保存・続きの位置の記録・再試行は
収集の Service（services/collect）が、どの取得元にも同じ手順で行う。取得元を足すときに書くのは、
SourceReader の子クラスと、記述（config/sources.toml の adapter）と試験だけ。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class SourceItem:
    """取り込む 1 件。payload は取得元の形のまま（正規化は services/normalize）。"""
    source: str
    item_id: str
    occurred_at: datetime
    payload: dict = field(default_factory=dict)


@dataclass
class Batch:
    """一度に保存する項目と、この束を保存し終えた後の続きの位置。位置は束と同じ取引で記録する（途中で落ちても重複・欠落しない）。"""
    items: list[SourceItem]
    cursor: dict


class SourceNotConfiguredError(RuntimeError):
    """必須の設定がない取得元。"""


class SourceReader(ABC):
    name: str = ""

    def __init__(self, settings: dict, http):
        self.settings, self.http = settings, http

    @abstractmethod
    def read(self, cursor: dict | None) -> Iterator[Batch]:
        """cursor（前回の続きの位置。初回は None）から読み、束を順に返す。"""
