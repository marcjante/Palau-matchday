from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional

from app.database import get_db
from app.auth import verify_api_key
from app import models, schemas

router = APIRouter(prefix="/matches", tags=["matches"], dependencies=[Depends(verify_api_key)])


@router.post("", response_model=schemas.MatchOut)
def create_match(match: schemas.MatchCreate, db: Session = Depends(get_db)):
    team = db.query(models.Team).get(match.team_id)
    if not team:
        raise HTTPException(404, "Equipo no encontrado")
    opponent = db.query(models.Opponent).get(match.opponent_id)
    if not opponent:
        raise HTTPException(404, "Rival no encontrado")

    db_match = models.Match(team_id=match.team_id, opponent_id=match.opponent_id, season=match.season)
    db.add(db_match)
    db.commit()
    db.refresh(db_match)
    return db_match


@router.get("", response_model=List[schemas.MatchOut])
def list_matches(
    team_id: Optional[int] = None,
    opponent_id: Optional[int] = None,
    season: Optional[str] = None,
    db: Session = Depends(get_db),
):
    q = db.query(models.Match)
    if team_id:
        q = q.filter(models.Match.team_id == team_id)
    if opponent_id:
        q = q.filter(models.Match.opponent_id == opponent_id)
    if season:
        q = q.filter(models.Match.season == season)
    return q.order_by(models.Match.date.desc()).all()


@router.get("/{match_id}", response_model=schemas.MatchOut)
def get_match(match_id: int, db: Session = Depends(get_db)):
    match = db.query(models.Match).get(match_id)
    if not match:
        raise HTTPException(404, "Partido no encontrado")
    return match


@router.patch("/{match_id}/clock", response_model=schemas.MatchOut)
def update_clock(match_id: int, update: schemas.MatchClockUpdate, db: Session = Depends(get_db)):
    match = db.query(models.Match).get(match_id)
    if not match:
        raise HTTPException(404, "Partido no encontrado")
    match.clock_seconds = update.clock_seconds
    if update.status:
        match.status = update.status
    db.commit()
    db.refresh(match)
    return match


@router.delete("/{match_id}")
def delete_match(match_id: int, db: Session = Depends(get_db)):
    match = db.query(models.Match).get(match_id)
    if not match:
        raise HTTPException(404, "Partido no encontrado")
    db.delete(match)
    db.commit()
    return {"deleted": True}
