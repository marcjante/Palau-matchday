"""
Las estadísticas se calculan agregando los `deltas` guardados en cada
MatchEvent — no hay contadores redundantes que puedan desincronizarse.
Esto es lo que permite filtrar por temporada, por rival, o comparar entre
partidos sin tener que rediseñar el modelo de datos cada vez.
"""
from collections import defaultdict
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional

from app.database import get_db
from app.auth import get_current_user
from app import models
from app.voice_nlu import ACTION_LABELS

router = APIRouter(tags=["stats"], dependencies=[Depends(get_current_user)])


def _sum_deltas(events):
    totals = defaultdict(int)
    for ev in events:
        for key, val in (ev.deltas or {}).items():
            totals[key] += val
    return dict(totals)


def _derived_fields(totals: dict) -> dict:
    saves = totals.get("saves", 0)
    shots_faced = totals.get("shots_faced", 0)
    totals["save_percentage"] = round((saves / shots_faced) * 100, 1) if shots_faced else 0.0
    return totals


@router.get("/players/{player_id}/stats")
def player_stats(
    player_id: int,
    season: Optional[str] = None,
    opponent_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    player = db.query(models.Player).get(player_id)
    if not player:
        raise HTTPException(404, "Jugador no encontrado")

    q = db.query(models.MatchEvent).join(models.Match).filter(models.MatchEvent.player_id == player_id)
    if season:
        q = q.filter(models.Match.season == season)
    if opponent_id:
        q = q.filter(models.Match.opponent_id == opponent_id)
    events = q.all()

    totals = _derived_fields(_sum_deltas(events))
    return {
        "player_id": player.id,
        "number": player.number,
        "name": player.name,
        "is_gk": player.is_gk,
        "matches_with_events": len({e.match_id for e in events}),
        "totals": totals,
    }


@router.get("/teams/{team_id}/season-summary")
def team_season_summary(team_id: int, season: str = Query(...), db: Session = Depends(get_db)):
    team = db.query(models.Team).get(team_id)
    if not team:
        raise HTTPException(404, "Equipo no encontrado")

    players = db.query(models.Player).filter(models.Player.team_id == team_id).all()
    matches = db.query(models.Match).filter(models.Match.team_id == team_id, models.Match.season == season).all()
    match_ids = [m.id for m in matches]

    result = []
    for player in players:
        events = db.query(models.MatchEvent).filter(
            models.MatchEvent.player_id == player.id,
            models.MatchEvent.match_id.in_(match_ids) if match_ids else False,
        ).all()
        totals = _derived_fields(_sum_deltas(events))
        result.append({
            "player_id": player.id, "number": player.number, "name": player.name,
            "is_gk": player.is_gk, "totals": totals,
        })

    wins = sum(1 for m in matches if m.score_us > m.score_them)
    draws = sum(1 for m in matches if m.score_us == m.score_them)
    losses = sum(1 for m in matches if m.score_us < m.score_them)

    return {
        "team_id": team.id, "team_name": team.name, "category": team.category, "season": season,
        "matches_played": len(matches), "wins": wins, "draws": draws, "losses": losses,
        "goals_for": sum(m.score_us for m in matches), "goals_against": sum(m.score_them for m in matches),
        "players": result,
    }


@router.get("/opponents/{opponent_id}/history")
def opponent_history(opponent_id: int, team_id: int = Query(...), db: Session = Depends(get_db)):
    opponent = db.query(models.Opponent).get(opponent_id)
    if not opponent:
        raise HTTPException(404, "Rival no encontrado")

    matches = db.query(models.Match).filter(
        models.Match.opponent_id == opponent_id,
        models.Match.team_id == team_id,
    ).order_by(models.Match.date).all()

    wins = sum(1 for m in matches if m.score_us > m.score_them)
    draws = sum(1 for m in matches if m.score_us == m.score_them)
    losses = sum(1 for m in matches if m.score_us < m.score_them)

    return {
        "opponent_id": opponent.id, "opponent_name": opponent.name,
        "matches_played": len(matches), "wins": wins, "draws": draws, "losses": losses,
        "matches": [
            {
                "id": m.id, "season": m.season, "date": m.date,
                "score_us": m.score_us, "score_them": m.score_them, "status": m.status,
            } for m in matches
        ],
    }


@router.get("/players/{player_id}/evolution")
def player_evolution(player_id: int, season: Optional[str] = None, db: Session = Depends(get_db)):
    """
    Estadísticas del jugador partido a partido (no acumuladas), ordenadas
    cronológicamente, para poder ver su evolución a lo largo de la
    temporada — no solo el total, sino si mejora, empeora o se mantiene
    estable en cada estadística clave.
    """
    player = db.query(models.Player).get(player_id)
    if not player:
        raise HTTPException(404, "Jugador no encontrado")

    q = db.query(models.Match).filter(models.Match.team_id == player.team_id)
    if season:
        q = q.filter(models.Match.season == season)
    matches = q.order_by(models.Match.date).all()

    events = db.query(models.MatchEvent).filter(
        models.MatchEvent.player_id == player_id,
        models.MatchEvent.match_id.in_([m.id for m in matches]) if matches else False,
    ).all()
    events_by_match = defaultdict(list)
    for ev in events:
        events_by_match[ev.match_id].append(ev)

    # Solo se listan los partidos en los que el jugador tuvo alguna acción registrada
    match_series = []
    for m in matches:
        match_events = events_by_match.get(m.id, [])
        if not match_events:
            continue
        totals = _derived_fields(_sum_deltas(match_events))
        match_series.append({
            "match_id": m.id,
            "date": m.date,
            "opponent_name": m.opponent.name,
            "season": m.season,
            "totals": totals,
        })

    # Estadísticas clave según el rol, para detectar tendencia
    key_stats = ["saves", "goals_conceded", "save_percentage"] if player.is_gk else \
                ["goals", "assists", "shots_on_target", "recoveries", "losses"]

    trend = {}
    n = len(match_series)
    if n >= 4:
        half = n // 2
        first_half = match_series[:half]
        second_half = match_series[half:]
        for stat in key_stats:
            first_avg = sum(m["totals"].get(stat, 0) for m in first_half) / len(first_half)
            second_avg = sum(m["totals"].get(stat, 0) for m in second_half) / len(second_half)
            if first_avg == 0 and second_avg == 0:
                direction = "estable"
                change_pct = 0.0
            else:
                change_pct = round(((second_avg - first_avg) / first_avg) * 100, 1) if first_avg else 100.0
                # Para "goals_conceded" y "losses", subir es empeorar, no mejorar
                worse_if_up = stat in ("goals_conceded", "losses")
                if abs(change_pct) < 10:
                    direction = "estable"
                elif (change_pct > 0) != worse_if_up:
                    direction = "mejora"
                else:
                    direction = "empeora"
            trend[stat] = {
                "primera_mitad_promedio": round(first_avg, 2),
                "segunda_mitad_promedio": round(second_avg, 2),
                "cambio_pct": change_pct,
                "tendencia": direction,
            }
    else:
        trend = {"nota": "Se necesitan al menos 4 partidos con datos para calcular una tendencia fiable"}

    return {
        "player_id": player.id, "number": player.number, "name": player.name, "is_gk": player.is_gk,
        "matches_played": n,
        "matches": match_series,
        "trend": trend,
    }


@router.get("/matches/{match_id}/summary")
def match_summary(match_id: int, db: Session = Depends(get_db)):
    match = db.query(models.Match).get(match_id)
    if not match:
        raise HTTPException(404, "Partido no encontrado")

    players = db.query(models.Player).filter(models.Player.team_id == match.team_id).all()
    events = db.query(models.MatchEvent).filter(models.MatchEvent.match_id == match_id).all()

    events_by_player = defaultdict(list)
    for ev in events:
        events_by_player[ev.player_id].append(ev)

    players_out = []
    for p in players:
        totals = _derived_fields(_sum_deltas(events_by_player.get(p.id, [])))
        players_out.append({"player_id": p.id, "number": p.number, "name": p.name, "is_gk": p.is_gk, "totals": totals})

    return {
        "match_id": match.id, "season": match.season, "score_us": match.score_us, "score_them": match.score_them,
        "clock_seconds": match.clock_seconds, "status": match.status,
        "players": players_out,
        "events": [
            {
                "id": e.id, "player_id": e.player_id, "action_type": e.action_type,
                "label": ACTION_LABELS.get(e.action_type, e.action_type),
                "match_second": e.match_second, "raw_text": e.raw_text,
            } for e in sorted(events, key=lambda e: e.id)
        ],
    }
