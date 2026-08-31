from datetime import datetime
from typing import Optional, Dict
from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------
class RegisterIn(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=6)
    registration_code: str


class LoginIn(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


# ---------------------------------------------------------------------
# Team
# ---------------------------------------------------------------------
class TeamCreate(BaseModel):
    name: str
    category: Optional[str] = None


class TeamOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    category: Optional[str] = None


# ---------------------------------------------------------------------
# Player
# ---------------------------------------------------------------------
class PlayerCreate(BaseModel):
    number: str
    name: str
    is_gk: bool = False


class PlayerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    team_id: int
    number: str
    name: str
    is_gk: bool
    active: bool


class PlayerUpdate(BaseModel):
    number: Optional[str] = None
    name: Optional[str] = None
    is_gk: Optional[bool] = None
    active: Optional[bool] = None


# ---------------------------------------------------------------------
# Opponent
# ---------------------------------------------------------------------
class OpponentCreate(BaseModel):
    name: str


class OpponentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str


# ---------------------------------------------------------------------
# Match
# ---------------------------------------------------------------------
class MatchCreate(BaseModel):
    team_id: int
    opponent_id: int
    season: str


class MatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    team_id: int
    opponent_id: int
    season: str
    date: datetime
    score_us: int
    score_them: int
    clock_seconds: int
    status: str
    active_player_id: Optional[int] = None


class MatchClockUpdate(BaseModel):
    clock_seconds: int
    status: Optional[str] = None


# ---------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------
class ManualEventCreate(BaseModel):
    player_id: int
    action_type: str
    zone: Optional[str] = None  # p.ej. "A1".."C3", solo relevante en acciones de tiro/parada/gol


class VoiceCommandIn(BaseModel):
    text: str


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    match_id: int
    player_id: int
    action_type: str
    match_second: int
    wall_time: datetime
    raw_text: Optional[str] = None
    zone: Optional[str] = None
    deltas: Dict[str, int]


class VoiceCommandOut(BaseModel):
    status: str  # "registered" | "undone" | "corrected" | "context_set" | "not_understood" | "help" | "error"
    message: str
    event: Optional[EventOut] = None
    active_player_id: Optional[int] = None
    active_player_label: Optional[str] = None  # p.ej. "7 - Pol", para mostrar en pantalla
    heard_text: Optional[str] = None  # lo que se entendió (texto enviado, o transcripción de Whisper)


class EventCorrection(BaseModel):
    player_id: Optional[int] = None
    action_type: Optional[str] = None
