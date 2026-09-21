"""Fresh read-only player lookup shared by Discord commands.

SQLite is also the website directory, including players with no games.
Autocomplete must not run migrations or contact Google Sheets.
"""
import os
import sqlite3
from contextlib import closing
from pathlib import Path
import mahjong_store
import registered_names


def player_names(db_file=None):
    path = Path(db_file or os.getenv("MAHJONG_DB_FILE") or mahjong_store.DEFAULT_DB_FILE)
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=1)) as db:
        return [row[0] for row in db.execute("SELECT name FROM players ORDER BY name COLLATE NOCASE")]


def matching_names(names, current):
    query = registered_names.normalize_name(current)
    matches = [name for name in names if query in registered_names.normalize_name(name)]
    matches.sort(key=lambda name: (registered_names.normalize_name(name) != query,
                                  not registered_names.normalize_name(name).startswith(query),
                                  registered_names.normalize_name(name)))
    return matches[:25]
