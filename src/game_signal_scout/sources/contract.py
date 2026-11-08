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
    version: str | None = None      # 取得元での版（編集された日時など）。変われば保存を置き換え、正規化をやり直す


@dataclass
class Batch:
    """一度に保存する項目と、この束を保存し終えた後の続きの位置。位置は束と同じ取引で記録する（途中で落ちても重複・欠落しない）。

    cursor の任意の鍵:
      complete … 取得元の全体を読み終えた
      snapshot … 取得元が全件の写し（配布物）で、その名前。全体を読み終えたら、写しにない項目を消す（削除への追従）

    gone: 取得元で消えた項目の ID（ストリームの削除・更新で対象外になった投稿）。actors_gone: 消えた投稿者の参照（アカウントの削除・停止）。
    どちらも収集の Service が、項目の保存より先に、同じ取引で消す（Anime の Listing の gone・actor_gone と同じ扱い）。
    """
    items: list[SourceItem]
    cursor: dict
    gone: list[str] = field(default_factory=list)
    actors_gone: list[str] = field(default_factory=list)


class SourceNotConfiguredError(RuntimeError):
    """必須の設定がない取得元（待っても直らない）。"""
    retryable, error_type = False, "source_not_configured"


class SourceCorruptError(RuntimeError):
    """取得元のデータが壊れている（形が違う・途中で切れている）。retryable は、取り直せば直る見込みがあるか。"""

    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.retryable, self.error_type = retryable, "source_corrupt"


class SourceReader(ABC):
    name: str = ""
    internal_id_markers: tuple[str, ...] = ()   # 公開の文書に出してはいけない、投稿者・投稿の内部の識別子の印（Anime と同じ。公開前の検査が集める）

    def __init__(self, settings: dict, http):
        self.settings, self.http = settings, http

    @abstractmethod
    def read(self, cursor: dict | None) -> Iterator[Batch]:
        """cursor（前回の続きの位置。初回は None）から読み、束を順に返す。"""

    # ---- 取得しない用途の契約（Anime の sources/contract と同じ名前・同じ既定。取得元の決まりがあれば上書きする）

    def quotable(self, conn, item_ids: list[str]) -> set[str]:
        """公開の画面に抜粋とリンクを出してよい項目の ID（既定: すべて。投稿者・内容のラベルのある取得元はここで判定する）。"""
        return set(item_ids)

    def permalink(self, item: dict) -> str | None:
        """項目の公開の URL（item は item_id・url。既定: 保存した url のうち https のもの。ID を URL とみなさない）。"""
        url = item.get("url")
        return url if url and str(url).startswith("https://") else None

    # ---- 取得元の形を、共通の形へ直す（Adapter の責務。共通の正規化〔services/normalize〕が、記述の normalizer の種類に応じて呼ぶ）
    # 取得元の形がすでに共通の形なら、既定のまま（何もしない）。取得元の名前で分ける処理は、ここ（各取得元のクラス）にだけ書く。

    @staticmethod
    def voice(item_id: str, payload: dict) -> dict:
        """発言: author・text・lang・url・link・link_title・tags、作品が取得元で決まるなら appid。
        取得元が持つなら stance（positive / negative）・playtime_minutes・flags（取得元が示す印）も。"""
        return payload

    @staticmethod
    def profile(item_id: str, received_at, payload: dict) -> dict | None:
        """作品の情報（game_profile の列）。作品でない項目は None。"""
        raise NotImplementedError

    @staticmethod
    def report(item_id: str, payload: dict) -> tuple:
        """動作の報告（player_report の列: item_id・appid・title・at・failed・config_hash・tool_version・notes）。"""
        raise NotImplementedError
