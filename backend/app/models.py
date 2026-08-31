"""
Modelo relacional.

Team       -> plantilla propia (puede haber varias: infantil, juvenil, senior...)
Player     -> jugador perteneciente a un Team, con número y si es portero/a
Opponent   -> equipo rival (independiente de Team, se reutiliza entre temporadas)
Match      -> un partido concreto: Team propio vs Opponent, con temporada
MatchEvent -> cada acción registrada durante un partido (gol, parada, etc.)

Las estadísticas NO se guardan como contadores en Player: se calculan
agregando MatchEvent.deltas bajo demanda (ver stats.py). Esto es lo que
permite sacar estadísticas por temporada, por rival, o comparativas entre
partidos sin tener que mantener contadores duplicados en varias tablas.
"""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, ForeignKey, Text, JSON
)
from sqlalchemy.orm import relationship
from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, nullable=False, unique=True, index=True)
    hashed_password = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Team(Base):
    __tablename__ = "teams"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    category = Column(String, nullable=True)  # p.ej. "Infantil", "Juvenil", "Senior"
    created_at = Column(DateTime, default=datetime.utcnow)

    players = relationship("Player", back_populates="team", cascade="all, delete-orphan")
    matches = relationship("Match", back_populates="team", cascade="all, delete-orphan")


class Player(Base):
    __tablename__ = "players"

    id = Column(Integer, primary_key=True, index=True)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    number = Column(String, nullable=False)
    name = Column(String, nullable=False)
    is_gk = Column(Boolean, default=False)
    active = Column(Boolean, default=True)  # permite dar de baja sin borrar histórico

    team = relationship("Team", back_populates="players")
    events = relationship("MatchEvent", back_populates="player")


class Opponent(Base):
    __tablename__ = "opponents"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, unique=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    matches = relationship("Match", back_populates="opponent")


class Match(Base):
    __tablename__ = "matches"

    id = Column(Integer, primary_key=True, index=True)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    opponent_id = Column(Integer, ForeignKey("opponents.id"), nullable=False)
    season = Column(String, nullable=False)  # p.ej. "2025-2026"
    date = Column(DateTime, default=datetime.utcnow)
    score_us = Column(Integer, default=0)
    score_them = Column(Integer, default=0)
    clock_seconds = Column(Integer, default=0)
    status = Column(String, default="active")  # active | finished
    active_player_id = Column(Integer, ForeignKey("players.id"), nullable=True)  # jugador "pegado" por voz

    team = relationship("Team", back_populates="matches")
    opponent = relationship("Opponent", back_populates="matches")
    events = relationship("MatchEvent", back_populates="match", cascade="all, delete-orphan", order_by="MatchEvent.id")


class MatchEvent(Base):
    __tablename__ = "match_events"

    id = Column(Integer, primary_key=True, index=True)
    match_id = Column(Integer, ForeignKey("matches.id"), nullable=False)
    player_id = Column(Integer, ForeignKey("players.id"), nullable=False)
    action_type = Column(String, nullable=False)
    match_second = Column(Integer, default=0)
    wall_time = Column(DateTime, default=datetime.utcnow)
    raw_text = Column(Text, nullable=True)
    deltas = Column(JSON, nullable=False)  # {"goals": 1, "shots": 1, ...} para poder revertir/corregir

    match = relationship("Match", back_populates="events")
    player = relationship("Player", back_populates="events")
