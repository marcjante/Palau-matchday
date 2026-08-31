from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from typing import List

from app.database import get_db
from app.auth import get_current_user
from app import models, schemas
from app.voice_nlu import interpret_command, ACTION_DELTAS, ACTION_LABELS
from app.transcribe import transcribe_audio_bytes

router = APIRouter(tags=["events"], dependencies=[Depends(get_current_user)])


# ---------------------------------------------------------------------
# Helpers internos (compartidos entre registro manual y comandos de voz)
# ---------------------------------------------------------------------
def _apply_score_delta(match: models.Match, action_type: str, sign: int):
    if action_type == "goal":
        match.score_us = max(0, match.score_us + sign)
    elif action_type in ("gk_goal_conceded", "gk_penalty_conceded"):
        match.score_them = max(0, match.score_them + sign)


def _register_event(db: Session, match: models.Match, player: models.Player, action_type: str, raw_text: str):
    if action_type not in ACTION_DELTAS:
        raise HTTPException(400, f"Acción desconocida: {action_type}")

    is_gk_action = action_type.startswith("gk_")
    if is_gk_action and not player.is_gk:
        raise HTTPException(400, f"{player.name} no está marcado como portero/a")
    if not is_gk_action and player.is_gk:
        raise HTTPException(400, f"{player.name} es portero/a, usa una acción de portería")

    deltas = ACTION_DELTAS[action_type]
    event = models.MatchEvent(
        match_id=match.id,
        player_id=player.id,
        action_type=action_type,
        match_second=match.clock_seconds,
        raw_text=raw_text,
        deltas=deltas,
    )
    _apply_score_delta(match, action_type, +1)
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def _revert_event(db: Session, event: models.MatchEvent):
    match = db.query(models.Match).get(event.match_id)
    _apply_score_delta(match, event.action_type, -1)
    db.commit()


def _find_player_by_number(db: Session, team_id: int, number: str) -> models.Player:
    return db.query(models.Player).filter(
        models.Player.team_id == team_id,
        models.Player.number == number,
        models.Player.active == True,  # noqa: E712
    ).first()


def _find_goalkeeper(db: Session, team_id: int) -> models.Player:
    return db.query(models.Player).filter(
        models.Player.team_id == team_id,
        models.Player.is_gk == True,  # noqa: E712
        models.Player.active == True,  # noqa: E712
    ).first()


def _get_match_or_404(db: Session, match_id: int) -> models.Match:
    match = db.query(models.Match).get(match_id)
    if not match:
        raise HTTPException(404, "Partido no encontrado")
    return match


# ---------------------------------------------------------------------
# Registro manual (botones en la interfaz)
# ---------------------------------------------------------------------
@router.post("/matches/{match_id}/events", response_model=schemas.EventOut)
def register_manual_event(match_id: int, payload: schemas.ManualEventCreate, db: Session = Depends(get_db)):
    match = _get_match_or_404(db, match_id)
    player = db.query(models.Player).get(payload.player_id)
    if not player or player.team_id != match.team_id:
        raise HTTPException(404, "Jugador no encontrado en este equipo")
    return _register_event(db, match, player, payload.action_type, f"(manual) {ACTION_LABELS.get(payload.action_type, payload.action_type)}")


@router.get("/matches/{match_id}/events", response_model=List[schemas.EventOut])
def list_events(match_id: int, db: Session = Depends(get_db)):
    _get_match_or_404(db, match_id)
    return db.query(models.MatchEvent).filter(models.MatchEvent.match_id == match_id).order_by(models.MatchEvent.id).all()


@router.delete("/events/{event_id}")
def delete_event(event_id: int, db: Session = Depends(get_db)):
    event = db.query(models.MatchEvent).get(event_id)
    if not event:
        raise HTTPException(404, "Evento no encontrado")
    _revert_event(db, event)
    db.delete(event)
    db.commit()
    return {"deleted": True}


@router.patch("/events/{event_id}", response_model=schemas.EventOut)
def correct_event(event_id: int, correction: schemas.EventCorrection, db: Session = Depends(get_db)):
    """Permite corregir manualmente el jugador y/o el tipo de una acción del historial."""
    event = db.query(models.MatchEvent).get(event_id)
    if not event:
        raise HTTPException(404, "Evento no encontrado")
    match = db.query(models.Match).get(event.match_id)

    _revert_event(db, event)

    if correction.player_id is not None:
        new_player = db.query(models.Player).get(correction.player_id)
        if not new_player or new_player.team_id != match.team_id:
            raise HTTPException(404, "Jugador no encontrado en este equipo")
        event.player_id = new_player.id

    if correction.action_type is not None:
        if correction.action_type not in ACTION_DELTAS:
            raise HTTPException(400, "Tipo de acción no reconocido")
        event.action_type = correction.action_type
        event.deltas = ACTION_DELTAS[correction.action_type]

    _apply_score_delta(match, event.action_type, +1)
    db.commit()
    db.refresh(event)
    return event


