from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator


class Seat(str, Enum):
    east = "east"
    south = "south"
    west = "west"
    north = "north"


SEATS = tuple(seat.value for seat in Seat)
SEAT_NAMES = dict(zip(SEATS, ("东", "南", "西", "北")))
TableId = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")]


class User(BaseModel):
    id: str | int
    role: str = "user"

    @field_validator("id", mode="before")
    @classmethod
    def validate_id(cls, value):
        if type(value) is bool or not str(value) or len(str(value)) > 128:
            raise ValueError("Invalid account ID")
        return value
    name: str = Field(min_length=1, max_length=128)


SCORE_STEP = 100
SCORE_MAX_ABSOLUTE = 10_000_000


class Scores(BaseModel):
    model_config = ConfigDict(extra="forbid")
    east: StrictInt
    south: StrictInt
    west: StrictInt
    north: StrictInt

    @field_validator("*")
    @classmethod
    def validate_points(cls, value: int):
        # Negative final points are valid; decimals, booleans and OCR noise are not.
        if abs(value) > SCORE_MAX_ABSOLUTE or value % SCORE_STEP:
            raise ValueError("点数必须是 100 的整数倍，且绝对值不超过 10,000,000")
        return value


class SubmitScores(BaseModel):
    model_config = ConfigDict(extra="forbid")
    table: TableId
    scores: Scores
    match_id: str | None = Field(default=None, min_length=1, max_length=64)

    @field_validator("table", mode="before")
    @classmethod
    def normalize_table(cls, value):
        return str(value) if type(value) is int else value


class RelativeScores(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bottom: str = Field(max_length=128)
    right: str = Field(max_length=128)
    top: str = Field(max_length=128)
    left: str = Field(max_length=128)


class RelativeSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")
    table: TableId
    scores: RelativeScores
    match_id: str | None = Field(default=None, min_length=1, max_length=64)
    viewpoint_seat: Seat | None = None

    @field_validator("table", mode="before")
    @classmethod
    def normalize_table(cls, value):
        return str(value) if type(value) is int else value


class ConfirmScores(BaseModel):
    model_config = ConfigDict(extra="forbid")
    draft_id: str = Field(min_length=1, max_length=64)
    scores: Scores
