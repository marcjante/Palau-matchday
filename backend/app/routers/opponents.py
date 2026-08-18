from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.database import get_db
from app.auth import verify_api_key
from app import models, schemas

router = APIRouter(prefix="/opponents", tags=["opponents"], dependencies=[Depends(verify_api_key)])


@router.post("", response_model=schemas.OpponentOut)
def create_opponent(opponent: schemas.OpponentCreate, db: Session = Depends(get_db)):
    existing = db.query(models.Opponent).filter(models.Opponent.name == opponent.name).first()
    if existing:
        return existing
    db_opp = models.Opponent(name=opponent.name)
    db.add(db_opp)
    db.commit()
    db.refresh(db_opp)
    return db_opp


@router.get("", response_model=List[schemas.OpponentOut])
def list_opponents(db: Session = Depends(get_db)):
    return db.query(models.Opponent).order_by(models.Opponent.name).all()


@router.get("/{opponent_id}", response_model=schemas.OpponentOut)
def get_opponent(opponent_id: int, db: Session = Depends(get_db)):
    opp = db.query(models.Opponent).get(opponent_id)
    if not opp:
        raise HTTPException(404, "Rival no encontrado")
    return opp
