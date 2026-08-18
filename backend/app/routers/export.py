import csv
import io
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth import verify_api_key
from app import models
from app.routers.stats import match_summary

router = APIRouter(prefix="/matches", tags=["export"], dependencies=[Depends(verify_api_key)])


OUTFIELD_COLUMNS = ["shots", "shots_on_target", "shots_off", "goals", "assists", "recoveries",
                     "losses", "interceptions", "fouls_committed", "fouls_received", "yellow_cards",
                     "red_cards", "defensive_actions"]
GK_COLUMNS = ["shots_faced", "saves", "goals_conceded", "save_percentage", "penalties_faced",
              "penalties_saved", "exits_good", "exits_bad", "distributions"]


@router.get("/{match_id}/export/csv")
def export_csv(match_id: int, db: Session = Depends(get_db)):
    match = db.query(models.Match).get(match_id)
    if not match:
        raise HTTPException(404, "Partido no encontrado")
    summary = match_summary(match_id, db)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Partido vs", match.opponent.name, "Resultado", f"{match.score_us}-{match.score_them}", "Temporada", match.season])
    writer.writerow([])

    writer.writerow(["JUGADORES DE CAMPO"])
    writer.writerow(["Nº", "Nombre"] + OUTFIELD_COLUMNS)
    for p in summary["players"]:
        if p["is_gk"]:
            continue
        writer.writerow([p["number"], p["name"]] + [p["totals"].get(c, 0) for c in OUTFIELD_COLUMNS])

    writer.writerow([])
    writer.writerow(["PORTERO/A"])
    writer.writerow(["Nº", "Nombre"] + GK_COLUMNS)
    for p in summary["players"]:
        if not p["is_gk"]:
            continue
        writer.writerow([p["number"], p["name"]] + [p["totals"].get(c, 0) for c in GK_COLUMNS])

    writer.writerow([])
    writer.writerow(["HISTORIAL"])
    writer.writerow(["Segundo", "Jugador", "Acción", "Texto reconocido"])
    for e in summary["events"]:
        player = next((p for p in summary["players"] if p["player_id"] == e["player_id"]), None)
        writer.writerow([e["match_second"], f"{player['number']} - {player['name']}" if player else "?", e["label"], e["raw_text"]])

    buf.seek(0)
    filename = f"estadisticas_{match.opponent.name}_{match.date.date()}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{match_id}/export/pdf")
def export_pdf(match_id: int, db: Session = Depends(get_db)):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    match = db.query(models.Match).get(match_id)
    if not match:
        raise HTTPException(404, "Partido no encontrado")
    summary = match_summary(match_id, db)

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4
    y = height - 50

    c.setFont("Helvetica-Bold", 16)
    c.drawCentredString(width / 2, y, "INFORME DE ESTADÍSTICAS")
    y -= 20
    c.setFont("Helvetica", 10)
    c.drawCentredString(width / 2, y, f"vs {match.opponent.name} | {match.score_us}-{match.score_them} | Temporada {match.season}")
    y -= 30

    c.setFont("Helvetica-Bold", 12)
    c.drawString(40, y, "JUGADORES")
    y -= 18
    c.setFont("Helvetica", 8)
    for p in summary["players"]:
        if p["is_gk"]:
            continue
        t = p["totals"]
        line = f"{p['number']} {p['name']} — Goles:{t.get('goals',0)} Asist:{t.get('assists',0)} Tiros:{t.get('shots',0)} Rec:{t.get('recoveries',0)} Perd:{t.get('losses',0)}"
        c.drawString(40, y, line)
        y -= 14
        if y < 60:
            c.showPage()
            y = height - 50
            c.setFont("Helvetica", 8)

    y -= 10
    c.setFont("Helvetica-Bold", 12)
    c.drawString(40, y, "PORTERO/A")
    y -= 18
    c.setFont("Helvetica", 9)
    for p in summary["players"]:
        if not p["is_gk"]:
            continue
        t = p["totals"]
        c.drawString(40, y, f"{p['number']} {p['name']} — Paradas:{t.get('saves',0)} Recibidos:{t.get('shots_faced',0)} Goles encajados:{t.get('goals_conceded',0)} %Paradas:{t.get('save_percentage',0)}")
        y -= 14

    y -= 20
    c.setFont("Helvetica-Bold", 12)
    c.drawString(40, y, "HISTORIAL")
    y -= 16
    c.setFont("Helvetica", 7)
    for e in summary["events"]:
        player = next((p for p in summary["players"] if p["player_id"] == e["player_id"]), None)
        c.drawString(40, y, f"[{e['match_second']}s] {player['number'] if player else '?'} {player['name'] if player else ''} — {e['label']}")
        y -= 11
        if y < 40:
            c.showPage()
            y = height - 50
            c.setFont("Helvetica", 7)

    c.save()
    buf.seek(0)
    filename = f"informe_{match.opponent.name}_{match.date.date()}.pdf"
    return StreamingResponse(
        buf, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
