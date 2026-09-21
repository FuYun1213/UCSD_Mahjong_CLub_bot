"""Additive notification outbox migration; no existing account/history writes."""
from sqlalchemy.orm import Session
from .database_models import Metadata
from .discord_reminder_models import DiscordReminder, DiscordReminderThrottle


def migrate_discord_reminders(engine):
    DiscordReminder.__table__.create(engine, checkfirst=True)
    DiscordReminderThrottle.__table__.create(engine, checkfirst=True)
    with Session(engine) as db, db.begin():
        if db.get(Metadata, "discord_reservation_reminders_v1") is None:
            db.add(Metadata(key="discord_reservation_reminders_v1", value="1"))
