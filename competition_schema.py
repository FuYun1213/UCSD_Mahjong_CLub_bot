"""Additive date-window competition ledger in the authoritative club database."""
SCHEMA = """
CREATE TABLE IF NOT EXISTS competitions (
 id TEXT PRIMARY KEY, slug TEXT NOT NULL UNIQUE, title TEXT NOT NULL,
 introduction TEXT NOT NULL DEFAULT '', timezone TEXT NOT NULL,
 start_at TEXT NOT NULL, end_at TEXT NOT NULL,
 scoring_mode TEXT NOT NULL CHECK(scoring_mode='placement_and_game_count'),
 rules_json TEXT NOT NULL, pending_rules_json TEXT,
 auto_enrollment INTEGER NOT NULL DEFAULT 1, published INTEGER NOT NULL DEFAULT 0,
 featured INTEGER NOT NULL DEFAULT 0, leaderboard_public INTEGER NOT NULL DEFAULT 0,
 draft_json TEXT NOT NULL DEFAULT '{}', published_json TEXT NOT NULL DEFAULT '{}',
 version INTEGER NOT NULL DEFAULT 1, rules_version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 leaderboard_updated_at TEXT, CHECK(start_at < end_at)
);
CREATE INDEX IF NOT EXISTS competition_dates ON competitions(start_at,end_at,published);
CREATE TABLE IF NOT EXISTS competition_participants (
 id TEXT PRIMARY KEY, competition_id TEXT NOT NULL REFERENCES competitions(id),
 identity_key TEXT NOT NULL, name TEXT NOT NULL, normalized_name TEXT NOT NULL,
 participant_type TEXT NOT NULL, avatar TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
 UNIQUE(competition_id,identity_key)
);
CREATE TABLE IF NOT EXISTS competition_games (
 game_key TEXT PRIMARY KEY, played_at TEXT, status TEXT NOT NULL, source TEXT NOT NULL,
 players_json TEXT NOT NULL, fingerprint TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS competition_scores (
 competition_id TEXT NOT NULL REFERENCES competitions(id), game_key TEXT NOT NULL REFERENCES competition_games(game_key),
 participant_id TEXT NOT NULL REFERENCES competition_participants(id),
 placement INTEGER NOT NULL CHECK(placement BETWEEN 1 AND 4), placement_score TEXT NOT NULL,
 participation_score TEXT NOT NULL, total_score TEXT NOT NULL, rule_version INTEGER NOT NULL,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 PRIMARY KEY(competition_id,game_key,participant_id)
);
CREATE INDEX IF NOT EXISTS competition_score_participant ON competition_scores(competition_id,participant_id);
CREATE INDEX IF NOT EXISTS competition_score_game ON competition_scores(competition_id,game_key);
CREATE TABLE IF NOT EXISTS competition_audit (
 id INTEGER PRIMARY KEY AUTOINCREMENT, competition_id TEXT, actor TEXT NOT NULL,
 action TEXT NOT NULL, details_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS competition_game_overrides (
 game_key TEXT PRIMARY KEY, patch_json TEXT NOT NULL, reason TEXT NOT NULL, actor TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS competition_game_tombstones (
 game_key TEXT PRIMARY KEY, reason TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS competition_identity_links (
 alias TEXT PRIMARY KEY, identity_key TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS competition_jobs (
 id TEXT PRIMARY KEY, competition_id TEXT NOT NULL REFERENCES competitions(id),
 rebuild INTEGER NOT NULL, actor TEXT NOT NULL, reason TEXT NOT NULL,
 request_key TEXT NOT NULL UNIQUE, status TEXT NOT NULL DEFAULT 'pending',
 attempts INTEGER NOT NULL DEFAULT 0, available_at REAL NOT NULL DEFAULT 0,
 lease_until REAL, error_code TEXT, created_at TEXT NOT NULL, finished_at TEXT
);
CREATE INDEX IF NOT EXISTS competition_jobs_ready ON competition_jobs(status,available_at);
CREATE TABLE IF NOT EXISTS competition_images (
 id TEXT PRIMARY KEY, small_file TEXT NOT NULL, large_file TEXT NOT NULL,
 alt TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, actor TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS competition_image_originals (
 image_id TEXT PRIMARY KEY REFERENCES competition_images(id) ON DELETE CASCADE,
 original_file TEXT NOT NULL, width INTEGER NOT NULL, height INTEGER NOT NULL
);
"""


def migrate(db):
    db.executescript(SCHEMA)
    existing = {r[1] for r in db.execute("PRAGMA table_info(games)")}
    if existing:
        for name, definition in {"authoritative_played_at":"TEXT", "played_at_source":"TEXT",
                                 "record_status":"TEXT NOT NULL DEFAULT 'confirmed'", "is_test":"INTEGER NOT NULL DEFAULT 0",
                                 "duplicate_of":"TEXT"}.items():
            if name not in existing:
                db.execute("ALTER TABLE games ADD COLUMN " + name + " " + definition)
    db.commit()
