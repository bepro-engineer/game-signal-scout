"""retry してよい失敗と、してはいけない失敗の分類（Anime の ops/errors から移植）。"""
from __future__ import annotations

import asyncio


class OpsError(Exception):
    retryable = False
    error_type = "error"


class RetryableError(OpsError):
    """待てば直る失敗（通信の一時的な失敗など）。"""
    retryable = True
    error_type = "transient"

    def __init__(self, message: str, error_type: str = "transient"):
        super().__init__(message)
        self.error_type = error_type


class LockedError(RetryableError):
    def __init__(self, message: str):
        super().__init__(message, "locked")


def classify(e: BaseException) -> tuple[bool, str]:
    """(retryable, error_type)。分類できない失敗は retry しない（同じ失敗を繰り返さないため）。"""
    if isinstance(e, OpsError):
        return e.retryable, e.error_type
    from game_signal_scout.sources.contract import SourceCorruptError, SourceNotConfiguredError
    if isinstance(e, (SourceCorruptError, SourceNotConfiguredError)):
        return e.retryable, e.error_type
    from game_signal_scout.config import WrongDatabaseError
    if isinstance(e, WrongDatabaseError):
        return False, "wrong_database"
    try:
        import psycopg
        if isinstance(e, psycopg.OperationalError):
            return True, "db_unavailable"
        if isinstance(e, (psycopg.errors.UndefinedTable, psycopg.errors.UndefinedColumn)):
            return False, "schema_mismatch"
    except ImportError:
        pass
    if isinstance(e, (TimeoutError, asyncio.TimeoutError)):
        return True, "timeout"
    if isinstance(e, (ConnectionError, OSError)):
        return True, "network"
    return False, "unexpected"
