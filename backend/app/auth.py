"""
Autenticación por usuario y contraseña, con tokens JWT.

Sustituye a la API key compartida: ahora cada entrenador tiene su propia
cuenta. Nadie ve ninguna clave mirando el código fuente del frontend —
lo único que viaja es un token temporal que se consigue haciendo login.

Registro de cuentas nuevas: para que no cualquiera con la URL pueda
crearse una cuenta y acceder a los datos del equipo, crear un usuario
nuevo exige conocer REGISTRATION_CODE (una clave definida por el
administrador, pensada para compartirla solo con el cuerpo técnico, una
vez, para que cada uno se cree su cuenta — no se usa en el día a día,
solo al darse de alta).
"""
import os
import bcrypt
import jwt
from datetime import datetime, timedelta, timezone
from fastapi import Header, HTTPException, status, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app import models

JWT_SECRET = os.getenv("JWT_SECRET", "")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_DAYS = 30  # sesión larga a propósito: uso diario en el pabellón, sin re-logins constantes

REGISTRATION_CODE = os.getenv("REGISTRATION_CODE", "")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(user_id: int, username: str) -> str:
    if not JWT_SECRET:
        raise RuntimeError("JWT_SECRET no está configurado en el servidor")
    payload = {
        "sub": str(user_id),
        "username": username,
        "exp": datetime.now(timezone.utc) + timedelta(days=JWT_EXPIRE_DAYS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def get_current_user(
    authorization: str = Header(default=""),
    db: Session = Depends(get_db),
) -> models.User:
    """
    Dependencia usada en todos los endpoints protegidos. Exige la cabecera
    'Authorization: Bearer <token>' con un JWT válido obtenido en /auth/login.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Falta la cabecera Authorization con el token (Bearer <token>). Inicia sesión en /auth/login.",
        )
    token = authorization[len("Bearer "):]

    if not JWT_SECRET:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="El servidor no tiene JWT_SECRET configurado.",
        )

    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sesión caducada, vuelve a iniciar sesión.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido.")

    user = db.query(models.User).get(int(payload["sub"]))
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="El usuario de este token ya no existe.")
    return user