@router.post("/matches/{match_id}/undo-last", response_model=schemas.VoiceCommandOut)
def undo_last(match_id: int, db: Session = Depends(get_db)):
    match = _get_match_or_404(db, match_id)
    last_event = db.query(models.MatchEvent).filter(
        models.MatchEvent.match_id == match_id
    ).order_by(models.MatchEvent.id.desc()).first()

    if not last_event:
        return schemas.VoiceCommandOut(status="error", message="No hay acciones para deshacer")

    _revert_event(db, last_event)
    label = f"{last_event.player.number} {last_event.player.name} — {ACTION_LABELS.get(last_event.action_type)}"
    db.delete(last_event)
    db.commit()
    return schemas.VoiceCommandOut(status="undone", message=f"Acción eliminada: {label}")


# ---------------------------------------------------------------------
# Comando de voz: el texto ya transcrito se interpreta y ejecuta aquí
# ---------------------------------------------------------------------
def _active_player_label(player: models.Player) -> str:
    return f"{player.number} - {player.name}"


def _get_active_context(db: Session, match: models.Match):
    """Devuelve (player_or_None, is_gk_or_None) del contexto activo guardado en el partido."""
    if not match.active_player_id:
        return None, None
    player = db.query(models.Player).get(match.active_player_id)
    if not player:
        return None, None
    return player, player.is_gk


def _execute_result(db: Session, match: models.Match, active_player, result, heard_text: str) -> schemas.VoiceCommandOut:
    """
    Ejecuta el resultado ya interpretado de un comando (venga de texto
    tecleado/enviado directamente o de una transcripción de audio) contra
    la base de datos. Compartido entre /voice-command y /voice-audio para
    no duplicar la lógica de negocio.
    """
    match_id = match.id

    if result.kind == "help":
        return schemas.VoiceCommandOut(
            status="help", heard_text=heard_text,
            message='Ataque (por defecto): "jugador 5 gol" o "numero 5 parado". '
                    'Defensa (solo si dices "portero"/"portera"): "portero parada". '
                    'Una vez dicho "jugador 5" o "portero", puedes seguir solo con la acción: "gol", "pierde", "recupera"... '
                    'Control: "deshacer", "elimina el ultimo gol del jugador 5", '
                    '"cambiar la ultima accion a asistencia", "corregir jugador 8 por jugador 6".',
        )

    if result.kind == "not_understood":
        return schemas.VoiceCommandOut(
            status="not_understood", heard_text=heard_text,
            message=f'No he identificado al jugador ni la acción en: "{result.data.get("raw_text", heard_text)}"',
            active_player_id=active_player.id if active_player else None,
            active_player_label=_active_player_label(active_player) if active_player else None,
        )

    if result.kind == "undo":
        out = undo_last(match_id, db)
        out.heard_text = heard_text
        return out

    if result.kind == "set_context":
        if result.data.get("is_gk"):
            gk = _find_goalkeeper(db, match.team_id)
            if not gk:
                return schemas.VoiceCommandOut(status="error", heard_text=heard_text, message="No hay ningún portero/a en la plantilla de este equipo")
            match.active_player_id = gk.id
            db.commit()
            return schemas.VoiceCommandOut(
                status="context_set", heard_text=heard_text, message=f"Portero/a {gk.name} activo. Di la acción.",
                active_player_id=gk.id, active_player_label=_active_player_label(gk),
            )
        else:
            player = _find_player_by_number(db, match.team_id, result.data["player_number"])
            if not player:
                return schemas.VoiceCommandOut(status="error", heard_text=heard_text, message=f"No hay ningún jugador con el número {result.data['player_number']} en este equipo")
            match.active_player_id = player.id
            db.commit()
            return schemas.VoiceCommandOut(
                status="context_set", heard_text=heard_text, message=f"Jugador {player.number}, {player.name}, activo. Di la acción.",
                active_player_id=player.id, active_player_label=_active_player_label(player),
            )

    if result.kind == "delete_last_of_type":
        player = _find_player_by_number(db, match.team_id, result.data["player_number"])
        if not player:
            return schemas.VoiceCommandOut(status="error", heard_text=heard_text, message=f"No existe el jugador {result.data['player_number']}")
        target_type = result.data["action_type"]
        event = db.query(models.MatchEvent).filter(
            models.MatchEvent.match_id == match_id,
            models.MatchEvent.player_id == player.id,
            models.MatchEvent.action_type == target_type,
        ).order_by(models.MatchEvent.id.desc()).first()
        if not event:
            return schemas.VoiceCommandOut(status="error", heard_text=heard_text, message="No se encontró esa acción para ese jugador")
        _revert_event(db, event)
        db.delete(event)
        db.commit()
        return schemas.VoiceCommandOut(status="undone", heard_text=heard_text, message=f"Eliminado: {player.name} — {ACTION_LABELS.get(target_type)}")

    if result.kind == "change_last_type":
        last_event = db.query(models.MatchEvent).filter(
            models.MatchEvent.match_id == match_id
        ).order_by(models.MatchEvent.id.desc()).first()
        if not last_event:
            return schemas.VoiceCommandOut(status="error", heard_text=heard_text, message="No hay acciones que corregir")
        new_type = result.data["action_type"]
        _revert_event(db, last_event)
        last_event.action_type = new_type
        last_event.deltas = ACTION_DELTAS[new_type]
        last_event.raw_text = (last_event.raw_text or "") + f" (corregido a {ACTION_LABELS.get(new_type)})"
        _apply_score_delta(match, new_type, +1)
        db.commit()
        db.refresh(last_event)
        return schemas.VoiceCommandOut(status="corrected", heard_text=heard_text, message=f"Última acción corregida a: {ACTION_LABELS.get(new_type)}", event=last_event)

    if result.kind == "reassign_last":
        last_event = db.query(models.MatchEvent).filter(
            models.MatchEvent.match_id == match_id
        ).order_by(models.MatchEvent.id.desc()).first()
        if not last_event:
            return schemas.VoiceCommandOut(status="error", heard_text=heard_text, message="No hay acciones que corregir")
        new_player = _find_player_by_number(db, match.team_id, result.data["new_player_number"])
        if not new_player:
            return schemas.VoiceCommandOut(status="error", heard_text=heard_text, message=f"No existe el jugador {result.data['new_player_number']}")
        _revert_event(db, last_event)
        last_event.player_id = new_player.id
        _apply_score_delta(match, last_event.action_type, +1)
        db.commit()
        db.refresh(last_event)
        return schemas.VoiceCommandOut(status="corrected", heard_text=heard_text, message=f"Acción reasignada a {new_player.name}", event=last_event)

    if result.kind == "action":
        if result.data["is_gk"]:
            player = _find_goalkeeper(db, match.team_id)
            if not player:
                return schemas.VoiceCommandOut(status="error", heard_text=heard_text, message="No hay ningún portero/a en la plantilla de este equipo")
        elif result.data["player_number"] is not None:
            player = _find_player_by_number(db, match.team_id, result.data["player_number"])
            if not player:
                return schemas.VoiceCommandOut(status="error", heard_text=heard_text, message=f"No hay ningún jugador con el número {result.data['player_number']} en este equipo")
        else:
            # Sin identificador explícito: usar el jugador de campo del contexto activo
            player = active_player
            if not player:
                return schemas.VoiceCommandOut(status="error", heard_text=heard_text, message="No hay ningún jugador activo. Di primero 'jugador N' o 'portero'.")

        event = _register_event(db, match, player, result.data["action_type"], result.data["raw_text"])

        # Actualizar el contexto activo si el comando lo fijaba explícitamente
        if result.data.get("set_context"):
            match.active_player_id = player.id
            db.commit()

        role = "Portero/a" if player.is_gk else "Jugador"
        label = ACTION_LABELS.get(result.data["action_type"], result.data["action_type"])
        return schemas.VoiceCommandOut(
            status="registered", heard_text=heard_text,
            message=f"Registrado: {role} {player.number} — {label}",
            event=event,
            active_player_id=player.id,
            active_player_label=_active_player_label(player),
        )

    return schemas.VoiceCommandOut(status="error", heard_text=heard_text, message="No se pudo interpretar el comando")


