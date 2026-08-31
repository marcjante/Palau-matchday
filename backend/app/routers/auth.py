from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app import models, schemas
from app.auth import hash_password, verify_password, create_access_token, REGISTRATION_CODE

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=schemas.TokenOut)
def register(payload: schemas.RegisterIn, db: Session = Depends(get_db)):
    if not REGISTRATION_CODE:
        raise HTTPException(500, "El servidor no tiene REGISTRATION_CODE configurado — no se pueden crear cuentas nuevas todavía.")
    if payload.registration_code != REGISTRATION_CODE:
        raise HTTPException(403, "Código de registro incorrecto.")

    existing = db.query(models.User).filter(models.User.username == payload.username).first()
    if existing:
        raise HTTPException(400, f"El usuario '{payload.username}' ya existe. Prueba a iniciar sesión en su lugar.")

    user = models.User(username=payload.username, hashed_password=hash_password(payload.password))
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token(user.id, user.username)
    return schemas.TokenOut(access_token=token, user=user)


@router.post("/login", response_model=schemas.TokenOut)
def login(payload: schemas.LoginIn, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.username == payload.username).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(401, "Usuario o contraseña incorrectos.")

    token = create_access_token(user.id, user.username)
    return schemas.TokenOut(access_token=token, user=user)
