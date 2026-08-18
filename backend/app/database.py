"""
Configuración de la base de datos.
Por defecto usa SQLite en un archivo local (hcpalau.db), suficiente para el
uso de un club. Si en el futuro se necesita Postgres (por ejemplo al
desplegar en Railway/Render con su base de datos gestionada), basta con
definir la variable de entorno DATABASE_URL apuntando a la cadena de
conexión de Postgres — no hay que tocar nada más del código.
"""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./hcpalau.db")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