@router.post("/matches/{match_id}/voice-command", response_model=schemas.VoiceCommandOut)
def voice_command(match_id: int, payload: schemas.VoiceCommandIn, db: Session = Depends(get_db)):
    """Interpreta y ejecuta un comando ya transcrito como texto (p.ej. desde la Web Speech API del navegador)."""
    match = _get_match_or_404(db, match_id)
    active_player, active_is_gk = _get_active_context(db, match)
    result = interpret_command(payload.text, active_is_gk=active_is_gk)
    return _execute_result(db, match, active_player, result, heard_text=payload.text)


@router.post("/matches/{match_id}/voice-audio", response_model=schemas.VoiceCommandOut)
async def voice_audio(match_id: int, audio: UploadFile = File(...), db: Session = Depends(get_db)):
    """
    Recibe un clip de audio corto (una orden de voz), lo transcribe con
    Whisper en el propio servidor, y ejecuta el comando resultante igual
    que /voice-command. Pensado para usarse con captura de audio con
    supresión de ruido activada en el frontend (echoCancellation,
    noiseSuppression, autoGainControl), en vez de depender del
    reconocimiento del navegador.
    """
    match = _get_match_or_404(db, match_id)
    audio_bytes = await audio.read()

    try:
        text = transcribe_audio_bytes(audio_bytes)
    except Exception as e:
        return schemas.VoiceCommandOut(status="error", message=f"No se pudo transcribir el audio: {e}")

    if not text:
        return schemas.VoiceCommandOut(status="not_understood", message="No se ha detectado ninguna voz en el audio grabado")

    active_player, active_is_gk = _get_active_context(db, match)
    result = interpret_command(text, active_is_gk=active_is_gk)
    return _execute_result(db, match, active_player, result, heard_text=text)
