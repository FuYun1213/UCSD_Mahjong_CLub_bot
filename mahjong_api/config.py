"""Configuration is separate from the existing bot's credentials/settings."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    database_path: Path = Path("data/nfc_matches.sqlite3")
    database_url: str = ""
    club_database_path: str = ""
    auth_profile_url: str = ""
    vision_enabled: bool = False
    vision_directory: Path = Path("third_party/lcd_digit_recognition")
    vision_confidence: float = 0.95
    max_photo_bytes: int = 8 * 1024 * 1024
    mock_auth_enabled: bool = False
    yolo_api_key: str = ""
    initial_points: int = 25000
    login_url: str = "/login"
    frontend_sit_path: str = "/sit"
    allowed_origins: tuple[str, ...] = ()
    sheets_enabled: bool = False
    spreadsheet_id: str = ""
    credentials_file: str = "credentials.json"
    current_sheet: str = "当前对局表"
    history_sheet: str = "历史对局记录表"
    sync_interval_seconds: float = 10
    google_timeout_seconds: float = 15

    def __post_init__(self):
        if not 0 < self.vision_confidence <= 1:
            raise ValueError("vision_confidence must be in (0, 1]")
        if self.initial_points <= 0 or self.initial_points % 100:
            raise ValueError("initial_points must be positive and a multiple of 100")
        if self.sync_interval_seconds <= 0 or self.google_timeout_seconds <= 0:
            raise ValueError("Timeouts and intervals must be positive")
        if not self.frontend_sit_path.startswith("/") or self.frontend_sit_path.startswith("//"):
            raise ValueError("frontend_sit_path must be a local absolute path")
        if self.current_sheet == self.history_sheet:
            raise ValueError("Current and history worksheet names must differ")
        if self.sheets_enabled and not self.spreadsheet_id:
            raise ValueError("NFC_SPREADSHEET_ID is required when Sheets is enabled")
        if "*" in self.allowed_origins:
            raise ValueError("Use explicit frontend origins for cookie authentication")

    @classmethod
    def from_env(cls):
        load_dotenv(os.getenv("NFC_ENV_FILE", ".env.nfc"))

        def flag(name: str) -> bool:
            return os.getenv(name, "false").lower() in {"1", "true", "yes"}

        return cls(
            database_path=Path(os.getenv("NFC_DATABASE_PATH", "data/nfc_matches.sqlite3")),
            auth_profile_url=os.getenv("NFC_AUTH_PROFILE_URL", ""),
            database_url=os.getenv("NFC_DATABASE_URL", ""),
            club_database_path=os.getenv("NFC_CLUB_DATABASE_PATH", ""),
            vision_enabled=flag("NFC_VISION_ENABLED"),
            vision_directory=Path(os.getenv("NFC_VISION_DIRECTORY", "third_party/lcd_digit_recognition")),
            vision_confidence=float(os.getenv("NFC_VISION_CONFIDENCE", "0.95")),
            mock_auth_enabled=flag("NFC_MOCK_AUTH_ENABLED"),
            yolo_api_key=os.getenv("NFC_YOLO_API_KEY", ""),
            initial_points=int(os.getenv("NFC_INITIAL_POINTS", "25000")),
            login_url=os.getenv("NFC_LOGIN_URL", "/login"),
            frontend_sit_path=os.getenv("NFC_FRONTEND_SIT_PATH", "/sit"),
            allowed_origins=tuple(x.strip().rstrip("/") for x in os.getenv("NFC_ALLOWED_ORIGINS", "").split(",") if x.strip()),
            sheets_enabled=flag("NFC_SHEETS_ENABLED"),
            spreadsheet_id=os.getenv("NFC_SPREADSHEET_ID", ""),
            credentials_file=os.getenv("NFC_GOOGLE_CREDENTIALS", "credentials.json"),
            current_sheet=os.getenv("NFC_CURRENT_SHEET", "当前对局表"),
            history_sheet=os.getenv("NFC_HISTORY_SHEET", "历史对局记录表"),
            sync_interval_seconds=float(os.getenv("NFC_SYNC_INTERVAL_SECONDS", "10")),
            google_timeout_seconds=float(os.getenv("NFC_GOOGLE_TIMEOUT_SECONDS", "15")),
        )
