"""Anime の catalog（作品情報の取得元）の Game 版の入口。Game の作品情報は game_profile（記述の normalizer が profiles の取得元が作る）。
取得元の名前は持たない（作品の情報の取得元も、記述で替えられる 1 つの入力）。"""


def load_settings() -> dict:
    return {}


def provider_name(settings: dict) -> str:
    return "profiles"
