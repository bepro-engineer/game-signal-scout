"""Anime の repositories/work の Game 版（流用した部品が使う関数だけ）。Game の作品は親子なし。
ここでの鍵 "app:<作品の番号>" は、流用した画面の部品の中だけで使う鍵で、作品の番号はこのサイトの作品の番号（repositories/work_key。取得元の番号ではない）。"""


def list_keys_by_work(conn, work_ids) -> dict:
    return {int(w): [f"app:{int(w)}"] for w in work_ids}


def list_work_ids_by_keys(conn, keys) -> list[int]:
    return sorted({int(k[4:]) for k in keys if str(k).startswith("app:") and k[4:].isdigit()})


def get_parent_id(conn, work_id):
    return None
