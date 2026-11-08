"""Anime の catalog（作品情報の取得元）の Game 版の入口。Game の作品情報は game_profile（取得元 steam_store）。"""


def load_settings() -> dict:
    return {}


def provider_name(settings: dict) -> str:
    return "steam_store"
