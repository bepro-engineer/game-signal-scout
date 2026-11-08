"""対象日（日本時間の放送日 3:00〜翌 3:00）の範囲。"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))
MON_EN = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]   # 英語の月の略称（画面の日付）


def broadcast_day(ts: datetime) -> date:
    """時刻 ts を含む放送日（日本時間 3:00〜翌 3:00）。全 Source・日次・常駐で同じ 1 つの区切り。"""
    return (ts.astimezone(JST) - timedelta(hours=3)).date()


def day_range(d: date) -> tuple[datetime, datetime]:
    start = datetime(d.year, d.month, d.day, 3, tzinfo=JST).astimezone(timezone.utc)
    return start, start + timedelta(days=1)


def default_day(now: datetime | None = None, settle_minutes: int = 30) -> date:
    """終わって落ち着いた最新の放送日（日次の既定の対象日）。"""
    now = (now or datetime.now(timezone.utc)) - timedelta(minutes=settle_minutes)
    j = now.astimezone(JST) - timedelta(hours=3)
    return (j - timedelta(days=1)).date()


