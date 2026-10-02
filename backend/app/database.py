"""
Configuración de la base de datos.
Por defecto usa SQLite en un archivo local (hcpalau.db), suficiente para el
uso de un club. Si en el futuro se necesita Postgres (por ejemplo al
desplegar en Railway/Render con su base de datos gestionada), basta con
definir la variable de entorno DATABASE_URL apuntando a la cadena de
conexión de Postgres — no hay que tocar nada más del código.
"""
import logging
import os
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./hcpalau.db")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

logger = logging.getLogger(__name__)


def add_missing_columns():
    """
    create_all() crea las tablas que faltan pero no toca las que ya existen.
    Cuando se añade una columna a un modelo (p.ej. MatchEvent.zone), una base
    de datos ya desplegada se quedaría sin ella y fallarían las consultas.
    Esto añade con ALTER TABLE las columnas que falten, solo si admiten NULL
    (las filas existentes no tendrían valor para una columna obligatoria).
    """
    inspector = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not inspector.has_table(table.name):
                continue
            existing = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing:
                    continue
                if not column.nullable:
                    logger.warning("Columna obligatoria %s.%s sin migrar: requiere migración manual", table.name, column.name)
                    continue
                column_type = column.type.compile(dialect=engine.dialect)
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {column_type}'))
                logger.info("Añadida columna %s.%s", table.name, column.name)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
