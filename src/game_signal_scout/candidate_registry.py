"""Anime の candidate_registry から、流用した部品が使う 2 つの関数だけを写す（表記の鍵・6 時間の窓）。"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta, timezone


def candidate_key(term: str) -> str:
    n = unicodedata.normalize("NFKC", term).casefold()
    return re.sub(r"[\s\W_]+", "", n)


def window_start(t: datetime, hours: int) -> datetime:
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    step = hours * 3600
    return epoch + timedelta(seconds=int((t - epoch).total_seconds()) // step * step)
