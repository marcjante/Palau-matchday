"""
Punto de entrada de la API.

Ejecutar en local para desarrollo:
    uvicorn app.main:app --reload --port 8000

Documentación interactiva automática una vez arrancado:
    http://localhost:8000/docs
"""
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import Base, engine
from app.routers import teams, players, opponents, matches, events, stats, export

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="HC Palau - API de Estadísticas",
    description="Backend para registrar estadísticas de partidos de hockey patines por voz o manualmente, con gestión de varios equipos propios y rivales.",
    version="1.0.0",
)

# CORS abierto: el frontend se sirve desde otro dominio (GitHub Pages / app Android).
# Si se quiere restringir más adelante, cambiar allow_origins por la lista de dominios concretos.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(teams.router)
app.include_router(players.router)
app.include_router(opponents.router)
app.include_router(matches.router)
app.include_router(events.router)
app.include_router(stats.router)
app.include_router(export.router)


@app.get("/")
def root():
    return {"status": "ok", "service": "HC Palau Stats API"}


@app.get("/health")
def health():
    return {"status": "healthy"}
