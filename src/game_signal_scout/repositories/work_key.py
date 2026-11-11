"""作品の鍵（game_work・game_work_key。#3 段階 B。ARCHITECTURE §8）: 取得元の番号 → 作品の番号、作品の番号 → 取得元の番号。

どの取得元の番号も同じ形で引く。名前空間（keyspace）は取得元の記述（config/sources.toml の work_keyspace）が決め、ここは名前空間の名前で分岐しない。
知らない番号は新しい作品にする（作品の番号は連番 game_work_seq。既存の作品と重ならない範囲）。
"""
from __future__ import annotations

TABLES = ("game_profile", "player_post", "game_attribute", "game_insight", "game_activity", "game_upcoming", "game_assets", "player_report", "shift_event")   # 作品の番号を持つ表


def resolve(conn, keyspace: str, ext_ids) -> dict[str, str]:
    """取得元の番号 → 作品の番号（知らない番号は新しい作品を作る）。呼ぶ側の transaction の中で使う。"""
    ids = sorted({str(x) for x in ext_ids if x not in (None, "")})
    if not ids:
        return {}
    if not keyspace:
        raise ValueError("作品の番号を渡す取得元に、記述の work_keyspace がない")
    found = dict(conn.execute("SELECT ext_id, work_id FROM game_work_key WHERE keyspace = %s AND ext_id = ANY(%s)", (keyspace, ids)).fetchall())
    for x in (i for i in ids if i not in found):
        w = conn.execute("INSERT INTO game_work (work_id) SELECT nextval('game_work_seq')::text RETURNING work_id").fetchone()[0]
        row = conn.execute("INSERT INTO game_work_key (keyspace, ext_id, work_id) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING RETURNING work_id",
                           (keyspace, x, w)).fetchone()
        if row is None:   # 同時に入った: 入っている方を使う（作った作品の番号は使わない）
            conn.execute("DELETE FROM game_work WHERE work_id = %s", (w,))
            row = conn.execute("SELECT work_id FROM game_work_key WHERE keyspace = %s AND ext_id = %s", (keyspace, x)).fetchone()
        found[x] = row[0]
    return found


def external(conn, keyspace: str, work_ids) -> dict[str, str]:
    """作品の番号 → その名前空間の取得元の番号（鍵のない作品は入らない）。"""
    ids = [str(w) for w in work_ids]
    if not ids or not keyspace:
        return {}
    rows = conn.execute("SELECT work_id, min(ext_id) FROM game_work_key WHERE keyspace = %s AND work_id = ANY(%s) GROUP BY work_id", (keyspace, ids)).fetchall()
    return dict(rows)


def own_ids(conn, keyspace: str, work_ids) -> list[str]:
    """作品の番号の並び → その取得元の番号の並び（並びを保つ。鍵のない作品は飛ばす）。"""
    m = external(conn, keyspace, work_ids)
    return [m[str(w)] for w in work_ids if str(w) in m]


def adopt_existing(conn, keyspace: str) -> int:
    """既存の作品（移行の前からある番号。連番の範囲より小さい数字）の鍵を、その番号のまま名前空間 keyspace に入れる（一度だけの移行。ARCHITECTURE §8）。"""
    union = " UNION ".join(f"SELECT work_id FROM {t} WHERE work_id IS NOT NULL" for t in TABLES)
    conn.execute(f"INSERT INTO game_work (work_id) SELECT DISTINCT work_id FROM ({union}) x WHERE work_id ~ '^[0-9]{{1,9}}$' ON CONFLICT DO NOTHING")   # 移行の後に入った行も
    with conn.cursor() as cur:
        cur.execute("INSERT INTO game_work_key (keyspace, ext_id, work_id) SELECT %s, work_id, work_id FROM game_work "
                    "WHERE work_id ~ '^[0-9]{1,9}$' ON CONFLICT DO NOTHING", (keyspace,))
        return cur.rowcount


def keys_of(conn, work_ids) -> dict[str, list[str]]:
    """作品の番号 → 鍵（"<名前空間>:<番号>"）の一覧。"""
    out: dict[str, list[str]] = {}
    for w, k, x in conn.execute("SELECT work_id, keyspace, ext_id FROM game_work_key WHERE work_id = ANY(%s) ORDER BY 1, 2, 3", ([str(w) for w in work_ids],)):
        out.setdefault(w, []).append(f"{k}:{x}")
    return out
