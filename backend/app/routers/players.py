from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.database import get_db
from app.auth import verify_api_key
from app import models, schemas

router = APIRouter(tags=["players"], dependencies=[Depends(verify_api_key)])


@router.post("/teams/{team_id}/players", response_model=schemas.PlayerOut)
def add_player(team_id: int, player: schemas.PlayerCreate, db: Session = Depends(get_db)):
    team = db.query(models.Team).get(team_id)
    if not team:
        raise HTTPException(404, "Equipo no encontrado")

    exists = db.query(models.Player).filter(
        models.Player.team_id == team_id,
        models.Player.number == player.number,
        models.Player.active == True,  # noqa: E712
    ).first()
    if exists:
        raise HTTPException(400, f"Ya existe un jugador activo con el número {player.number} en este equipo")

    db_player = models.Player(team_id=team_id, number=player.number, name=player.name, is_gk=player.is_gk)
    db.add(db_player)
    db.commit()
    db.refresh(db_player)
    return db_player


@router.get("/teams/{team_id}/players", response_model=List[schemas.PlayerOut])
def list_players(team_id: int, include_inactive: bool = False, db: Session = Depends(get_db)):
    q = db.query(models.Player).filter(models.Player.team_id == team_id)
    if not include_inactive:
        q = q.filter(models.Player.active == True)  # noqa: E712
    return q.order_by(models.Player.number).all()


@router.delete("/players/{player_id}")
def deactivate_player(player_id: int, db: Session = Depends(get_db)):
    """No se borra físicamente (mantiene el histórico de eventos), se marca como inactivo."""
    player = db.query(models.Player).get(player_id)
    if not player:
        raise HTTPException(404, "Jugador no encontrado")
    player.active = False
    db.commit()
    return {"deactivated": True}


@router.patch("/players/{player_id}", response_model=schemas.PlayerOut)
def update_player(player_id: int, update: schemas.PlayerUpdate, db: Session = Depends(get_db)):
    """
    Edita datos de un jugador (número, nombre, si es portero/a) o lo
    reactiva tras haberlo dado de baja. No afecta al histórico de eventos
    ya registrados, que sigue apuntando al mismo jugador.
    """
    player = db.query(models.Player).get(player_id)
    if not player:
        raise HTTPException(404, "Jugador no encontrado")

    if update.number is not None and update.number != player.number:
        clash = db.query(models.Player).filter(
            models.Player.team_id == player.team_id,
            models.Player.number == update.number,
            models.Player.active == True,  # noqa: E712
            models.Player.id != player.id,
        ).first()
        if clash:
            raise HTTPException(400, f"Ya existe un jugador activo con el número {update.number} en este equipo")
        player.number = update.number

    if update.name is not None:
        player.name = update.name
    if update.is_gk is not None:
        player.is_gk = update.is_gk
    if update.active is not None:
        player.active = update.active

    db.commit()
    db.refresh(player)
    return player
