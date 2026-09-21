"""Idempotent, additive manual-score migration; no historical results change."""
from sqlalchemy.orm import Session
from sqlalchemy import inspect, text

from .database_models import Metadata
from .manual_score_models import ManualScoreDraft, ManualScorePlayer, ManualScoreRequest


def migrate_manual_scores(engine):
    for model in (ManualScoreDraft, ManualScorePlayer, ManualScoreRequest):
        model.__table__.create(engine, checkfirst=True)
    if "played_at" not in {c["name"] for c in inspect(engine).get_columns("manual_score_drafts")}:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE manual_score_drafts ADD COLUMN played_at VARCHAR(40)"))
    with Session(engine) as db, db.begin():
        if db.get(Metadata, "manual_score_v1_migrated") is None:
            db.add(Metadata(key="manual_score_v1_migrated", value="1"))
