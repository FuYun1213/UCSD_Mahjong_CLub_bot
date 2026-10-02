import os
import re
import sqlite3
import threading
from pathlib import Path

from mmr import compute_one_table


DEFAULT_DB_FILE = Path(__file__).resolve().parent / "mahjong.sqlite3"
DISCORD_SCORE_PAUSED_KEY = "discord_score_paused"


def normalize_name(value):
    return " ".join(str(value or "").casefold().split())


_SCHEMA_VERSIONS = {}
_SCHEMA_LOCK = threading.RLock()


def connect(db_file=None):
    path = Path(db_file or os.getenv("MAHJONG_DB_FILE") or DEFAULT_DB_FILE)
    connection = sqlite3.connect(str(path))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=5000")
    try:
        with _SCHEMA_LOCK:
            stat = path.stat()
            key = (str(path.resolve()), stat.st_ino)
            version = connection.execute("PRAGMA schema_version").fetchone()[0]
            if _SCHEMA_VERSIONS.get(key) != version:
                init_db(connection)
                _SCHEMA_VERSIONS[key] = connection.execute("PRAGMA schema_version").fetchone()[0]
        return connection
    except BaseException:
        connection.close()
        raise


def init_db(connection):
    connection.executescript(
        """
        PRAGMA journal_mode=WAL;

        CREATE TABLE IF NOT EXISTS players (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            name_key TEXT NOT NULL UNIQUE,
            current_mmr REAL NOT NULL DEFAULT 1500,
            total_pt REAL NOT NULL DEFAULT 0,
            history_highest_pt REAL NOT NULL DEFAULT 0,
            history_highest_mmr REAL NOT NULL DEFAULT 1500,
            games_played INTEGER NOT NULL DEFAULT 0,
            wins INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS games (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            played_at TEXT NOT NULL,
            quarter TEXT,
            source TEXT NOT NULL DEFAULT 'web',
            sheet_row INTEGER UNIQUE,
            sync_status TEXT NOT NULL DEFAULT 'pending',
            created_by TEXT NOT NULL DEFAULT 'web',
            yakuman_winner TEXT,
            yakuman_deal_in TEXT,
            yakuman_text TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS game_players (
            game_id INTEGER NOT NULL,
            player_id INTEGER NOT NULL,
            rank_order INTEGER NOT NULL,
            final_score INTEGER NOT NULL,
            placement INTEGER NOT NULL,
            mmr_before REAL NOT NULL,
            mmr_delta REAL NOT NULL,
            mmr_after REAL NOT NULL,
            pt_delta REAL NOT NULL,
            PRIMARY KEY (game_id, player_id),
            FOREIGN KEY (game_id) REFERENCES games(id),
            FOREIGN KEY (player_id) REFERENCES players(id)
        );

        CREATE TABLE IF NOT EXISTS app_config (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS game_score_summaries (
            game_id INTEGER PRIMARY KEY REFERENCES games(id),
            payload_json TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS yakuman_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id INTEGER,
            played_at TEXT NOT NULL,
            winner_id INTEGER NOT NULL,
            yakuman_name TEXT NOT NULL,
            deal_in TEXT NOT NULL DEFAULT '',
            note TEXT NOT NULL DEFAULT '',
            players_text TEXT NOT NULL DEFAULT '',
            photo_path TEXT NOT NULL DEFAULT '',
            photo_caption TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT 'web',
            source_key TEXT UNIQUE,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (game_id) REFERENCES games(id),
            FOREIGN KEY (winner_id) REFERENCES players(id)
        );

        CREATE TABLE IF NOT EXISTS deleted_yakuman_records (
            source_key TEXT PRIMARY KEY,
            deleted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    ensure_column(connection, "games", "quarter", "TEXT")
    ensure_column(connection, "games", "nfc_match_id", "TEXT")
    ensure_column(connection, "games", "started_at", "TEXT")
    ensure_column(connection, "games", "ended_at", "TEXT")
    ensure_column(connection, "games", "duration_seconds", "INTEGER")
    connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_games_nfc_match ON games(nfc_match_id)")

    # Ranking position is not a physical seat. Unknown historical winds stay NULL.
    ensure_column(connection, "games", "source_seat_order", "TEXT NOT NULL DEFAULT 'unknown'")
    ensure_column(connection, "game_players", "seat_wind", "TEXT")
    ensure_column(connection, "game_players", "source_position", "INTEGER")
    ensure_column(connection, "players", "history_highest_mmr", "REAL NOT NULL DEFAULT 1500")
    ensure_column(connection, "yakuman_records", "deal_in", "TEXT NOT NULL DEFAULT ''")
    ensure_column(connection, "yakuman_records", "photo_path", "TEXT NOT NULL DEFAULT ''")
    ensure_column(connection, "yakuman_records", "photo_caption", "TEXT NOT NULL DEFAULT ''")
    ensure_column(connection, "yakuman_records", "updated_at", "TEXT NOT NULL DEFAULT ''")
    connection.execute(
        """
        UPDATE yakuman_records
        SET updated_at = COALESCE(NULLIF(created_at, ''), CURRENT_TIMESTAMP)
        WHERE COALESCE(updated_at, '') = ''
        """
    )
    connection.execute(
        """
        UPDATE players
        SET history_highest_mmr = MAX(
            1500,
            COALESCE((SELECT MAX(gp.mmr_after) FROM game_players gp WHERE gp.player_id = players.id), 1500)
        )
        WHERE history_highest_mmr IS NULL OR history_highest_mmr <= 1500
        """
    )
    connection.execute(
        """
        INSERT OR IGNORE INTO yakuman_records (
            game_id, played_at, winner_id, yakuman_name, note, players_text, source, source_key, updated_at
        )
        SELECT
            g.id,
            g.played_at,
            p.id,
            TRIM(g.yakuman_text),
            '',
            (
                SELECT GROUP_CONCAT(p2.name, ' / ')
                FROM game_players gp2
                JOIN players p2 ON p2.id = gp2.player_id
                WHERE gp2.game_id = g.id
                ORDER BY gp2.rank_order ASC
            ),
            'game-migration',
            'game-migration:' || g.id || ':' || g.yakuman_winner || ':' || g.yakuman_text,
            CURRENT_TIMESTAMP
        FROM games g
        JOIN players p ON p.name_key = lower(trim(g.yakuman_winner))
        WHERE COALESCE(g.yakuman_winner, '') <> ''
          AND COALESCE(g.yakuman_text, '') <> ''
          AND NOT EXISTS (
              SELECT 1
              FROM yakuman_records yr_existing
              WHERE yr_existing.game_id = g.id
          )
          AND NOT EXISTS (
              SELECT 1
              FROM deleted_yakuman_records dyr
              WHERE dyr.source_key = 'game-migration:' || g.id || ':' || g.yakuman_winner || ':' || g.yakuman_text
          )
        """
    )
    dedupe_yakuman_records(connection)
    connection.commit()
    from competition_schema import migrate
    migrate(connection)


YAKUMAN_OPTIONS = [
    "天和",
    "地和",
    "国士无双",
    "四暗刻",
    "大三元",
    "清老头",
    "九莲宝灯",
    "小四喜",
    "大四喜",
    "字一色",
    "绿一色",
    "四杠子",
    "累计役满",
    "四暗刻单骑",
    "石上三年",
    "大七星",
    "连七对",
    "纯正九莲宝灯",
    "国士无双十三面",
    "人和",
]


def ensure_column(connection, table_name, column_name, column_type):
    columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table_name})")}
    if column_name not in columns:
        try:
            connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")
        except sqlite3.OperationalError:
            # Another worker may have completed this additive migration after
            # our first read. Only suppress the race when the column now exists.
            current = {row["name"] for row in connection.execute(f"PRAGMA table_info({table_name})")}
            if column_name not in current:
                raise


def upsert_player(connection, name, initial_mmr=1500):
    name = str(name or "").strip()
    key = normalize_name(name)
    if not key:
        raise ValueError("Player name is required.")

    row = connection.execute("SELECT * FROM players WHERE name_key = ?", (key,)).fetchone()
    if row:
        # Importing a score or registering a spelling variant must not rename a
        # player. Explicit administrator rename is the only name-changing path.
        return row

    connection.execute(
        "INSERT INTO players (name, name_key, current_mmr, history_highest_pt, history_highest_mmr) VALUES (?, ?, ?, 0, ?)",
        (name, key, float(initial_mmr), float(initial_mmr)),
    )
    connection.commit()
    return connection.execute("SELECT * FROM players WHERE name_key = ?", (key,)).fetchone()


def dedupe_yakuman_records(connection):
    groups = connection.execute(
        """
        SELECT game_id, winner_id, yakuman_name, COUNT(*) AS count
        FROM yakuman_records
        WHERE game_id IS NOT NULL
        GROUP BY game_id, winner_id, yakuman_name
        HAVING COUNT(*) > 1
        """
    ).fetchall()
    for group in groups:
        rows = connection.execute(
            """
            SELECT id, source, updated_at, created_at
            FROM yakuman_records
            WHERE game_id = ? AND winner_id = ? AND yakuman_name = ?
            ORDER BY
                CASE WHEN source = 'game-migration' THEN 1 ELSE 0 END ASC,
                COALESCE(NULLIF(updated_at, ''), created_at) DESC,
                id DESC
            """,
            (group["game_id"], group["winner_id"], group["yakuman_name"]),
        ).fetchall()
        keep_id = rows[0]["id"]
        for row in rows[1:]:
            connection.execute("DELETE FROM yakuman_records WHERE id = ?", (row["id"],))
        refresh_game_yakuman_fields(connection, group["game_id"])


def pt_delta(final_score, placement):
    oka_uma = [30, 10, -10, -30][placement - 1]
    return (int(final_score) - 25000) / 1000 + oka_uma


def placements_from_scores(scores):
    numeric_scores = [int(score) for score in scores]
    return [1 + sum(1 for other in numeric_scores if other > score) for score in numeric_scores]


def get_config(connection, key, default=""):
    row = connection.execute("SELECT value FROM app_config WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_config(connection, key, value):
    connection.execute(
        """
        INSERT INTO app_config (key, value, updated_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value,
            updated_at = CURRENT_TIMESTAMP
        """,
        (key, value),
    )
    connection.commit()


def discord_score_paused(connection):
    # A missing setting keeps the existing Discord command enabled. An
    # unexpected stored value fails closed until an administrator resets it.
    return get_config(connection, DISCORD_SCORE_PAUSED_KEY, "0") != "0"


def set_discord_score_paused(connection, paused):
    if type(paused) is not bool:
        raise ValueError("paused must be a boolean")
    set_config(connection, DISCORD_SCORE_PAUSED_KEY, "1" if paused else "0")
    return paused


def set_current_quarter(connection, quarter):
    quarter = str(quarter or "").strip()
    if not quarter:
        raise ValueError("Quarter is required.")
    set_config(connection, "current_quarter", quarter)
    return quarter


def latest_quarter(connection):
    configured = get_config(connection, "current_quarter", "")
    if configured:
        return configured
    row = connection.execute(
        """
        SELECT quarter
        FROM games
        WHERE COALESCE(quarter, '') <> ''
        ORDER BY id DESC
        LIMIT 1
        """
    ).fetchone()
    return row["quarter"] if row else ""


def quarters(connection):
    values = []
    configured = get_config(connection, "current_quarter", "")
    if configured:
        values.append(configured)
    rows = connection.execute(
        """
        SELECT DISTINCT quarter
        FROM games
        WHERE COALESCE(quarter, '') <> ''
        ORDER BY id DESC
        """
    ).fetchall()
    for row in rows:
        quarter = row["quarter"]
        if quarter and quarter not in values:
            values.append(quarter)
    return values


def import_game(connection, names, scores, played_at, source="sheet", sheet_row=None, created_by="sync", yakuman=None, quarter="", seat_winds=None, source_seat_order="unknown", nfc_match_id=None, started_at=None, ended_at=None, duration_seconds=None, authoritative_played_at=None, played_at_source=None, summary_time=None):
    if nfc_match_id:
        existing = connection.execute("SELECT id FROM games WHERE nfc_match_id = ?", (nfc_match_id,)).fetchone()
        if existing:
            return existing["id"]
    if sheet_row is not None:
        existing = connection.execute("SELECT id FROM games WHERE sheet_row = ?", (sheet_row,)).fetchone()
        if existing:
            return existing["id"]

    if len(names) != 4 or len(scores) != 4:
        raise ValueError("A game must have exactly four players and four scores.")
    if len({normalize_name(name) for name in names}) != 4:
        raise ValueError(f"Duplicate players in one game: {', '.join(names)}")

    if source_seat_order not in {"unknown", "ESWN", "EWSN"}:
        raise ValueError("Invalid source seat order.")
    if seat_winds is not None and (len(seat_winds) != 4 or set(seat_winds) != {"east", "south", "west", "north"}):
        raise ValueError("Four explicit physical winds are required.")

    from competition_time import event_time
    actual_time = authoritative_played_at or started_at
    if actual_time is None and source not in {"nfc", "photo", "manual"}:
        actual_time = played_at
    try:
        actual_time = event_time(actual_time) if actual_time else None
    except ValueError:
        actual_time = None  # Preserve legacy imports; unknown event time is not competition eligible.

    pre_status = player_status_map(connection, names) if source != "sheet" else None
    players = [upsert_player(connection, name) for name in names]
    mmrs = [player["current_mmr"] for player in players]
    result = compute_one_table(scores, mmrs)
    placements = placements_from_scores(scores)

    yakuman = yakuman or {}
    cursor = connection.execute(
        """
        INSERT INTO games (
            played_at, quarter, source, sheet_row, sync_status, created_by,
            yakuman_winner, yakuman_deal_in, yakuman_text
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            played_at,
            quarter or "",
            source,
            sheet_row,
            "synced" if source == "sheet" else "pending",
            created_by,
            yakuman.get("winner", ""),
            yakuman.get("deal_in", ""),
            yakuman.get("text", ""),
        ),
    )
    game_id = cursor.lastrowid
    connection.execute("UPDATE games SET nfc_match_id=?, started_at=?, ended_at=?, duration_seconds=? WHERE id=?",
                       (nfc_match_id, started_at, ended_at, duration_seconds, game_id))
    connection.execute("UPDATE games SET source_seat_order = ?, authoritative_played_at=?, played_at_source=? WHERE id = ?",
                       (source_seat_order, actual_time, played_at_source or ("table_started_at" if started_at else "declared_game_time" if actual_time else None), game_id))

    for index, player in enumerate(players):
        placement = placements[index]
        delta = round(result["deltas"][index], 4)
        mmr_after = round(result["new_mmr"][index], 2)
        point_delta = round(pt_delta(scores[index], placement), 1)
        total_pt = float(player["total_pt"]) + point_delta
        history_highest_pt = max(float(player["history_highest_pt"]), total_pt)
        history_highest_mmr = max(float(player["history_highest_mmr"] or 1500), mmr_after, 1500)

        connection.execute(
            """
            INSERT INTO game_players (
                game_id, player_id, rank_order, final_score, placement,
                mmr_before, mmr_delta, mmr_after, pt_delta
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                game_id,
                player["id"],
                index,
                int(scores[index]),
                placement,
                float(player["current_mmr"]),
                delta,
                mmr_after,
                point_delta,
            ),
        )
        if seat_winds is not None:
            source_winds = {"ESWN": ["east", "south", "west", "north"], "EWSN": ["east", "west", "south", "north"]}.get(source_seat_order)
            source_position = source_winds.index(seat_winds[index]) if source_winds else None
            connection.execute("UPDATE game_players SET seat_wind = ?, source_position = ? WHERE game_id = ? AND player_id = ?",
                               (seat_winds[index], source_position, game_id, player["id"]))
        connection.execute(
            """
            UPDATE players
            SET current_mmr = ?,
                total_pt = ?,
                history_highest_pt = ?,
                history_highest_mmr = ?,
                games_played = games_played + 1,
                wins = wins + ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (mmr_after, total_pt, history_highest_pt, history_highest_mmr, 1 if placement == 1 else 0, player["id"]),
        )

    if pre_status is not None:
        import json
        from game_summary import build_game_summary
        payload = build_game_summary(names, scores, summary_time or played_at, pre_status,
            player_status_map(connection, names), yakuman.get("winner", ""),
            yakuman.get("deal_in", ""), yakuman.get("text", ""))
        connection.execute("INSERT INTO game_score_summaries(game_id, payload_json) VALUES (?, ?)",
                           (game_id, json.dumps(payload, ensure_ascii=False)))
    connection.commit()
    yakuman_names = yakuman.get("names") if isinstance(yakuman.get("names"), list) else []
    if not yakuman_names and yakuman.get("text"):
        yakuman_names = [name.strip() for name in str(yakuman.get("text", "")).replace("，", ",").split(",") if name.strip()]
    for yakuman_name in yakuman_names:
        record_yakuman(
            connection,
            played_at=played_at,
            winner=yakuman.get("winner", ""),
            yakuman_name=yakuman_name,
            note=yakuman.get("note", ""),
            players=names,
            game_id=game_id,
            source=source,
            source_key=f"{source}:game:{game_id}:{yakuman.get('winner', '')}:{yakuman_name}",
            deal_in=yakuman.get("deal_in", ""),
            photo_path=yakuman.get("photo_path", ""),
            photo_caption=yakuman.get("photo_caption", ""),
        )
    return game_id


def record_yakuman(connection, played_at, winner, yakuman_name, note="", players=None, game_id=None, source="web", source_key=None, deal_in="", photo_path="", photo_caption=""):
    winner = str(winner or "").strip()
    yakuman_name = str(yakuman_name or "").strip()
    if not winner or not yakuman_name:
        return None
    winner_row = upsert_player(connection, winner)
    deal_in = str(deal_in or "").strip()
    photo_path = str(photo_path or "").strip()
    photo_caption = str(photo_caption or "").strip()
    players = [str(player).strip() for player in (players or []) if str(player).strip()]
    if game_id is None:
        matched = find_game_for_yakuman(connection, played_at, winner, players)
        if matched:
            game_id = matched["id"]
            players = matched["players"]
    players_text = " / ".join([str(player).strip() for player in (players or []) if str(player).strip()])
    if source_key:
        deleted = connection.execute("SELECT source_key FROM deleted_yakuman_records WHERE source_key = ?", (source_key,)).fetchone()
        if deleted:
            return None
        existing = connection.execute("SELECT id FROM yakuman_records WHERE source_key = ?", (source_key,)).fetchone()
        if existing:
            return existing["id"]
    if game_id:
        existing = connection.execute(
            """
            SELECT yr.id
            FROM yakuman_records yr
            JOIN players p ON p.id = yr.winner_id
            WHERE yr.game_id = ?
              AND p.name_key = ?
              AND yr.yakuman_name = ?
            LIMIT 1
            """,
            (game_id, normalize_name(winner), yakuman_name),
        ).fetchone()
        if existing:
            update_yakuman(
                connection,
                existing["id"],
                played_at=played_at,
                winner=winner,
                yakuman_name=yakuman_name,
                deal_in=deal_in,
                note=note or "",
                game_id=game_id,
            )
            return existing["id"]
    cursor = connection.execute(
        """
        INSERT INTO yakuman_records (game_id, played_at, winner_id, yakuman_name, deal_in, note, players_text, photo_path, photo_caption, source, source_key, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """,
        (game_id, played_at, winner_row["id"], yakuman_name, deal_in, note or "", players_text, photo_path, photo_caption, source, source_key),
    )
    if game_id:
        append_game_yakuman(connection, game_id, winner, yakuman_name, deal_in=deal_in)
    connection.commit()
    return cursor.lastrowid


def reset_yakuman_records(connection, clear_tombstones=True):
    connection.execute("DELETE FROM yakuman_records")
    if clear_tombstones:
        connection.execute("DELETE FROM deleted_yakuman_records")
    connection.execute(
        """
        UPDATE games
        SET yakuman_winner = '',
            yakuman_deal_in = '',
            yakuman_text = ''
        """
    )
    connection.commit()


def date_key(value):
    text = str(value or "").strip()
    return text[:10] if len(text) >= 10 else text


def append_game_yakuman(connection, game_id, winner, yakuman_name, deal_in=""):
    row = connection.execute("SELECT yakuman_winner, yakuman_deal_in, yakuman_text FROM games WHERE id = ?", (game_id,)).fetchone()
    if not row:
        return
    names = [part.strip() for part in str(row["yakuman_text"] or "").replace("，", ",").split(",") if part.strip()]
    if yakuman_name not in names:
        names.append(yakuman_name)
    deal_ins = [part.strip() for part in str(row["yakuman_deal_in"] or "").replace("，", ",").split(",") if part.strip()]
    if deal_in and deal_in not in deal_ins:
        deal_ins.append(deal_in)
    connection.execute(
        """
        UPDATE games
        SET yakuman_winner = COALESCE(NULLIF(yakuman_winner, ''), ?),
            yakuman_deal_in = ?,
            yakuman_text = ?
        WHERE id = ?
        """,
        (winner, ", ".join(deal_ins), ", ".join(names), game_id),
    )


def find_game_for_yakuman(connection, played_at, winner, players=None):
    target_date = date_key(played_at)
    winner_key = normalize_name(winner)
    player_keys = {normalize_name(player) for player in (players or []) if normalize_name(player)}
    if not target_date or not winner_key:
        return None

    rows = connection.execute(
        """
        SELECT g.id, g.played_at
        FROM games g
        JOIN game_players gp ON gp.game_id = g.id
        JOIN players p ON p.id = gp.player_id
        WHERE p.name_key = ? AND substr(g.played_at, 1, 10) = ?
        ORDER BY g.id DESC
        """,
        (winner_key, target_date),
    ).fetchall()
    best = None
    best_score = -1
    for row in rows:
        game_players = [
            player["name"]
            for player in connection.execute(
                """
                SELECT p.name
                FROM game_players gp
                JOIN players p ON p.id = gp.player_id
                WHERE gp.game_id = ?
                ORDER BY gp.rank_order ASC
                """,
                (row["id"],),
            )
        ]
        game_keys = {normalize_name(player) for player in game_players}
        overlap = len(player_keys & game_keys) if player_keys else 1
        if player_keys and winner_key not in game_keys:
            continue
        if player_keys and overlap < min(3, len(player_keys)):
            continue
        if overlap > best_score:
            best = {"id": row["id"], "played_at": row["played_at"], "players": game_players}
            best_score = overlap
    return best


def ranking(connection, kind="quarter_pt", limit=25, quarter=None):
    quarter = quarter or latest_quarter(connection)
    if kind in {"quarter_pt", "quarter_mmr", "quarter_games"} and quarter:
        return quarter_ranking(connection, kind=kind, quarter=quarter, limit=limit)

    column_by_kind = {
        "quarter_pt": "total_pt",
        "quarter_mmr": "current_mmr",
        "total_mmr": "current_mmr",
        "total_pt": "total_pt",
        "history_highest_mmr": "history_highest_mmr",
        "quarter_games": "games_played",
        "total_games": "games_played",
    }
    label_by_kind = {
        "quarter_pt": "Quarter PT",
        "quarter_mmr": "Quarter MMR",
        "total_mmr": "Total MMR",
        "total_pt": "Total PT",
        "history_highest_mmr": "History Highest MMR",
        "quarter_games": "Quarter Games",
        "total_games": "Total Games",
    }
    column = column_by_kind.get(kind, "total_pt")
    rows = connection.execute(
        f"""
        SELECT name, {column} AS value, wins, games_played AS games
        FROM players
        WHERE games_played > 0
        ORDER BY {column} DESC, name COLLATE NOCASE ASC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [
        {
            "name": row["name"],
            "value": format_number(row["value"]),
            "label": label_by_kind.get(kind, "Quarter PT"),
            "wins": row["wins"],
            "games": row["games"],
            "rank": index,
        }
        for index, row in enumerate(rows, 1)
    ]


def quarter_ranking(connection, kind="quarter_pt", quarter="", limit=25):
    if kind == "quarter_mmr":
        rows = connection.execute(
            """
            WITH latest AS (
                SELECT gp.player_id, MAX(g.id) AS latest_game_id
                FROM game_players gp
                JOIN games g ON g.id = gp.game_id
                WHERE g.quarter = ?
                GROUP BY gp.player_id
            ),
            wins AS (
                SELECT gp.player_id, SUM(CASE WHEN gp.placement = 1 THEN 1 ELSE 0 END) AS wins, COUNT(*) AS games
                FROM game_players gp
                JOIN games g ON g.id = gp.game_id
                WHERE g.quarter = ?
                GROUP BY gp.player_id
            )
            SELECT p.name,
                   gp.mmr_after AS value,
                   COALESCE(wins.wins, 0) AS wins, wins.games AS games
            FROM latest
            JOIN game_players gp ON gp.player_id = latest.player_id AND gp.game_id = latest.latest_game_id
            JOIN players p ON p.id = latest.player_id
            LEFT JOIN wins ON wins.player_id = latest.player_id
            ORDER BY value DESC, p.name COLLATE NOCASE ASC
            LIMIT ?
            """,
            (quarter, quarter, limit),
        ).fetchall()
        return [
            {
                "name": row["name"],
                "value": format_number(row["value"]),
                "label": "Quarter MMR",
                "wins": row["wins"],
                "games": row["games"],
                "rank": index,
            }
            for index, row in enumerate(rows, 1)
        ]
    else:
        metric_expr = "COUNT(*)" if kind == "quarter_games" else "SUM(gp.pt_delta)"
        label = "Quarter Games" if kind == "quarter_games" else "Quarter PT"

    rows = connection.execute(
        f"""
        SELECT p.name,
               {metric_expr} AS value,
               SUM(CASE WHEN gp.placement = 1 THEN 1 ELSE 0 END) AS wins, COUNT(*) AS games
        FROM game_players gp
        JOIN players p ON p.id = gp.player_id
        JOIN games g ON g.id = gp.game_id
        WHERE g.quarter = ?
        GROUP BY p.id
        HAVING COUNT(*) > 0
        ORDER BY value DESC, p.name COLLATE NOCASE ASC
        LIMIT ?
        """,
        (quarter, limit),
    ).fetchall()
    return [
        {
            "name": row["name"],
            "value": format_number(row["value"]),
            "label": label,
            "wins": row["wins"],
            "games": row["games"],
            "rank": index,
        }
        for index, row in enumerate(rows, 1)
    ]


def player_stats(connection, limit=500):
    rows = connection.execute(
        """
        SELECT
            id,
            name,
            current_mmr,
            total_pt,
            history_highest_pt,
            history_highest_mmr,
            games_played,
            wins
        FROM players
        WHERE games_played > 0
        ORDER BY total_pt DESC, name COLLATE NOCASE ASC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    stats = []
    for row in rows:
        win_rate = (row["wins"] / row["games_played"]) if row["games_played"] else 0
        stats.append(
            {
                "name": row["name"],
                "current_mmr": round(float(row["current_mmr"]), 2),
                "total_pt": round(float(row["total_pt"]), 1),
                "history_highest_pt": round(float(row["history_highest_pt"]), 1),
                "history_highest_mmr": round(float(row["history_highest_mmr"] or 1500), 2),
                "games_played": row["games_played"],
                "wins": row["wins"],
                "win_rate": round(win_rate, 4),
                "avg_place": 0,
                "top2_rate": 0,
            }
        )

    by_name = {item["name"]: item for item in stats}
    for row in connection.execute(
        """
        SELECT p.name,
               AVG(gp.placement) AS avg_place,
               SUM(CASE WHEN gp.placement <= 2 THEN 1 ELSE 0 END) AS top2,
               COUNT(*) AS games
        FROM game_players gp
        JOIN players p ON p.id = gp.player_id
        GROUP BY p.id
        """
    ):
        item = by_name.get(row["name"])
        if not item:
            continue
        item["avg_place"] = round(float(row["avg_place"] or 0), 3)
        item["top2_rate"] = round((row["top2"] or 0) / row["games"], 4) if row["games"] else 0

    for metric, rank_key in [
        ("current_mmr", "mmr_rank"),
        ("total_pt", "pt_rank"),
        ("history_highest_mmr", "history_highest_mmr_rank"),
    ]:
        ordered = sorted(stats, key=lambda item: item[metric], reverse=True)
        for rank, item in enumerate(ordered, 1):
            item[rank_key] = rank

    return stats


def player_names(connection):
    return [row["name"] for row in connection.execute("SELECT name FROM players ORDER BY name COLLATE NOCASE")]


def split_player_text(value):
    return [name.strip() for name in str(value or "").split("/") if name.strip()]


def replace_name_list_text(value, old_name, new_name):
    old_key = normalize_name(old_name)
    names = split_player_text(value)
    changed = False
    output = []
    for name in names:
        if normalize_name(name) == old_key:
            output.append(new_name)
            changed = True
        else:
            output.append(name)
    return " / ".join(output), changed


def replace_delimited_name_text(value, old_name, new_name):
    """Replace exact name tokens while preserving comma/slash list formatting."""
    old_key = normalize_name(old_name)
    pieces = re.split(r"([/,，])", str(value or ""))
    changed = False
    for index in range(0, len(pieces), 2):
        token = pieces[index]
        match = re.fullmatch(r"(\s*)(.*?)(\s*)", token, flags=re.DOTALL)
        if match and normalize_name(match.group(2)) == old_key:
            pieces[index] = match.group(1) + new_name + match.group(3)
            changed = True
    return "".join(pieces), changed


def update_name_references(connection, old_name, new_name):
    for table_name, column_name in [("games", "yakuman_winner"), ("games", "yakuman_deal_in"), ("yakuman_records", "deal_in")]:
        rows = connection.execute(f"SELECT id, {column_name} AS value FROM {table_name}").fetchall()
        for row in rows:
            updated, changed = replace_delimited_name_text(row["value"], old_name, new_name)
            if changed:
                connection.execute(
                    f"UPDATE {table_name} SET {column_name} = ? WHERE id = ?",
                    (updated, row["id"]),
                )

    rows = connection.execute("SELECT id, players_text FROM yakuman_records").fetchall()
    for row in rows:
        updated, changed = replace_name_list_text(row["players_text"], old_name, new_name)
        if changed:
            connection.execute("UPDATE yakuman_records SET players_text = ? WHERE id = ?", (updated, row["id"]))


def rename_player(connection, old_name, new_name, *, commit=True):
    old_key = normalize_name(old_name)
    new_name = str(new_name or "").strip()
    new_key = normalize_name(new_name)
    if not old_key or not new_key:
        raise ValueError("Both old and new player names are required.")
    source = connection.execute("SELECT * FROM players WHERE name_key = ?", (old_key,)).fetchone()
    if not source:
        raise ValueError("Source player was not found in SQL.")
    import registered_names
    existing = next((row for row in connection.execute("SELECT * FROM players")
                     if registered_names.normalize_name(row["name"]) == registered_names.normalize_name(new_name)
                     and row["id"] != source["id"]), None)
    if existing:
        raise ValueError("Target name already exists. Use merge duplicate users instead.")

    connection.execute(
        "UPDATE players SET name = ?, name_key = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (new_name, new_key, source["id"]),
    )
    update_name_references(connection, source["name"], new_name)
    if commit:
        connection.commit()
    return {"old_name": source["name"], "new_name": new_name}


def _merge_player_rows(connection, source, target):
    if not source:
        raise ValueError("Source player was not found in SQL.")
    if not target:
        raise ValueError("Target player was not found in SQL.")
    if int(source["id"]) == int(target["id"]):
        raise ValueError("Source and target are the same player.")

    conflicts = connection.execute(
        """
        SELECT game_id
        FROM game_players
        WHERE player_id IN (?, ?)
        GROUP BY game_id
        HAVING COUNT(DISTINCT player_id) > 1
        ORDER BY game_id
        LIMIT 10
        """,
        (source["id"], target["id"]),
    ).fetchall()
    if conflicts:
        ids = ", ".join(str(row["game_id"]) for row in conflicts)
        raise ValueError(f"Cannot merge because both names appear in the same game(s): {ids}")

    connection.execute("UPDATE game_players SET player_id = ? WHERE player_id = ?", (target["id"], source["id"]))
    connection.execute("UPDATE yakuman_records SET winner_id = ? WHERE winner_id = ?", (target["id"], source["id"]))
    update_name_references(connection, source["name"], target["name"])
    if connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='account_creation_intents'").fetchone():
        # Creation intents are recovery journals, not historical score data. A
        # merged source can no longer be published as a separate player.
        connection.execute("DELETE FROM account_creation_intents WHERE player_id = ?", (source["id"],))
    connection.execute("DELETE FROM players WHERE id = ?", (source["id"],))
    recompute_all_games(connection)
    connection.commit()
    return {"source": source["name"], "target": target["name"],
            "source_player_id": int(source["id"]), "target_player_id": int(target["id"])}


def merge_player_ids(connection, source_player_id, target_player_id):
    try:
        source_id, target_id = int(source_player_id), int(target_player_id)
    except (TypeError, ValueError):
        raise ValueError("Both source and target player IDs are required.") from None
    if source_id <= 0 or target_id <= 0:
        raise ValueError("Both source and target player IDs are required.")
    source = connection.execute("SELECT * FROM players WHERE id = ?", (source_id,)).fetchone()
    target = connection.execute("SELECT * FROM players WHERE id = ?", (target_id,)).fetchone()
    if not source:
        raise ValueError("Source player was not found in SQL.")
    if not target:
        raise ValueError("Target player was not found in SQL.")
    return _merge_player_rows(connection, source, target)


def merge_players(connection, source_name, target_name):
    source_key = normalize_name(source_name)
    target_key = normalize_name(target_name)
    if not source_key or not target_key:
        raise ValueError("Both source and target player names are required.")
    source = connection.execute("SELECT * FROM players WHERE name_key = ?", (source_key,)).fetchone()
    target = connection.execute("SELECT * FROM players WHERE name_key = ?", (target_key,)).fetchone()
    if not source:
        raise ValueError("Source player was not found in SQL.")
    if not target:
        raise ValueError("Target player was not found in SQL.")
    return _merge_player_rows(connection, source, target)


def game_mmr_deltas(connection, game_id):
    return [
        row["mmr_delta"]
        for row in connection.execute(
            "SELECT mmr_delta FROM game_players WHERE game_id = ? ORDER BY rank_order ASC",
            (game_id,),
        )
    ]


def game_mmr_afters(connection, game_id):
    return [
        row["mmr_after"]
        for row in connection.execute(
            "SELECT mmr_after FROM game_players WHERE game_id = ? ORDER BY rank_order ASC",
            (game_id,),
        )
    ]


def recompute_player_aggregates(connection, player_ids):
    for player_id in player_ids:
        rows = connection.execute(
            """
            SELECT gp.pt_delta, gp.placement, gp.mmr_after
            FROM game_players gp
            WHERE gp.player_id = ?
            ORDER BY gp.game_id ASC
            """,
            (player_id,),
        ).fetchall()

        total_pt = 0.0
        highest_pt = 0.0
        highest_mmr = 1500.0
        wins = 0
        current_mmr = 1500.0
        for row in rows:
            total_pt += float(row["pt_delta"] or 0)
            highest_pt = max(highest_pt, total_pt)
            wins += 1 if int(row["placement"]) == 1 else 0
            current_mmr = float(row["mmr_after"] or current_mmr)
            highest_mmr = max(highest_mmr, current_mmr)

        connection.execute(
            """
            UPDATE players
            SET current_mmr = ?,
                total_pt = ?,
                history_highest_pt = ?,
                history_highest_mmr = ?,
                games_played = ?,
                wins = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (round(current_mmr, 2), round(total_pt, 1), round(highest_pt, 1), round(highest_mmr, 2), len(rows), wins, player_id),
        )


def recompute_all_games(connection):
    game_rows = connection.execute("SELECT * FROM games ORDER BY id ASC").fetchall()
    snapshots = []
    for game in game_rows:
        player_rows = connection.execute(
            """
            SELECT p.name, gp.*
            FROM game_players gp
            JOIN players p ON p.id = gp.player_id
            WHERE gp.game_id = ?
            ORDER BY gp.rank_order ASC
            """,
            (game["id"],),
        ).fetchall()
        snapshots.append(
            {
                "game": game,
                "rows": player_rows,
                "names": [row["name"] for row in player_rows],
                "scores": [row["final_score"] for row in player_rows],
            }
        )

    connection.execute("DELETE FROM game_players")
    connection.execute(
        """
        UPDATE players
        SET current_mmr = 1500,
            total_pt = 0,
            history_highest_pt = 0,
            history_highest_mmr = 1500,
            games_played = 0,
            wins = 0,
            updated_at = CURRENT_TIMESTAMP
        """
    )

    for item in snapshots:
        game = item["game"]
        players = [upsert_player(connection, name) for name in item["names"]]
        if len(item["rows"]) != 4:
            # Preserve uncommon imported rows verbatim. Older rebuilds silently
            # dropped them merely because they were not four-player games.
            for player, row in zip(players, item["rows"]):
                connection.execute(
                    """INSERT INTO game_players (
                           game_id,player_id,rank_order,final_score,placement,
                           mmr_before,mmr_delta,mmr_after,pt_delta,seat_wind,source_position
                       ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (game["id"], player["id"], row["rank_order"], row["final_score"], row["placement"],
                     row["mmr_before"], row["mmr_delta"], row["mmr_after"], row["pt_delta"],
                     row["seat_wind"], row["source_position"]),
                )
                total_pt = float(player["total_pt"]) + float(row["pt_delta"] or 0)
                connection.execute("""UPDATE players SET current_mmr=?,total_pt=?,
                    history_highest_pt=MAX(history_highest_pt,?),
                    history_highest_mmr=MAX(history_highest_mmr,?,1500),
                    games_played=games_played+1,wins=wins+?,updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                    (row["mmr_after"], total_pt, total_pt, row["mmr_after"],
                     1 if int(row["placement"]) == 1 else 0, player["id"]))
            continue
        mmrs = [player["current_mmr"] for player in players]
        result = compute_one_table(item["scores"], mmrs)
        placements = placements_from_scores(item["scores"])
        for index, player in enumerate(players):
            placement = placements[index]
            delta = round(result["deltas"][index], 4)
            mmr_after = round(result["new_mmr"][index], 2)
            point_delta = round(pt_delta(item["scores"][index], placement), 1)
            total_pt = float(player["total_pt"]) + point_delta
            highest_pt = max(float(player["history_highest_pt"]), total_pt)
            highest_mmr = max(float(player["history_highest_mmr"] or 1500), mmr_after, 1500)
            connection.execute(
                """
                INSERT INTO game_players (
                    game_id, player_id, rank_order, final_score, placement,
                    mmr_before, mmr_delta, mmr_after, pt_delta, seat_wind, source_position
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (game["id"], player["id"], index, int(item["scores"][index]), placement,
                 float(player["current_mmr"]), delta, mmr_after, point_delta,
                 item["rows"][index]["seat_wind"], item["rows"][index]["source_position"]),
            )
            connection.execute(
                """
                UPDATE players
                SET current_mmr = ?,
                    total_pt = ?,
                    history_highest_pt = ?,
                    history_highest_mmr = ?,
                    games_played = games_played + 1,
                    wins = wins + ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (mmr_after, total_pt, highest_pt, highest_mmr, 1 if placement == 1 else 0, player["id"]),
            )
    connection.commit()


def revert_game(connection, game_id, recompute_following=True):
    # Every caller, including Discord and maintenance scripts, must honor the
    # NFC score ledger and reservation accounting boundary. Lock before the
    # lookup so a projected row cannot change identity before deletion.
    started_here = not connection.in_transaction
    if started_here:
        connection.execute("BEGIN IMMEDIATE")
    try:
        original = connection.execute(
            "SELECT nfc_match_id FROM games WHERE id=?", (game_id,)).fetchone()
        if original and original["nfc_match_id"]:
            raise ValueError("NFC scores cannot be reverted here. Contact an administrator for coordinated score correction.")
        rows = connection.execute(
            """
            SELECT gp.player_id, p.name
            FROM game_players gp
            JOIN players p ON p.id = gp.player_id
            WHERE gp.game_id = ?
            ORDER BY gp.rank_order ASC
            """,
            (game_id,),
        ).fetchall()
        if not rows:
            raise ValueError("Could not find that SQL game record.")

        key = "club:" + str(game_id)
        connection.execute("INSERT OR IGNORE INTO competition_game_tombstones VALUES(?,?,CURRENT_TIMESTAMP)", (key,"game_record_reverted"))
        connection.execute("DELETE FROM yakuman_records WHERE game_id = ?", (game_id,))
        connection.execute("DELETE FROM game_players WHERE game_id = ?", (game_id,))
        connection.execute("DELETE FROM games WHERE id = ?", (game_id,))
        if recompute_following:
            recompute_all_games(connection)
        else:
            recompute_player_aggregates(connection, [row["player_id"] for row in rows])
            connection.commit()
        return [row["name"] for row in rows]
    except BaseException:
        if started_here and connection.in_transaction:
            connection.rollback()
        raise


def recent_revert_candidates(connection, limit=12):
    games = connection.execute(
        """
        SELECT id, played_at, sheet_row, created_by, quarter
        FROM games
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    result = []
    for game in games:
        players = connection.execute(
            """
            SELECT p.name, gp.final_score, gp.placement, gp.mmr_delta, gp.pt_delta
            FROM game_players gp
            JOIN players p ON p.id = gp.player_id
            WHERE gp.game_id = ?
            ORDER BY gp.rank_order ASC
            """,
            (game["id"],),
        ).fetchall()
        result.append(
            {
                "id": f"sql-{game['id']}",
                "game_id": game["id"],
                "date": game["played_at"],
                "sheet_row": game["sheet_row"],
                "created_by": game["created_by"] or "",
                "quarter": game["quarter"] or "",
                "players": [
                    {
                        "name": row["name"],
                        "score": row["final_score"],
                        "placement": row["placement"],
                        "mmr_delta": row["mmr_delta"],
                        "pt_delta": row["pt_delta"],
                    }
                    for row in players
                ],
            }
        )
    return result


def admin_game_rows(connection, page=1, per_page=10, played_at="", player_names=None):
    page = max(1, int(page or 1))
    per_page = max(1, min(50, int(per_page or 10)))
    offset = (page - 1) * per_page
    target_date = str(played_at or "").strip()[:10]
    player_keys = []
    for name in player_names or []:
        key = normalize_name(name)
        if key and key not in player_keys:
            player_keys.append(key)
    filters = []
    params = []
    if target_date:
        try:
            from competition_time import local_day_utc_bounds
            start_at, end_at = local_day_utc_bounds(target_date, zone="America/Los_Angeles")
            # NFC game times are stored in UTC. Keep the date-prefix clause for
            # older rows whose timestamps were stored as local, timezone-free text.
            filters.append("((g.played_at >= ? AND g.played_at < ?) OR substr(g.played_at, 1, 10) = ?)")
            params.extend((start_at, end_at, target_date))
        except ValueError:
            filters.append("substr(g.played_at, 1, 10) = ?")
            params.append(target_date)
    where = f"WHERE {' AND '.join(filters)}" if filters else ""
    player_join = ""
    player_having = ""
    if player_keys:
        placeholders = ",".join("?" for _ in player_keys)
        player_join = """
        JOIN game_players gp_filter ON gp_filter.game_id = g.id
        JOIN players p_filter ON p_filter.id = gp_filter.player_id
        """
        where = f"{where} {'AND' if where else 'WHERE'} p_filter.name_key IN ({placeholders})"
        params.extend(player_keys)
        player_having = "HAVING COUNT(DISTINCT p_filter.name_key) = ?"

    total_row = connection.execute(
        f"""
        SELECT COUNT(*) AS count
        FROM (
            SELECT g.id
            FROM games g
            {player_join}
            {where}
            GROUP BY g.id
            {player_having}
        ) filtered_games
        """,
        (*params, len(player_keys)) if player_keys else params,
    ).fetchone()
    total = total_row["count"] if total_row else 0
    games = connection.execute(
        f"""
        SELECT id, played_at, sheet_row, created_by, quarter, yakuman_winner, yakuman_deal_in, yakuman_text, nfc_match_id
        FROM (
            SELECT g.*
            FROM games g
            {player_join}
            {where}
            GROUP BY g.id
            {player_having}
        )
        ORDER BY id DESC
        LIMIT ? OFFSET ?
        """,
        (*params, len(player_keys), per_page, offset) if player_keys else (*params, per_page, offset),
    ).fetchall()
    rows = []
    for game in games:
        players = connection.execute(
            """
            SELECT p.name, gp.final_score, gp.placement, gp.mmr_delta, gp.pt_delta
            FROM game_players gp
            JOIN players p ON p.id = gp.player_id
            WHERE gp.game_id = ?
            ORDER BY gp.rank_order ASC
            """,
            (game["id"],),
        ).fetchall()
        yakuman = connection.execute(
            """
            SELECT yr.id, p.name AS winner, yr.yakuman_name, yr.deal_in
            FROM yakuman_records yr
            JOIN players p ON p.id = yr.winner_id
            WHERE yr.game_id = ?
            ORDER BY yr.id ASC
            """,
            (game["id"],),
        ).fetchall()
        rows.append(
            {
                "id": f"sql-{game['id']}",
                "game_id": game["id"],
                "date": game["played_at"],
                "sheet_row": game["sheet_row"],
                "created_by": game["created_by"] or "",
                "quarter": game["quarter"] or "",
                "can_revert": not bool(game["nfc_match_id"]),
                "yakuman_winner": game["yakuman_winner"] or "",
                "yakuman_deal_in": game["yakuman_deal_in"] or "",
                "yakuman_text": game["yakuman_text"] or "",
                "players": [
                    {
                        "name": row["name"],
                        "score": row["final_score"],
                        "placement": row["placement"],
                        "mmr_delta": row["mmr_delta"],
                        "pt_delta": row["pt_delta"],
                    }
                    for row in players
                ],
                "yakuman": [
                    {
                        "id": row["id"],
                        "winner": row["winner"],
                        "yakuman": row["yakuman_name"],
                        "deal_in": row["deal_in"] or "",
                    }
                    for row in yakuman
                ],
            }
        )
    return {"rows": rows, "page": page, "per_page": per_page, "total": total, "pages": max(1, (total + per_page - 1) // per_page)}


def player_status_map(connection, player_names):
    stats = player_stats(connection)
    by_key = {normalize_name(row["name"]): row for row in stats}
    result = {}
    for name in player_names:
        item = by_key.get(normalize_name(name))
        if not item:
            result[name] = {"mmr": 1500, "mmr_rank": "Unranked", "pt": 0, "pt_rank": "Unranked"}
            continue
        player = connection.execute("SELECT id FROM players WHERE name_key = ?", (normalize_name(item["name"]),)).fetchone()
        quarter_pt = current_quarter_pt(connection, player["id"]) if player else 0
        result[name] = {
            "mmr": item["current_mmr"],
            "mmr_rank": item["mmr_rank"],
            "pt": quarter_pt,
            "pt_rank": rank_in_metric(connection, player["id"], "quarter_pt") if player else item["pt_rank"],
        }
    return result


def recent_yakuman(connection, limit=12):
    rows = connection.execute(
        """
        SELECT yr.id, yr.game_id, yr.played_at, p.name AS winner, yr.yakuman_name, yr.deal_in, yr.note, yr.players_text,
               yr.photo_path, yr.photo_caption, yr.source, yr.source_key, yr.created_at, yr.updated_at
        FROM yakuman_records yr
        JOIN players p ON p.id = yr.winner_id
        ORDER BY COALESCE(NULLIF(yr.updated_at, ''), yr.created_at, yr.played_at) DESC, yr.id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    records = []
    for row in rows:
        records.append(
            {
                "id": row["id"],
                "game_id": row["game_id"],
                "date": row["played_at"],
                "winner": row["winner"] or "",
                "deal_in": row["deal_in"] or "",
                "yakuman": row["yakuman_name"] or "",
                "note": row["note"] or "",
                "players": [name.strip() for name in str(row["players_text"] or "").split("/") if name.strip()],
                "photo_url": row["photo_path"] or "",
                "photo_caption": row["photo_caption"] or "",
                "source": row["source"] or "",
                "source_key": row["source_key"] or "",
                "created_at": row["created_at"] or "",
                "updated_at": row["updated_at"] or "",
            }
        )
    return records


def refresh_game_yakuman_fields(connection, game_id):
    rows = connection.execute(
        """
        SELECT p.name AS winner, yr.yakuman_name, yr.deal_in
        FROM yakuman_records yr
        JOIN players p ON p.id = yr.winner_id
        WHERE yr.game_id = ?
        ORDER BY yr.id ASC
        """,
        (game_id,),
    ).fetchall()
    winners = []
    yakuman_names = []
    deal_ins = []
    for row in rows:
        if row["winner"] and row["winner"] not in winners:
            winners.append(row["winner"])
        if row["yakuman_name"] and row["yakuman_name"] not in yakuman_names:
            yakuman_names.append(row["yakuman_name"])
        if row["deal_in"] and row["deal_in"] not in deal_ins:
            deal_ins.append(row["deal_in"])
    connection.execute(
        """
        UPDATE games
        SET yakuman_winner = ?,
            yakuman_deal_in = ?,
            yakuman_text = ?
        WHERE id = ?
        """,
        (", ".join(winners), ", ".join(deal_ins), ", ".join(yakuman_names), game_id),
    )


def delete_yakuman(connection, yakuman_id):
    row = connection.execute(
        """
        SELECT yr.id, yr.game_id, yr.played_at, yr.yakuman_name, yr.deal_in, yr.note,
               yr.players_text, yr.photo_path, yr.photo_caption, yr.source, yr.source_key, p.name AS winner
        FROM yakuman_records yr
        JOIN players p ON p.id = yr.winner_id
        WHERE yr.id = ?
        """,
        (yakuman_id,),
    ).fetchone()
    if not row:
        raise ValueError("Could not find that yakuman record.")
    if row["source_key"]:
        connection.execute(
            "INSERT OR IGNORE INTO deleted_yakuman_records (source_key) VALUES (?)",
            (row["source_key"],),
        )
    connection.execute("DELETE FROM yakuman_records WHERE id = ?", (yakuman_id,))
    if row["game_id"]:
        refresh_game_yakuman_fields(connection, row["game_id"])
    connection.commit()
    return {
        "id": row["id"],
        "game_id": row["game_id"],
        "played_at": row["played_at"],
        "winner": row["winner"],
        "yakuman": row["yakuman_name"],
        "deal_in": row["deal_in"] or "",
        "note": row["note"] or "",
        "players_text": row["players_text"] or "",
        "photo_path": row["photo_path"] or "",
        "photo_caption": row["photo_caption"] or "",
        "source": row["source"] or "",
        "source_key": row["source_key"] or "",
    }


def update_yakuman(connection, yakuman_id, played_at="", winner="", yakuman_name="", deal_in="", note="", game_id=None):
    row = connection.execute(
        """
        SELECT yr.id, yr.game_id, yr.played_at, yr.winner_id, p.name AS winner, yr.yakuman_name,
               yr.deal_in, yr.note, yr.players_text, yr.photo_path, yr.photo_caption, yr.source, yr.source_key
        FROM yakuman_records yr
        JOIN players p ON p.id = yr.winner_id
        WHERE yr.id = ?
        """,
        (yakuman_id,),
    ).fetchone()
    if not row:
        raise ValueError("Could not find that yakuman record.")

    old = {
        "id": row["id"],
        "game_id": row["game_id"],
        "played_at": row["played_at"],
        "winner": row["winner"],
        "yakuman": row["yakuman_name"],
        "deal_in": row["deal_in"] or "",
        "note": row["note"] or "",
        "players_text": row["players_text"] or "",
        "photo_path": row["photo_path"] or "",
        "photo_caption": row["photo_caption"] or "",
        "source": row["source"] or "",
        "source_key": row["source_key"] or "",
    }

    next_played_at = str(played_at or row["played_at"]).strip()
    next_winner = str(winner or row["winner"]).strip()
    next_yakuman = str(yakuman_name or row["yakuman_name"]).strip()
    next_deal_in = str(deal_in if deal_in is not None else row["deal_in"] or "").strip()
    next_note = str(note if note is not None else row["note"] or "").strip()
    if not next_played_at or not next_winner or not next_yakuman:
        raise ValueError("Date, winner, and yakuman are required.")

    if game_id in ("", 0, "0"):
        next_game_id = None
    elif game_id is None:
        next_game_id = row["game_id"]
    else:
        next_game_id = int(game_id)

    players_text = row["players_text"] or ""
    if next_game_id:
        game = connection.execute("SELECT id, played_at FROM games WHERE id = ?", (next_game_id,)).fetchone()
        if not game:
            raise ValueError("Selected game was not found.")
        if not played_at:
            next_played_at = game["played_at"]
        players = [
            item["name"]
            for item in connection.execute(
                """
                SELECT p.name
                FROM game_players gp
                JOIN players p ON p.id = gp.player_id
                WHERE gp.game_id = ?
                ORDER BY gp.rank_order ASC
                """,
                (next_game_id,),
            )
        ]
        players_text = " / ".join(players)

    winner_row = upsert_player(connection, next_winner)
    connection.execute(
        """
        UPDATE yakuman_records
        SET game_id = ?,
            played_at = ?,
            winner_id = ?,
            yakuman_name = ?,
            deal_in = ?,
            note = ?,
            players_text = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (next_game_id, next_played_at, winner_row["id"], next_yakuman, next_deal_in, next_note, players_text, yakuman_id),
    )
    affected_game_ids = {row["game_id"], next_game_id}
    for affected_game_id in affected_game_ids:
        if affected_game_id:
            refresh_game_yakuman_fields(connection, affected_game_id)
    connection.commit()
    return {
        "old": old,
        "new": {
            "id": yakuman_id,
            "game_id": next_game_id,
            "played_at": next_played_at,
            "winner": next_winner,
            "yakuman": next_yakuman,
            "deal_in": next_deal_in,
            "note": next_note,
            "players_text": players_text,
            "photo_path": old["photo_path"],
            "photo_caption": old["photo_caption"],
            "source": old["source"],
            "source_key": old["source_key"],
        },
    }


def restore_yakuman(connection, deleted):
    played_at = str(deleted.get("played_at") or "").strip()
    winner = str(deleted.get("winner") or "").strip()
    yakuman_name = str(deleted.get("yakuman") or deleted.get("yakuman_name") or "").strip()
    if not played_at or not winner or not yakuman_name:
        raise ValueError("Deleted yakuman payload is missing date, winner, or yakuman.")
    source_key = str(deleted.get("source_key") or "").strip()
    if source_key:
        connection.execute("DELETE FROM deleted_yakuman_records WHERE source_key = ?", (source_key,))
    players_text = str(deleted.get("players_text") or "").strip()
    players = [part.strip() for part in players_text.replace("，", ",").replace("/", ",").split(",") if part.strip()]
    game_id = deleted.get("game_id")
    record_id = record_yakuman(
        connection,
        played_at=played_at,
        winner=winner,
        yakuman_name=yakuman_name,
        note=deleted.get("note", ""),
        players=players,
        game_id=game_id,
        source=deleted.get("source", "restored"),
        source_key=source_key or None,
        deal_in=deleted.get("deal_in", ""),
        photo_path=deleted.get("photo_path", ""),
        photo_caption=deleted.get("photo_caption", ""),
    )
    return record_id


def delete_yakuman_matching(connection, played_at, winner, yakuman_name):
    target_date = str(played_at or "").strip()
    target_winner = normalize_name(winner)
    target_yakuman = str(yakuman_name or "").strip()
    if not target_date or not target_winner or not target_yakuman:
        raise ValueError("Date, winner, and yakuman are required for matching delete.")
    rows = connection.execute(
        """
        SELECT yr.id
        FROM yakuman_records yr
        JOIN players p ON p.id = yr.winner_id
        WHERE yr.played_at = ?
          AND p.name_key = ?
          AND yr.yakuman_name = ?
        ORDER BY yr.id ASC
        """,
        (target_date, target_winner, target_yakuman),
    ).fetchall()
    deleted = []
    for row in rows:
        deleted.append(delete_yakuman(connection, row["id"]))
    return deleted


def update_yakuman_photo(connection, yakuman_id, photo_path="", photo_caption=""):
    row = connection.execute("SELECT id, photo_path FROM yakuman_records WHERE id = ?", (yakuman_id,)).fetchone()
    if not row:
        raise ValueError("Could not find that yakuman record.")
    connection.execute(
        """
        UPDATE yakuman_records
        SET photo_path = COALESCE(NULLIF(?, ''), photo_path),
            photo_caption = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (str(photo_path or "").strip(), str(photo_caption or "").strip(), yakuman_id),
    )
    connection.commit()
    return {"id": yakuman_id, "old_photo_path": row["photo_path"] or "", "photo_path": photo_path or row["photo_path"] or "", "photo_caption": photo_caption or ""}


def yakuman_leaders(connection, limit=10):
    rows = connection.execute(
        """
        SELECT p.name, COUNT(*) AS yakuman_count
        FROM yakuman_records yr
        JOIN players p ON p.id = yr.winner_id
        GROUP BY p.id
        ORDER BY yakuman_count DESC, p.name COLLATE NOCASE ASC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [{"rank": index, "name": row["name"], "yakuman_count": row["yakuman_count"]} for index, row in enumerate(rows, 1)]


def resolve_player_name(connection, player_name):
    target = normalize_name(player_name)
    if not target:
        return ""
    exact = connection.execute("SELECT name FROM players WHERE name_key = ?", (target,)).fetchone()
    if exact:
        return exact["name"]
    matches = connection.execute(
        "SELECT name FROM players WHERE name_key LIKE ? ORDER BY name COLLATE NOCASE",
        (f"%{target}%",),
    ).fetchall()
    return matches[0]["name"] if len(matches) == 1 else player_name


def recent_games(connection, limit=12, player_name="", quarter=None):
    target = normalize_name(player_name)
    if target:
        player = connection.execute("SELECT id, name FROM players WHERE name_key = ?", (target,)).fetchone()
        if not player:
            resolved = resolve_player_name(connection, player_name)
            player = connection.execute("SELECT id, name FROM players WHERE name_key = ?", (normalize_name(resolved),)).fetchone()
        if not player:
            return [], player_name
        game_rows = connection.execute(
            f"""
            SELECT g.*
            FROM games g
            JOIN game_players gp ON gp.game_id = g.id
            WHERE gp.player_id = ?
              {"AND g.quarter = ?" if quarter else ""}
            ORDER BY g.id DESC
            LIMIT ?
            """,
            (player["id"], quarter, limit) if quarter else (player["id"], limit),
        ).fetchall()
        resolved_name = player["name"]
    else:
        game_rows = connection.execute(
            f"SELECT * FROM games {'WHERE quarter = ?' if quarter else ''} ORDER BY id DESC LIMIT ?",
            (quarter, limit) if quarter else (limit,),
        ).fetchall()
        resolved_name = ""

    games = []
    for game in game_rows:
        player_rows = connection.execute(
            """
            SELECT p.name, gp.final_score, gp.mmr_delta, gp.pt_delta
            FROM game_players gp
            JOIN players p ON p.id = gp.player_id
            WHERE gp.game_id = ?
            ORDER BY gp.rank_order ASC
            """,
            (game["id"],),
        ).fetchall()
        games.append(
            {
                "id": f"sql-{game['id']}",
                "created_at": game["played_at"],
                "date": game["played_at"],
                "user_name": game["created_by"],
                "players": [
                    {
                        "name": row["name"],
                        "score": row["final_score"],
                        "delta": row["mmr_delta"],
                        "pt_delta": row["pt_delta"],
                    }
                    for row in player_rows
                ],
                "target_player": resolved_name or player_name,
                "reverted": False,
            }
        )
    return games, resolved_name


def games_with_players(connection, player_names, limit=50, quarter=None):
    keys = [normalize_name(name) for name in player_names if normalize_name(name)]
    seen = []
    for key in keys:
        if key not in seen:
            seen.append(key)
    if not seen:
        return []

    placeholders = ",".join("?" for _ in seen)
    params = [*seen]
    quarter_clause = ""
    if quarter:
        quarter_clause = "AND g.quarter = ?"
        params.append(quarter)
    params.extend([len(seen), int(limit)])
    game_rows = connection.execute(
        f"""
        SELECT g.*
        FROM games g
        JOIN game_players gp ON gp.game_id = g.id
        JOIN players p ON p.id = gp.player_id
        WHERE p.name_key IN ({placeholders})
          {quarter_clause}
        GROUP BY g.id
        HAVING COUNT(DISTINCT p.name_key) = ?
        ORDER BY g.id DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [game_summary(connection, game) for game in game_rows]


def game_summary(connection, game):
    player_rows = connection.execute(
        """
        SELECT p.name, gp.final_score, gp.placement, gp.mmr_delta, gp.pt_delta
        FROM game_players gp
        JOIN players p ON p.id = gp.player_id
        WHERE gp.game_id = ?
        ORDER BY gp.rank_order ASC
        """,
        (game["id"],),
    ).fetchall()
    return {
        "id": f"sql-{game['id']}",
        "game_id": game["id"],
        "created_at": game["played_at"],
        "date": game["played_at"],
        "user_name": game["created_by"],
        "quarter": game["quarter"] or "",
        "players": [
            {
                "name": row["name"],
                "score": row["final_score"],
                "placement": row["placement"],
                "delta": row["mmr_delta"],
                "pt_delta": row["pt_delta"],
            }
            for row in player_rows
        ],
        "reverted": False,
    }


def latest_game_for_player(connection, player_name):
    resolved_name = resolve_player_name(connection, player_name)
    player = connection.execute("SELECT id, name FROM players WHERE name_key = ?", (normalize_name(resolved_name),)).fetchone()
    if not player:
        return None
    game = connection.execute(
        """
        SELECT g.*
        FROM games g
        JOIN game_players gp ON gp.game_id = g.id
        WHERE gp.player_id = ?
        ORDER BY g.id DESC
        LIMIT 1
        """,
        (player["id"],),
    ).fetchone()
    if not game:
        return None
    players = [
        row["name"]
        for row in connection.execute(
            """
            SELECT p.name
            FROM game_players gp
            JOIN players p ON p.id = gp.player_id
            WHERE gp.game_id = ?
            ORDER BY gp.rank_order ASC
            """,
            (game["id"],),
        )
    ]
    return {"id": game["id"], "played_at": game["played_at"], "players": players, "winner": player["name"]}


def quarter_pt_history(connection, player_name, quarter=None, limit=200):
    resolved_name = resolve_player_name(connection, player_name)
    target = normalize_name(resolved_name)
    if not target:
        return [], ""

    player = connection.execute("SELECT id, name FROM players WHERE name_key = ?", (target,)).fetchone()
    if not player:
        return [], resolved_name or player_name

    selected_quarter = quarter or latest_quarter(connection)
    rows = connection.execute(
        """
        SELECT g.id, g.played_at, gp.pt_delta, gp.placement, gp.final_score
        FROM game_players gp
        JOIN games g ON g.id = gp.game_id
        WHERE gp.player_id = ? AND g.quarter = ?
        ORDER BY g.id ASC
        """,
        (player["id"], selected_quarter),
    ).fetchall()
    if limit and len(rows) > limit:
        rows = rows[-limit:]

    cumulative = 0.0
    points = []
    for index, row in enumerate(rows, 1):
        cumulative += float(row["pt_delta"] or 0)
        opponent_rows = connection.execute(
            """
            SELECT p.name
            FROM game_players gp
            JOIN players p ON p.id = gp.player_id
            WHERE gp.game_id = ? AND gp.player_id <> ?
            ORDER BY gp.rank_order ASC
            """,
            (row["id"], player["id"]),
        ).fetchall()
        points.append(
            {
                "game_id": f"sql-{row['id']}",
                "index": index,
                "date": row["played_at"],
                "pt_delta": round(float(row["pt_delta"] or 0), 1),
                "quarter_pt": round(cumulative, 1),
                "placement": int(row["placement"]),
                "score": int(row["final_score"]),
                "opponents": [opponent["name"] for opponent in opponent_rows],
            }
        )

    return points, player["name"]


def current_quarter_pt(connection, player_id):
    quarter = latest_quarter(connection)
    if not quarter:
        row = connection.execute("SELECT total_pt FROM players WHERE id = ?", (player_id,)).fetchone()
        return row["total_pt"] if row else 0
    row = connection.execute(
        """
        SELECT COALESCE(SUM(gp.pt_delta), 0) AS value
        FROM game_players gp
        JOIN games g ON g.id = gp.game_id
        WHERE gp.player_id = ? AND g.quarter = ?
        """,
        (player_id, quarter),
    ).fetchone()
    return row["value"] if row else 0


def quarter_mmr_delta(connection, player_id):
    quarter = latest_quarter(connection)
    if not quarter:
        row = connection.execute("SELECT current_mmr FROM players WHERE id = ?", (player_id,)).fetchone()
        return row["current_mmr"] if row else 1500
    row = connection.execute(
        """
        SELECT COALESCE(SUM(gp.mmr_delta), 0) AS value
        FROM game_players gp
        JOIN games g ON g.id = gp.game_id
        WHERE gp.player_id = ? AND g.quarter = ?
        """,
        (player_id, quarter),
    ).fetchone()
    return row["value"] if row else 0


def current_quarter_mmr(connection, player_id):
    quarter = latest_quarter(connection)
    if not quarter:
        row = connection.execute("SELECT current_mmr FROM players WHERE id = ?", (player_id,)).fetchone()
        return row["current_mmr"] if row else 1500
    row = connection.execute(
        """
        SELECT gp.mmr_after AS value
        FROM game_players gp
        JOIN games g ON g.id = gp.game_id
        WHERE gp.player_id = ? AND g.quarter = ?
        ORDER BY g.id DESC
        LIMIT 1
        """,
        (player_id, quarter),
    ).fetchone()
    if row:
        return row["value"]
    row = connection.execute("SELECT current_mmr FROM players WHERE id = ?", (player_id,)).fetchone()
    return row["current_mmr"] if row else 1500


def rank_in_metric(connection, player_id, kind, quarter=None):
    rows = ranking(connection, kind=kind, limit=10000, quarter=quarter)
    name = connection.execute("SELECT name FROM players WHERE id = ?", (player_id,)).fetchone()
    if not name:
        return None
    target = normalize_name(name["name"])
    for row in rows:
        if normalize_name(row["name"]) == target:
            return row["rank"]
    return None


def rank_total_for_metric(connection, kind, quarter=None):
    rows = ranking(connection, kind=kind, limit=10000, quarter=quarter)
    return len(rows)


def round1(value):
    try:
        return round(float(value), 1)
    except (TypeError, ValueError):
        return 0.0


def round_int(value):
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return 0


def rank_percentile(connection, rank):
    if not rank:
        return None
    row = connection.execute(
        "SELECT COUNT(*) AS count FROM players WHERE games_played > 0"
    ).fetchone()
    total = int(row["count"] or 0) if row else 0
    if total <= 0:
        return None
    return round((rank / total) * 100, 1)


def personal_data(connection, player_name, limit=15, quarter=None):
    resolved_name = resolve_player_name(connection, player_name)
    target = normalize_name(resolved_name)
    player = connection.execute("SELECT * FROM players WHERE name_key = ?", (target,)).fetchone()
    if not player:
        return None

    counts = {1: 0, 2: 0, 3: 0, 4: 0}
    where = "gp.player_id = ?"
    params = [player["id"]]
    if quarter and quarter != "Total games":
        where += " AND g.quarter = ?"
        params.append(quarter)

    rows = connection.execute(
        f"""
        SELECT g.id, gp.placement, gp.final_score, gp.pt_delta, gp.mmr_delta, gp.mmr_before, gp.mmr_after,
               g.played_at, g.yakuman_winner, g.yakuman_text
        FROM game_players gp
        JOIN games g ON g.id = gp.game_id
        WHERE {where}
        ORDER BY g.id ASC
        """,
        params,
    ).fetchall()
    # Registered players with no games in the selected scope still have profiles.
    sample_count = max(1, len(rows))
    highest_point = max((row["final_score"] for row in rows), default=0)
    avg_point = sum(row["final_score"] for row in rows) / sample_count
    avg_place = sum(row["placement"] for row in rows) / sample_count
    selected_pt = sum(row["pt_delta"] for row in rows)
    if not quarter:
        selected_pt = current_quarter_pt(connection, player["id"])
    elif quarter == "Total games":
        selected_pt = player["total_pt"]
    for row in rows:
        counts[row["placement"]] += 1

    latest_mmr = rows[-1]["mmr_after"] if rows else player["current_mmr"]
    highest_mmr = max((row["mmr_after"] for row in rows), default=player["current_mmr"])
    first_rate = counts[1] / sample_count
    top2_rate = (counts[1] + counts[2]) / sample_count
    avoid_last_rate = 1 - (counts[4] / sample_count) if rows else 0
    pt_history = []
    cumulative_pt = 0.0
    for index, row in enumerate(rows, 1):
        cumulative_pt += float(row["pt_delta"] or 0)
        pt_history.append(
            {
                "index": index,
                "date": row["played_at"],
                "pt_delta": round1(row["pt_delta"]),
                "cumulative_pt": round1(cumulative_pt),
                "mmr_delta": round1(row["mmr_delta"]),
                "mmr_after": round1(row["mmr_after"]),
                "placement": int(row["placement"]),
                "score": int(row["final_score"]),
            }
        )

    yakuman_records = [
        {"time": row["played_at"], "names": [row["yakuman_name"]], "note": row["note"], "yakuman": row["yakuman_name"]}
        for row in connection.execute(
            f"""
            SELECT yr.played_at, yr.yakuman_name, yr.note
            FROM yakuman_records yr
            LEFT JOIN games g ON g.id = yr.game_id
            WHERE yr.winner_id = ?
            {"AND g.quarter = ?" if quarter and quarter != "Total games" else ""}
            ORDER BY yr.id ASC
            """,
            (player["id"], quarter) if quarter and quarter != "Total games" else (player["id"],),
        )
    ]

    max_first_streak = 0
    current_first_streak = 0
    for row in rows:
        if row["placement"] == 1:
            current_first_streak += 1
            max_first_streak = max(max_first_streak, current_first_streak)
        else:
            current_first_streak = 0

    recent_rows = list(reversed(rows))[:limit]
    recent_chronological = list(reversed(recent_rows))
    return {
        "info": {
            "total_pt": round1(selected_pt),
            "avg_place": round1(avg_place),
            "top2_rate": round1(top2_rate * 100),
            "avoid_last_rate": round1(avoid_last_rate * 100),
            "highest_point": round_int(highest_point),
            "avg_point": round_int(avg_point),
            "rate_1st": counts[1] / sample_count,
            "rate_2nd": counts[2] / sample_count,
            "rate_3rd": counts[3] / sample_count,
            "rate_4th": counts[4] / sample_count,
            "count_1st": counts[1],
            "count_2nd": counts[2],
            "count_3rd": counts[3],
            "count_4th": counts[4],
            "total_games": len(rows),
            "source_sheet": "SQLite",
        },
        "pt_history": [row["pt_delta"] for row in recent_rows],
        "mmr_history": [row["mmr_delta"] for row in recent_rows],
        "rank_history": [str(row["placement"]) for row in recent_rows],
        "pt_chart_data": [row["pt_delta"] for row in recent_chronological],
        "current_mmr": round1(latest_mmr),
        "highest_mmr": round1(highest_mmr),
        "yakuman_count": len(yakuman_records),
        "yakuman_records": yakuman_records[-10:],
        "max_first_streak": max_first_streak,
        "quarter_pt": round1(selected_pt),
        "scope_label": quarter or f"Latest {limit}",
        "stats_sheet_name": "SQLite",
        "mmr_start": recent_chronological[0]["mmr_before"] if recent_chronological else None,
        "mmr_end": recent_chronological[-1]["mmr_after"] if recent_chronological else None,
        "selected_game_count": len(rows),
        "trend_game_count": len(recent_rows),
        "history": pt_history[-100:],
        "radar": {
            "实力(MMR)": min(100, max(0, (float(latest_mmr) - 1300) / 4)),
            "效率(平均PT)": min(100, max(0, (float(selected_pt) / max(1, len(rows)) + 30) / 0.6)),
            "顺位(平均)": min(100, max(0, (4 - float(avg_place)) / 3 * 100)) if rows else 0,
            "进攻(一位率)": round1(first_rate * 100),
            "防守(避四率)": round1(avoid_last_rate),
            "近况(近10)": min(100, max(0, sum(1 for item in rows[-10:] if item["placement"] <= 2) / max(1, min(10, len(rows))) * 100)),
        },
    }


def user_summary(connection, username, quarter=None):
    target = normalize_name(username)
    row = connection.execute("SELECT * FROM players WHERE name_key = ?", (target,)).fetchone()
    if not row:
        return None
    stats = {item["name"]: item for item in player_stats(connection)}
    item = stats.get(row["name"], {})
    quarter_pt_value = current_quarter_pt(connection, row["id"])
    quarter_mmr_value = current_quarter_mmr(connection, row["id"])
    current_quarter = latest_quarter(connection)
    personal_scope = quarter if quarter is not None else current_quarter
    scoped_quarter = personal_scope if personal_scope and personal_scope != "Total games" else None
    scoped_mmr_kind = "quarter_mmr" if scoped_quarter else "total_mmr"
    scoped_pt_kind = "quarter_pt" if scoped_quarter else "total_pt"
    mmr_rank = rank_in_metric(connection, row["id"], scoped_mmr_kind, quarter=scoped_quarter)
    pt_rank = rank_in_metric(connection, row["id"], scoped_pt_kind, quarter=scoped_quarter)
    mmr_total = rank_total_for_metric(connection, scoped_mmr_kind, quarter=scoped_quarter)
    pt_total = rank_total_for_metric(connection, scoped_pt_kind, quarter=scoped_quarter)
    summary = {
        "name": row["name"],
        "games_played": row["games_played"],
        "wins": row["wins"],
        "win_rate": item.get("win_rate", 0),
        "avg_place": item.get("avg_place", 0),
        "top2_rate": item.get("top2_rate", 0),
    }
    summary["quarter_pt"] = {"rank": rank_in_metric(connection, row["id"], "quarter_pt"), "value": format_number(quarter_pt_value), "label": "Quarter PT"}
    summary["total_pt"] = {"rank": item.get("pt_rank"), "value": format_number(row["total_pt"]), "label": "Total PT"}
    summary["quarter_mmr"] = {"rank": rank_in_metric(connection, row["id"], "quarter_mmr"), "value": format_number(quarter_mmr_value), "label": "Quarter MMR"}
    total_mmr_rank = item.get("mmr_rank")
    summary["total_mmr"] = {
        "rank": total_mmr_rank,
        "percentile": rank_percentile(connection, total_mmr_rank),
        "value": format_number(row["current_mmr"]),
        "label": "Total MMR",
    }
    summary["history_highest_mmr"] = {
        "rank": item.get("history_highest_mmr_rank"),
        "value": format_number(row["history_highest_mmr"] or 1500),
        "label": "History Highest MMR",
    }
    personal = personal_data(connection, username, limit=15, quarter=personal_scope)
    if personal:
        info = personal.get("info", {})
        summary["personal_data"] = {
            "scope": personal_scope or "Current quarter",
            "mmr_value": personal.get("current_mmr"),
            "mmr_rank": mmr_rank,
            "mmr_rank_total": mmr_total,
            "pt_value": info.get("total_pt", 0),
            "pt_rank": pt_rank,
            "pt_rank_total": pt_total,
            "avg_place": info.get("avg_place", ""),
            "top2_rate": info.get("top2_rate", 0),
            "avoid_last_rate": info.get("avoid_last_rate", 0),
            "highest_point": info.get("highest_point", ""),
            "avg_point": info.get("avg_point", ""),
            "placement_counts": {
                "1st": info.get("count_1st", 0),
                "2nd": info.get("count_2nd", 0),
                "3rd": info.get("count_3rd", 0),
                "4th": info.get("count_4th", 0),
            },
            "yakuman_count": personal.get("yakuman_count", 0),
            "yakuman_records": personal.get("yakuman_records", []),
            "max_first_streak": personal.get("max_first_streak", 0),
            "mmr_start": format_number(personal.get("mmr_start")) if personal.get("mmr_start") is not None else "",
            "mmr_end": format_number(personal.get("mmr_end")) if personal.get("mmr_end") is not None else "",
            "history": personal.get("history", []),
            "radar": personal.get("radar", {}),
            "selected_game_count": personal.get("selected_game_count", 0),
        }
    return summary


def school_year_label_from_quarter(quarter):
    parts = str(quarter or "").strip().split()
    if len(parts) != 2:
        return ""
    try:
        year = int(parts[0])
    except ValueError:
        return ""
    term = parts[1].casefold()
    if term == "fall":
        return f"{year}-{year + 1}"
    if term in {"winter", "spring"}:
        return f"{year - 1}-{year}"
    return ""


def school_year_quarters(label):
    match = re.match(r"^\s*(20\d{2})\s*-\s*(20\d{2})\s*$", str(label or ""))
    if not match:
        return []
    start = int(match.group(1))
    return [f"{start} Fall", f"{start + 1} Winter", f"{start + 1} Spring"]


def school_years(connection):
    labels = []
    seen = set()
    rows = connection.execute(
        "SELECT DISTINCT quarter FROM games WHERE COALESCE(quarter, '') <> '' ORDER BY quarter"
    ).fetchall()
    for row in rows:
        label = school_year_label_from_quarter(row["quarter"])
        if label and label not in seen:
            labels.append(label)
            seen.add(label)
    return sorted(labels, reverse=True)


def annual_summary(connection, username, school_year=None):
    player = connection.execute(
        "SELECT id, name FROM players WHERE name_key = ?",
        (normalize_name(username),),
    ).fetchone()
    if not player:
        return None

    years = school_years(connection)
    if not school_year:
        current = latest_quarter(connection)
        school_year = school_year_label_from_quarter(current) or (years[0] if years else "")
    if school_year and school_year not in years:
        years.insert(0, school_year)
    quarters_in_year = school_year_quarters(school_year)
    if not quarters_in_year:
        return {"name": player["name"], "school_year": school_year or "", "years": years, "items": [], "games": 0}

    placeholders = ",".join("?" for _ in quarters_in_year)
    rows = connection.execute(
        f"""
        SELECT g.id, g.played_at, g.quarter, gp.final_score, gp.placement, gp.pt_delta
        FROM game_players gp
        JOIN games g ON g.id = gp.game_id
        WHERE gp.player_id = ? AND g.quarter IN ({placeholders})
        ORDER BY g.id ASC
        """,
        (player["id"], *quarters_in_year),
    ).fetchall()
    if not rows:
        return {"name": player["name"], "school_year": school_year, "years": years, "items": [], "games": 0}

    def day_key(played_at):
        text = str(played_at or "")
        return text[:10] if len(text) >= 10 and text[4:5] == "-" else text[:4] or "Unknown"

    def opponents(game_id):
        return [
            row["name"]
            for row in connection.execute(
                """
                SELECT p.name
                FROM game_players gp
                JOIN players p ON p.id = gp.player_id
                WHERE gp.game_id = ? AND gp.player_id <> ?
                ORDER BY gp.rank_order ASC
                """,
                (game_id, player["id"]),
            )
        ]

    def streak(predicate):
        best = current = 0
        start = best_start = best_end = None
        for row in rows:
            if predicate(row):
                if current == 0:
                    start = row["played_at"]
                current += 1
                if current > best:
                    best = current
                    best_start = start
                    best_end = row["played_at"]
            else:
                current = 0
                start = None
        return best, best_start, best_end

    by_day = {}
    pt_by_day = {}
    latest_row = rows[0]
    high_score = max(rows, key=lambda row: row["final_score"])
    low_score = min(rows, key=lambda row: row["final_score"])
    for row in rows:
        key = day_key(row["played_at"])
        by_day[key] = by_day.get(key, 0) + 1
        pt_by_day[key] = pt_by_day.get(key, 0.0) + float(row["pt_delta"] or 0)
        if str(row["played_at"]) > str(latest_row["played_at"]):
            latest_row = row

    opponent_stats = {}
    for row in rows:
        won = int(row["placement"]) == 1
        lost = int(row["placement"]) == 4
        for name in opponents(row["id"]):
            stat = opponent_stats.setdefault(name, {"games": 0, "wins": 0, "losses": 0})
            stat["games"] += 1
            stat["wins"] += 1 if won else 0
            stat["losses"] += 1 if lost else 0

    eligible = [(name, stat) for name, stat in opponent_stats.items() if stat["games"] >= 2]
    best_opp = max(eligible, key=lambda item: (item[1]["wins"] / item[1]["games"], item[1]["games"])) if eligible else None
    worst_opp = max(eligible, key=lambda item: (item[1]["losses"] / item[1]["games"], item[1]["games"])) if eligible else None
    top2_streak = streak(lambda row: int(row["placement"]) <= 2)
    bottom2_streak = streak(lambda row: int(row["placement"]) >= 3)
    first_streak = streak(lambda row: int(row["placement"]) == 1)
    fourth_streak = streak(lambda row: int(row["placement"]) == 4)
    yakuman_row = connection.execute(
        f"""
        SELECT COUNT(*) AS count
        FROM yakuman_records yr
        JOIN games g ON g.id = yr.game_id
        WHERE yr.winner_id = ? AND g.quarter IN ({placeholders})
        """,
        (player["id"], *quarters_in_year),
    ).fetchone()

    busiest_day, busiest_count = max(by_day.items(), key=lambda item: item[1])
    best_pt_day, best_pt = max(pt_by_day.items(), key=lambda item: item[1])
    worst_pt_day, worst_pt = min(pt_by_day.items(), key=lambda item: item[1])

    items = [
        {"key": "busiest_day", "title_cn": "对局最多的一天", "title_en": "Busiest day", "value": f"{busiest_day} · {busiest_count} games", "comment_cn": "这天牌桌热度拉满。", "comment_en": "The table was properly alive that day."},
        {"key": "latest_game", "title_cn": "最晚对局", "title_en": "Latest match", "value": latest_row["played_at"], "comment_cn": "夜战记录在案。", "comment_en": "A late-night entry in the ledger."},
        {"key": "highest_score", "title_cn": "全年最高原始分", "title_en": "Highest raw score", "value": f"{high_score['final_score']} vs {' / '.join(opponents(high_score['id']))}", "comment_cn": "这局是火力展示。", "comment_en": "That one was a clean power spike."},
        {"key": "lowest_score", "title_cn": "全年最低原始分", "title_en": "Lowest raw score", "value": f"{low_score['final_score']} vs {' / '.join(opponents(low_score['id']))}", "comment_cn": "低谷也算履历的一部分。", "comment_en": "The rough games count too."},
        {"key": "best_opponent", "title_cn": "遇到谁胜率最高", "title_en": "Best matchup", "value": f"{best_opp[0]} · {best_opp[1]['games']} games / {best_opp[1]['wins']} wins" if best_opp else "Not enough data", "comment_cn": "这个对位目前手感最好。", "comment_en": "This matchup has treated you kindly."},
        {"key": "worst_opponent", "title_cn": "遇到谁胜率最低", "title_en": "Hardest matchup", "value": f"{worst_opp[0]} · {worst_opp[1]['games']} games / {worst_opp[1]['losses']} losses" if worst_opp else "Not enough data", "comment_cn": "下次见面值得重点盯防。", "comment_en": "Worth watching closely next time."},
        {"key": "best_pt_day", "title_cn": "加分最多的一天", "title_en": "Best PT day", "value": f"{best_pt_day} · {format_number(best_pt)} PT", "comment_cn": "这天很会收米。", "comment_en": "That day paid out."},
        {"key": "worst_pt_day", "title_cn": "扣分最多的一天", "title_en": "Worst PT day", "value": f"{worst_pt_day} · {format_number(worst_pt)} PT", "comment_cn": "这天适合封存。", "comment_en": "A day best left in the archive."},
        {"key": "top2_streak", "title_cn": "最多连队次数", "title_en": "Longest top-2 streak", "value": f"{top2_streak[0]} games · {top2_streak[1] or ''} to {top2_streak[2] or ''}", "comment_cn": "稳定上桌，非常硬。", "comment_en": "Reliable table control."},
        {"key": "bottom2_streak", "title_cn": "最霉时刻", "title_en": "Unluckiest stretch", "value": f"{bottom2_streak[0]} games · {bottom2_streak[1] or ''} to {bottom2_streak[2] or ''}", "comment_cn": "连续三四位，确实难顶。", "comment_en": "A painful run of bottom-half finishes."},
        {"key": "first_streak", "title_cn": "最狗时刻", "title_en": "Longest 1st-place streak", "value": f"{first_streak[0]} games · {first_streak[1] or ''} to {first_streak[2] or ''}", "comment_cn": "这一段像是开了光。", "comment_en": "A very blessed streak."},
        {"key": "fourth_streak", "title_cn": "最多连4", "title_en": "Longest 4th-place streak", "value": f"{fourth_streak[0]} games · {fourth_streak[1] or ''} to {fourth_streak[2] or ''}", "comment_cn": "这段建议不要深夜复盘。", "comment_en": "Maybe do not review this one at midnight."},
        {"key": "yakuman", "title_cn": "全年役满", "title_en": "Yearly yakuman", "value": f"{yakuman_row['count'] if yakuman_row else 0}", "comment_cn": "役满是年度相册里的高光。", "comment_en": "Yakuman belongs in the highlight reel."},
    ]
    return {"name": player["name"], "school_year": school_year, "years": years, "games": len(rows), "items": items}


def has_games(connection):
    row = connection.execute("SELECT COUNT(*) AS count FROM games").fetchone()
    return bool(row and row["count"])


def format_number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value or "")
    return str(int(number)) if number.is_integer() else f"{number:.2f}"
