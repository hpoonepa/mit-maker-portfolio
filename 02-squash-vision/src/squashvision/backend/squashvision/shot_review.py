"""Versioned, report-scoped human shot reviews; published inference is immutable."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel
from squashvision.schemas import ApiError

Point = tuple[float, float]

class ReviewModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid", allow_inf_nan=False)

def bounded(point, width, height):
    if point is not None and not (0 <= point[0] <= width and 0 <= point[1] <= height):
        raise ValueError("point is outside its coordinate space")
    return point

class ShotImpact(ReviewModel):
    time_us: int = Field(ge=0)
    image: Point | None = None
    position: Point | None = None

    @field_validator("image")
    @classmethod
    def image_bounds(cls, value): return bounded(value, 1, 1)

class ReviewShot(ReviewModel):
    id: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")
    contact_us: int = Field(ge=0)
    hitter: Literal["A", "B"] | None
    type: Literal["drive", "crosscourt", "drop", "boast", "lob", "unknown"]
    origin: Literal["automatic", "reviewed"]
    confidence: float = Field(ge=0, le=1)
    contact_image: Point | None = None
    player_position: Point | None = None
    opponent_position: Point | None = None
    wall: ShotImpact | None = None
    landing: ShotImpact | None = None
    notes: str = Field(default="", max_length=1000)

    @field_validator("contact_image")
    @classmethod
    def image_bounds(cls, value): return bounded(value, 1, 1)

    @field_validator("player_position", "opponent_position")
    @classmethod
    def floor_bounds(cls, value): return bounded(value, 6.4, 9.75)

    @model_validator(mode="after")
    def impact_order(self) -> Self:
        if self.wall:
            bounded(self.wall.position, 6.4, 4.57)
            if self.wall.time_us <= self.contact_us: raise ValueError("wall impact must follow contact")
        if self.landing:
            bounded(self.landing.position, 6.4, 9.75)
            if self.landing.time_us <= self.contact_us: raise ValueError("landing must follow contact")
            if self.wall and self.landing.time_us < self.wall.time_us: raise ValueError("first landing must follow front wall")
        return self

class WallCalibration(ReviewModel):
    points: list[Point] = Field(min_length=4, max_length=4)
    tin_height_m: Literal[0.43, 0.48] = 0.48

    @model_validator(mode="after")
    def validate_polygon(self) -> Self:
        p = self.points
        for point in p: bounded(point, 1, 1)
        cross = [(p[(i+1)%4][0]-p[i][0])*(p[(i+2)%4][1]-p[(i+1)%4][1]) - (p[(i+1)%4][1]-p[i][1])*(p[(i+2)%4][0]-p[(i+1)%4][0]) for i in range(4)]
        area = abs(sum(p[i][0]*p[(i+1)%4][1]-p[i][1]*p[(i+1)%4][0] for i in range(4)))/2
        if not (all(v < -1e-5 for v in cross) and area > .005 and p[0][0] < p[1][0] and p[3][0] < p[2][0] and p[0][1] > p[3][1] and p[1][1] > p[2][1]):
            raise ValueError("mark left floor, right floor, right service line, left service line in order")
        return self

class SaveShotReview(ReviewModel):
    expected_version: int = Field(ge=0)
    shots: list[ReviewShot] = Field(max_length=2000)
    wall_calibration: WallCalibration | None = None

    @field_validator("shots")
    @classmethod
    def unique_ids(cls, shots):
        if len({s.id for s in shots}) != len(shots): raise ValueError("shot IDs must be unique")
        return shots

class ShotReviewDocument(ReviewModel):
    version: int
    report_revision: int
    shots: list[ReviewShot]
    wall_calibration: WallCalibration | None

def _database(path: Path):
    if path.is_symlink(): raise ApiError("review_storage_invalid", "Review storage is not a regular database", 409)
    db = sqlite3.connect(path, timeout=10)
    db.execute("CREATE TABLE IF NOT EXISTS shot_reviews (match_id TEXT NOT NULL, report_revision INTEGER NOT NULL, version INTEGER NOT NULL, document TEXT NOT NULL, PRIMARY KEY(match_id, report_revision, version))")
    return db

def _read(db, match_id, revision):
    row = db.execute("SELECT document FROM shot_reviews WHERE match_id=? AND report_revision=? ORDER BY version DESC LIMIT 1", (match_id, revision)).fetchone()
    return ShotReviewDocument.model_validate_json(row[0]) if row else ShotReviewDocument(version=0, report_revision=revision, shots=[], wall_calibration=None)

def read_review(path: Path, match_id: str, revision: int) -> ShotReviewDocument:
    if not path.exists(): return ShotReviewDocument(version=0, report_revision=revision, shots=[], wall_calibration=None)
    db = _database(path)
    try: return _read(db, match_id, revision)
    finally: db.close()

def save_review(path: Path, match_id: str, revision: int, command: SaveShotReview) -> ShotReviewDocument:
    db = _database(path)
    try:
        with db:
            db.execute("BEGIN IMMEDIATE")
            current = _read(db, match_id, revision)
            if current.version != command.expected_version:
                raise ApiError("shot_review_conflict", "Shot review changed in another tab. Reload the saved review before trying again.", 409)
            saved = ShotReviewDocument(version=current.version+1, report_revision=revision, shots=command.shots, wall_calibration=command.wall_calibration)
            db.execute("INSERT INTO shot_reviews VALUES (?,?,?,?)", (match_id, revision, saved.version, saved.model_dump_json(by_alias=True)))
        return saved
    finally: db.close()
