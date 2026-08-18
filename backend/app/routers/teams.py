from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.database import get_db
from app.auth import verify_api_key
from app import models, schemas

router = APIRouter(prefix="/teams", tags=["teams"], dependencies=[Depends(verify_api_key)])


@router.post("", response_model=schemas.TeamOut)
def create_team(team: schemas.TeamCreate, db: Session = Depends(get_db)):
    db_team = models.Team(name=team.name, category=team.category)
    db.add(db_team)
    db.commit()
    db.refresh(db_team)
    return db_team


@router.get("", response_model=List[schemas.TeamOut])
def list_teams(db: Session = Depends(get_db)):
    return db.query(models.Team).order_by(models.Team.name).all()


@router.get("/{team_id}", response_model=schemas.TeamOut)
def get_team(team_id: int, db: Session = Depends(get_db)):
    team = db.query(models.Team).get(team_id)
    if not team:
        raise HTTPException(404, "Equipo no encontrado")
    return team


@router.delete("/{team_id}")
def delete_team(team_id: int, db: Session = Depends(get_db)):
    team = db.query(models.Team).get(team_id)
    if not team:
        raise HTTPException(404, "Equipo no encontrado")
    db.delete(team)
    db.commit()
    return {"deleted": True}
