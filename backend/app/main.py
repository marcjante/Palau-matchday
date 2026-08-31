#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
TBC IA - Clinical Evidence & Hybrid RAG Engine (v7.0 SOTA Enterprise)
=============================================================================
Incluye:
  1. Harvester Multi-Fuente: PubMed, Crossref, Europe PMC, OPENALEX (Impacto).
  2. SOTA RAG: Query Rewriting -> BM25+Dense -> RRF -> CrossEncoder -> MMR.
  3. Razonamiento: Extracción de claims y Detección de Contradicciones (NLI).
  4. Auditoría Académica: Generación nativa de .RIS para Zotero/EndNote.
"""

import os
import re
import sys
import json
import math
import time
import uuid
import logging
from enum import Enum
import numpy as np
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Dict, List, Set, Optional, Tuple, Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import xml.etree.ElementTree as ET

# --- FastAPI ---
from fastapi import FastAPI, HTTPException, Depends, Security, Query, status, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security.api_key import APIKeyHeader
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
import uvicorn

# --- SQLAlchemy ---
from sqlalchemy import (
    create_engine, Column, String, Integer, Float, Boolean, DateTime, Text,
    Enum as SQLEnum, ForeignKey, event
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship, Session

# --- IA Models ---
try:
    from sentence_transformers import SentenceTransformer, CrossEncoder
except ImportError:
    print("FATAL ERROR: Instala 'sentence-transformers', 'transformers' y 'torch' para ejecutar el motor SOTA.")
    sys.exit(1)

# ==============================================================================
# 1. CONFIGURACIÓN Y LOGGING
# ==============================================================================

API_SECRET_KEY = os.getenv("TBC_API_KEY", "tbc_ia_secret_v7")
NCBI_EMAIL = os.getenv("NCBI_EMAIL", "tbc_ia_research@domain.org")
NCBI_API_KEY = os.getenv("NCBI_API_KEY", "")

BASE_DIR = "tbc_knowledge_repository"
DB_PATH = os.path.join(BASE_DIR, "data", "tbc_clinical_v7.db")
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("TBC_SOTA_ENGINE")

http_session = requests.Session()
retries = Retry(total=5, backoff_factor=1.5, status_forcelist=[429, 500, 502, 503, 504])
http_session.mount("https://", HTTPAdapter(max_retries=retries))
http_session.mount("http://", HTTPAdapter(max_retries=retries))

# ==============================================================================
# 2. CAPA RELACIONAL & BASE DE DATOS (SQLITE WAL)
# ==============================================================================

engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})

@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()

SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

class RetrievalStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETRACTED = "RETRACTED"

class DocumentORM(Base):
    __tablename__ = "documents"
    id = Column(String(64), primary_key=True)
    doi = Column(String(128), unique=True, index=True)
    pmid = Column(String(32), unique=True, index=True)
    title = Column(Text, nullable=False)
    authors = Column(Text, nullable=False)
    year = Column(Integer, index=True)
    journal = Column(String(255))
    evidence_level = Column(String(64), index=True)

    topics = Column(Text)
    populations = Column(Text)
    drugs = Column(Text)

    # Nuevos campos OpenAlex
    citation_count = Column(Integer, default=0, index=True)
    openalex_concepts = Column(Text, nullable=True)

    rag_priority = Column(String(16))
    rag_score = Column(Float, default=0.0)
    retrieval_status = Column(SQLEnum(RetrievalStatus), default=RetrievalStatus.ACTIVE)

    chunks = relationship("ChunkORM", back_populates="document", cascade="all, delete-orphan")

class ChunkORM(Base):
    __tablename__ = "chunks"
    id = Column(String(64), primary_key=True)
    document_id = Column(String(64), ForeignKey("documents.id"))
    content = Column(Text, nullable=False)
    section_weight = Column(Float, default=1.0)
    is_guideline = Column(Boolean, default=False)
    document = relationship("DocumentORM", back_populates="chunks")

Base.metadata.create_all(bind=engine)

# ==============================================================================
# 3. GESTOR DE MODELOS IA
# ==============================================================================

class AIModels:
    def __init__(self):
        logger.info("Cargando Dense Bi-Encoder (BGE-Small)...")
        self.bi_encoder = SentenceTransformer("BAAI/bge-small-en-v1.5")
        logger.info("Cargando Reranker (CrossEncoder)...")
        self.reranker = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
        logger.info("Cargando NLI Contradiction Detector (DeBERTa-v3)...")
        self.nli_model = CrossEncoder("cross-encoder/nli-deberta-v3-small")

ai_models = AIModels()

# ==============================================================================
# 4. FUNCIONES DEL HARVESTER (PUBMED + OPENALEX + CROSSREF)
# ==============================================================================

def fetch_openalex_metrics(doi: str) -> dict:
    """Obtiene métricas de impacto (citas) y conceptos desde OpenAlex."""
    if not doi or doi == "NO DISPONIBLE":
        return {"cited_by_count": 0, "concepts": ""}

    url = f"https://api.openalex.org/works/https://doi.org/{doi}"
    try:
        r = http_session.get(url, headers={"User-Agent": f"mailto:{NCBI_EMAIL}"}, timeout=5)
        if r.status_code == 200:
            data = r.json()
            concepts = [c["display_name"] for c in data.get("concepts", []) if c.get("score", 0) > 0.6]
            return {
                "cited_by_count": data.get("cited_by_count", 0),
                "concepts": "; ".join(concepts)
            }
    except Exception as e:
        logger.warning(f"Fallo en OpenAlex para DOI {doi}: {e}")

    return {"cited_by_count": 0, "concepts": ""}

def compute_rag_scores(evidence_level: str, topics: str, year_val: int, citations: int) -> Tuple[str, float]:
    """Calcula el rag_score sumando evidencia metodológica + impacto bibliométrico."""
    weights = {"Clinical guideline": 1.0, "Meta-analysis": 0.95, "Systematic review": 0.90, "Randomized controlled trial": 0.85, "Clinical trial": 0.75, "Cohort study": 0.70, "Narrative review": 0.60}
    score = weights.get(evidence_level, 0.40)

    if year_val >= datetime.now().year - 5: score += 0.05

    # Bonificación OpenAlex (Impacto)
    if citations > 500: score += 0.08
    elif citations > 100: score += 0.04
    elif citations > 20: score += 0.02

    score = min(1.0, score)
    prio = "HIGH" if score >= 0.80 else ("MEDIUM" if score >= 0.60 else "LOW")
    return prio, round(score, 3)

# ==============================================================================
# 5. BM25 SPARSE RETRIEVER
# ==============================================================================

class BM25Retriever:
    def __init__(self, corpus: List[str]):
        self.k1 = 1.5
        self.b = 0.75
        self.corpus = [re.findall(r"\w+", doc.lower()) for doc in corpus]
        self.doc_len = [len(d) for d in self.corpus]
        self.avgdl = sum(self.doc_len) / max(len(self.doc_len), 1)
        self.df = {}
        for d in self.corpus:
            for term in set(d): self.df[term] = self.df.get(term, 0) + 1
        self.idf = {t: math.log(1 + (len(self.corpus) - f + 0.5) / (f + 0.5)) for t, f in self.df.items()}

    def get_scores(self, query: str) -> np.ndarray:
        q_tokens = re.findall(r"\w+", query.lower())
        scores = np.zeros(len(self.corpus))
        for idx, doc in enumerate(self.corpus):
            tf_dict = {t: doc.count(t) for t in set(q_tokens).intersection(doc)}
            for q in q_tokens:
                if q in tf_dict:
                    tf = tf_dict[q]
                    denom = tf + self.k1 * (1 - self.b + self.b * (self.doc_len[idx] / self.avgdl))
                    scores[idx] += self.idf.get(q, 0.1) * (tf * (self.k1 + 1)) / denom
        return scores

# ==============================================================================
# 6. SOTA RAG PIPELINE (THE 16 STEPS)
# ==============================================================================

DRUGS_DB = {"etambutol": "ethambutol", "emb": "ethambutol", "isoniazida": "isoniazid", "rifampicina": "rifampin", "bedaquilina": "bedaquiline"}
POP_DB = {"embarazo": "pregnancy", "niño": "pediatric", "pediatria": "pediatric", "vih": "hiv"}

class SOTARagPipeline:
    def __init__(self, db: Session):
        self.db = db
        self.chunks = []
        self.embeddings = np.array([])
        self.bm25 = None
        self._load_mock_data_if_empty()
        self._build_index()

    def _load_mock_data_if_empty(self):
        """Simula una sincronización previa con OpenAlex si la DB está vacía."""
        if self.db.query(DocumentORM).count() == 0:
            doc1 = DocumentORM(id="DOC1", doi="10.1093/cid/ciw376", title="WHO TB Guidelines 2022", authors="WHO", year=2022, journal="WHO", evidence_level="Clinical guideline", citation_count=850, openalex_concepts="Tuberculosis; Medicine", drugs="ethambutol", populations="adult")
            doc2 = DocumentORM(id="DOC2", doi="10.1056/NEJMoa2033400", title="Pediatric TB Management", authors="Smith J", year=2021, journal="NEJM", evidence_level="Randomized controlled trial", citation_count=120, openalex_concepts="Pediatrics; Infectious Diseases", drugs="isoniazid", populations="pediatric")
            self.db.add_all([doc1, doc2])
            self.db.commit()

            c1 = ChunkORM(id="C1", document_id="DOC1", content="Ethambutol can cause optic neuropathy. Monitor vision.", is_guideline=True, section_weight=2.0)
            c2 = ChunkORM(id="C2", document_id="DOC2", content="In pediatric TB, isoniazid dosage is 10mg/kg.", is_guideline=False, section_weight=1.0)
            self.db.add_all([c1, c2])
            self.db.commit()

    def _build_index(self):
        self.chunks = self.db.query(ChunkORM).join(DocumentORM).filter(DocumentORM.retrieval_status == RetrievalStatus.ACTIVE).all()
        if self.chunks:
            texts = [c.content for c in self.chunks]
            self.embeddings = ai_models.bi_encoder.encode(texts, convert_to_numpy=True)
            self.bm25 = BM25Retriever(texts)

    def analyze_query(self, query: str) -> Dict[str, Any]:
        q_lower = query.lower()
        alerts = []
        if re.search(r"\b(vision|ciego|borroso)\b.*?\b(etambutol|emb)\b", q_lower):
            alerts.append("ALERTA: Posible toxicidad ocular por etambutol. Requiere oftalmología.")

        intent = "ADVERSE_EFFECT" if "efecto" in q_lower or "vision" in q_lower else "GENERAL"
        detected_drugs = [en for es, en in DRUGS_DB.items() if es in q_lower]
        detected_pops = [en for es, en in POP_DB.items() if es in q_lower]
        expanded_q = f"{query} {' '.join(detected_drugs)} {' '.join(detected_pops)}"

        valid_doc_ids = set()
        if detected_pops:
            docs = self.db.query(DocumentORM.id).filter(DocumentORM.populations.ilike(f"%{detected_pops[0]}%")).all()
            valid_doc_ids = {d[0] for d in docs}

        return {"expanded_query": expanded_q, "intent": intent, "alerts": alerts, "filters": valid_doc_ids}

    def execute_retrieval(self, analysis: Dict[str, Any], top_k: int = 5) -> List[Dict[str, Any]]:
        if not self.chunks: return []
        expanded_q = analysis["expanded_query"]
        valid_docs = analysis["filters"]

        q_emb = ai_models.bi_encoder.encode([expanded_q], convert_to_numpy=True)[0]
        dense_scores = np.dot(self.embeddings, q_emb)
        sparse_scores = self.bm25.get_scores(expanded_q)

        if valid_docs:
            for i, c in enumerate(self.chunks):
                if c.document_id not in valid_docs:
                    dense_scores[i] = -100
                    sparse_scores[i] = 0

        dense_rank = {idx: r for r, idx in enumerate(np.argsort(dense_scores)[::-1][:30])}
        sparse_rank = {idx: r for r, idx in enumerate(np.argsort(sparse_scores)[::-1][:30])}

        rrf_scores = []
        all_candidates = set(dense_rank.keys()).union(set(sparse_rank.keys()))
        for idx in all_candidates:
            chunk = self.chunks[idx]
            # Exclusión dura: si hay filtro de población, un chunk de otro
            # documento no debe llegar ni al reranker, no basta con
            # penalizar su score (con pocos candidatos puede colarse igual).
            if valid_docs and chunk.document_id not in valid_docs:
                continue

            score = 0.0
            if idx in dense_rank: score += 1.0 / (60 + dense_rank[idx])
            if idx in sparse_rank: score += 1.0 / (60 + sparse_rank[idx])

            if chunk.is_guideline: score *= 1.5
            score *= chunk.section_weight
            # Bonificación OpenAlex en tiempo de Retrieval RRF
            score *= (1.0 + (chunk.document.citation_count / 10000))

            rrf_scores.append((idx, score))

        if not rrf_scores:
            return []

        top_indices = [idx for idx, _ in sorted(rrf_scores, key=lambda x: x[1], reverse=True)[:15]]

        candidate_texts = [self.chunks[i].content for i in top_indices]
        rerank_scores = ai_models.reranker.predict([[expanded_q, t] for t in candidate_texts])

        reranked_pairs = sorted(zip(top_indices, rerank_scores), key=lambda x: x[1], reverse=True)

        # Source Diversity (Heurística MMR rápida)
        final_results = []
        seen_docs = {}
        for idx, r_score in reranked_pairs:
            doc_id = self.chunks[idx].document_id
            if seen_docs.get(doc_id, 0) < 2:
                final_results.append({"chunk": self.chunks[idx], "rerank_score": float(r_score)})
                seen_docs[doc_id] = seen_docs.get(doc_id, 0) + 1
            if len(final_results) >= top_k: break

        return final_results

    def evaluate_reasoning(self, results: List[Dict[str, Any]]) -> Tuple[str, str]:
        if not results: return "INSUFFICIENT", "NO_EVIDENCE"
        contradiction_status = "SUPPORTED"

        # Contradiction Detection (NLI)
        if len(results) > 1:
            base_claim = results[0]["chunk"].content
            for i in range(1, len(results)):
                comparison_text = results[i]["chunk"].content
                nli_scores = ai_models.nli_model.predict([base_claim, comparison_text])
                if nli_scores[0] > 2.0: # Umbral de contradicción DeBERTa
                    contradiction_status = "CONFLICTING"
                    break

        top_score = results[0]["rerank_score"]
        has_guidelines = any(r["chunk"].is_guideline for r in results)

        confidence = "LOW"
        if top_score > 2.0 and has_guidelines and contradiction_status != "CONFLICTING":
            confidence = "HIGH"
        elif top_score > 0.0:
            confidence = "MODERATE"

        if contradiction_status == "CONFLICTING": confidence = "LOW"
        return confidence, contradiction_status

# ==============================================================================
# 7. EXPORTADOR BIBLIOGRÁFICO (.RIS) PARA ZOTERO/ENDNOTE
# ==============================================================================

def export_to_ris(documents: List[DocumentORM]) -> str:
    """Convierte una lista de DocumentORM al formato estándar .RIS"""
    ris_content = []
    for doc in documents:
        ris_content.append("TY  - JOUR")
        ris_content.append(f"T1  - {doc.title}")
        for author in doc.authors.split(", "):
            ris_content.append(f"AU  - {author.strip()}")
        ris_content.append(f"PY  - {doc.year}")
        ris_content.append(f"JO  - {doc.journal}")
        if doc.doi and doc.doi != "NO DISPONIBLE":
            ris_content.append(f"DO  - {doc.doi}")
        if doc.pmid:
            ris_content.append(f"C2  - PMID:{doc.pmid}")

        # Inyectar métricas de OpenAlex como notas
        ris_content.append(f"N1  - Cited By: {doc.citation_count} | Level: {doc.evidence_level}")
        if doc.openalex_concepts:
            ris_content.append(f"KW  - {doc.openalex_concepts}")

        if doc.chunks:
            ris_content.append(f"AB  - {doc.chunks[0].content}")

        ris_content.append("ER  - \n")
    return "\n".join(ris_content)

# ==============================================================================
# 8. FASTAPI LIFESPAN Y ENDPOINTS
# ==============================================================================

app_state = {}

@asynccontextmanager
async def lifespan(app: FastAPI):
    db = SessionLocal()
    app_state["pipeline"] = SOTARagPipeline(db)
    yield
    db.close()

app = FastAPI(title="TBC IA - SOTA Engine", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

def verify_api_key(api_key: str = Security(APIKeyHeader(name="X-API-Key", auto_error=False))):
    if api_key != API_SECRET_KEY: raise HTTPException(status_code=401, detail="Unauthorized")
    return api_key

# --- ENDPOINT 1: RAG EVIDENCE ---
class EvidenceResponse(BaseModel):
    query: str
    expanded_query: str
    intent: str
    alerts: List[str]
    confidence_level: str
    contradiction_status: str
    grounded_evidence: List[Dict[str, Any]]

@app.post("/v1/evidence", response_model=EvidenceResponse)
def get_evidence(query: str = Query(...), api_key: str = Depends(verify_api_key)):
    pipeline: SOTARagPipeline = app_state["pipeline"]
    analysis = pipeline.analyze_query(query)

    if analysis["alerts"]:
        return EvidenceResponse(query=query, expanded_query=analysis["expanded_query"], intent=analysis["intent"], alerts=analysis["alerts"], confidence_level="EMERGENCY_URGENT", contradiction_status="N/A", grounded_evidence=[])

    results = pipeline.execute_retrieval(analysis, top_k=5)
    confidence, contradiction = pipeline.evaluate_reasoning(results)

    packaged_evidence = [
        {"chunk_id": r["chunk"].id, "document_id": r["chunk"].document_id, "content": r["chunk"].content, "is_guideline": r["chunk"].is_guideline, "rerank_score": round(r["rerank_score"], 3), "citas_openalex": r["chunk"].document.citation_count} for r in results
    ]

    return EvidenceResponse(query=query, expanded_query=analysis["expanded_query"], intent=analysis["intent"], alerts=analysis["alerts"], confidence_level=confidence, contradiction_status=contradiction, grounded_evidence=packaged_evidence)

# --- ENDPOINT 2: AUDITORÍA CLÍNICA (.RIS EXPORT) ---
@app.get("/v1/admin/export/ris", response_class=PlainTextResponse)
def export_corpus_ris(topic: Optional[str] = None, api_key: str = Depends(verify_api_key), db: Session = Depends(get_db)):
    """Exporta el corpus validado a Zotero/EndNote enriquecido con métricas OpenAlex."""
    query = db.query(DocumentORM).filter(DocumentORM.retrieval_status == RetrievalStatus.ACTIVE)
    if topic:
        query = query.filter(DocumentORM.topics.ilike(f"%{topic}%"))

    docs = query.all()
    ris_data = export_to_ris(docs)

    filename = f"TBC_IA_Corpus_{datetime.now().strftime('%Y%m%d')}.ris"
    return PlainTextResponse(content=ris_data, headers={"Content-Disposition": f"attachment; filename={filename}"})

# ==============================================================================
# 9. VERIFICACIÓN DE FIDELIDAD (GROUNDEDNESS) — agosto 2026
# ==============================================================================
# Detecta frases de una respuesta ya generada que no están respaldadas por
# ninguna de las fuentes recuperadas (el modelo "rellena" con una afirmación
# no verificada, sin anunciarlo con ninguna frase reconocible — por eso los
# guardrails basados en frases fijas de TBC-AI, LEAK_PATTERNS/REFUSAL_PATTERNS
# en backend/safety.py, no lo detectan). Reutiliza el mismo CrossEncoder NLI
# ya cargado para la detección de contradicciones entre fuentes.
#
# AVISO IMPORTANTE: el umbral de "respaldado" (ENTAILMENT_THRESHOLD) no se
# ha podido calibrar contra casos reales en el entorno donde se escribió este
# código (sin acceso a los modelos de HuggingFace desde aquí). El orden de
# las 3 etiquetas del modelo (contradiction/entailment/neutral) se asume
# igual al ya usado en evaluate_reasoning() de este mismo archivo (índice 0 =
# contradicción), consistente con la configuración pública del modelo en
# HuggingFace, pero NO se ha verificado en ejecución real. Antes de confiar
# en los resultados, imprime los scores crudos (endpoint con debug=true)
# para 2-3 frases donde ya sabes si están respaldadas o no, y ajusta el
# umbral si hace falta.

ENTAILMENT_THRESHOLD = 0.5  # sobre probabilidad softmax, no sobre el logit crudo

SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def split_into_sentences(text: str) -> List[str]:
    """Trocea en frases, descartando fragmentos triviales (viñetas sueltas,
    saludos cortos) que no aportan una afirmación verificable."""
    raw_sentences = SENTENCE_SPLIT_RE.split(text.replace("\n", " "))
    sentences = []
    for s in raw_sentences:
        s = s.strip().lstrip("*-• ").strip()
        if len(s) >= 20:  # descarta fragmentos demasiado cortos para ser una afirmación verificable
            sentences.append(s)
    return sentences


def softmax(scores) -> List[float]:
    exp_scores = np.exp(np.array(scores) - np.max(scores))
    return (exp_scores / exp_scores.sum()).tolist()


def check_sentence_grounded(sentence: str, sources: List[str], debug: bool = False) -> Dict[str, Any]:
    """Comprueba una frase contra todas las fuentes, se queda con la fuente
    que mejor la respalda (mayor probabilidad de 'entailment')."""
    best_entailment = 0.0
    best_source_idx = None
    debug_per_source = []
    for idx, source in enumerate(sources):
        raw_scores = ai_models.nli_model.predict([source, sentence])
        probs = softmax(raw_scores)
        entailment_prob = probs[1]  # índice 1 = entailment, ver aviso arriba
        if debug:
            debug_per_source.append({
                "source_index": idx,
                "raw_scores": [float(x) for x in raw_scores],
                "probs": [round(float(p), 3) for p in probs],
            })
        if entailment_prob > best_entailment:
            best_entailment = entailment_prob
            best_source_idx = idx

    result = {
        "sentence": sentence,
        "grounded": best_entailment >= ENTAILMENT_THRESHOLD,
        "best_entailment_prob": round(best_entailment, 3),
        "best_source_index": best_source_idx,
    }
    if debug:
        result["debug_per_source"] = debug_per_source
    return result


class GroundednessRequest(BaseModel):
    response_text: str
    sources: List[str]
    debug: bool = False


class GroundednessResponse(BaseModel):
    flags: List[Dict[str, Any]]
    sentences_checked: int
    sentences_ungrounded: int
    all_results: Optional[List[Dict[str, Any]]] = None


@app.post("/v1/verify_groundedness", response_model=GroundednessResponse)
def verify_groundedness(payload: GroundednessRequest, api_key: str = Depends(verify_api_key)):
    """Recibe una respuesta ya generada por el LLM y las fuentes usadas para
    generarla; devuelve, frase por frase, si el modelo NLI encuentra alguna
    fuente que la respalde. NO decide nada sobre la respuesta final — solo
    informa, para que TBC-AI (u otro sistema) decida qué hacer con eso.

    Con debug=true en el body, devuelve tambien los 3 scores crudos (softmax)
    por cada par frase-fuente en 'all_results', para calibrar el indice de
    la etiqueta 'entailment' contra casos conocidos antes de confiar en la
    clasificacion grounded/ungrounded."""
    sentences = split_into_sentences(payload.response_text)
    if not sentences or not payload.sources:
        return GroundednessResponse(flags=[], sentences_checked=0, sentences_ungrounded=0)

    results = [check_sentence_grounded(s, payload.sources, debug=payload.debug) for s in sentences]
    ungrounded = [r for r in results if not r["grounded"]]

    return GroundednessResponse(
        flags=ungrounded,
        sentences_checked=len(results),
        sentences_ungrounded=len(ungrounded),
        all_results=results if payload.debug else None,
    )


if __name__ == "__main__":
    print("Iniciando TBC IA SOTA Engine en http://127.0.0.1:8000")
    uvicorn.run(app, host="127.0.0.1", port=8000)
