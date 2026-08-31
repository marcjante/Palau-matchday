"""
Interpretación de comandos de voz + definición de estadísticas.

Toda la lógica de "qué significa esta frase" vive aquí, en el backend, en
vez de en el navegador. El frontend solo transcribe el audio y manda el
texto; este módulo decide qué acción es, a qué jugador corresponde, y qué
contadores hay que sumar. Esto es lo que permite ampliar el vocabulario o
añadir estadísticas nuevas sin tocar el cliente.
"""
import re
import unicodedata

# ---------------------------------------------------------------------
# Definición de acciones: qué contadores (deltas) suma cada una
# ---------------------------------------------------------------------
ACTION_DELTAS = {
    "shot":              {"shots": 1},
    "shot_on_target":    {"shots": 1, "shots_on_target": 1},
    "shot_off":          {"shots": 1, "shots_off": 1},
    "goal":              {"shots": 1, "shots_on_target": 1, "goals": 1},
    "assist":            {"assists": 1},
    "loss":              {"losses": 1},
    "recovery":          {"recoveries": 1},
    "interception":      {"interceptions": 1},
    "foul_committed":    {"fouls_committed": 1},
    "foul_received":     {"fouls_received": 1},
    "card_yellow":       {"yellow_cards": 1},
    "card_red":          {"red_cards": 1},
    "defensive_action":  {"defensive_actions": 1},
    # Portero
    "gk_save":              {"shots_faced": 1, "saves": 1},
    "gk_goal_conceded":     {"shots_faced": 1, "goals_conceded": 1},
    "gk_penalty_saved":     {"penalties_faced": 1, "penalties_saved": 1, "shots_faced": 1, "saves": 1},
    "gk_penalty_conceded":  {"penalties_faced": 1, "goals_conceded": 1, "shots_faced": 1},
    "gk_exit_good":         {"exits_good": 1},
    "gk_exit_bad":          {"exits_bad": 1},
    "gk_distribution":      {"distributions": 1},
}

ACTION_LABELS = {
    "shot": "Tiro", "shot_on_target": "Tiro a portería", "shot_off": "Tiro fuera",
    "goal": "Gol", "assist": "Asistencia", "loss": "Pérdida", "recovery": "Recuperación",
    "interception": "Intercepción", "foul_committed": "Falta cometida", "foul_received": "Falta recibida",
    "card_yellow": "Tarjeta amarilla", "card_red": "Tarjeta roja", "defensive_action": "Acción defensiva",
    "gk_save": "Parada", "gk_goal_conceded": "Gol recibido", "gk_penalty_saved": "Penalti parado",
    "gk_penalty_conceded": "Penalti recibido", "gk_exit_good": "Salida correcta", "gk_exit_bad": "Salida fallida",
    "gk_distribution": "Distribución/Pase",
}

NUMBER_WORDS = {
    "cero": "0", "uno": "1", "una": "1", "dos": "2", "tres": "3", "cuatro": "4",
    "cinco": "5", "seis": "6", "siete": "7", "ocho": "8", "nueve": "9", "diez": "10",
    "once": "11", "doce": "12", "trece": "13", "catorce": "14", "quince": "15",
    "dieciseis": "16", "diecisiete": "17", "dieciocho": "18", "diecinueve": "19", "veinte": "20",
}

OUTFIELD_PATTERNS = [
    ("goal",              re.compile(r"\bgol\b|\bmarca\b|\banota\b")),
    ("assist",            re.compile(r"asistenci|\basiste\b|pase de gol")),
    ("shot_on_target",    re.compile(r"tiro a porteria|tiro a puerta|tiro al arco|chuta a porteria")),
    ("shot_off",          re.compile(r"tiro fuera|chuta fuera|dispara fuera")),
    ("shot",              re.compile(r"\btiro\b|\bchuta\b|\bchutado\b|\bdispara\b|\blanza\b")),
    ("loss",              re.compile(r"perdida|\bpierde\b|perdio")),
    ("recovery",          re.compile(r"recuperacion|\brecupera\b")),
    ("interception",      re.compile(r"intercepcion|\bintercepta\b")),
    ("foul_received",     re.compile(r"recibe falta|le hacen falta|falta a favor|falta recibida")),
    ("foul_committed",    re.compile(r"\bfalta\b")),
    ("card_yellow",       re.compile(r"tarjeta amarilla|amonestacion")),
    ("card_red",          re.compile(r"tarjeta roja|expulsion")),
    ("defensive_action",  re.compile(r"entrada defensiva|accion defensiva|\bdespeje\b|\bentrada\b")),
]

GK_PATTERNS = [
    ("gk_penalty_saved",    re.compile(r"penalti parado|para el penalti|penalti detenido")),
    ("gk_penalty_conceded", re.compile(r"penalti recibido|le pitan penalti|penalti en contra")),
    ("gk_goal_conceded",    re.compile(r"gol recibido|encajado|le meten gol|gol encajado")),
    ("gk_exit_good",        re.compile(r"salida correcta|sale bien")),
    ("gk_exit_bad",         re.compile(r"salida fallida|sale mal")),
    ("gk_distribution",     re.compile(r"\bpase\b|\bsaque\b|distribucion")),
    ("gk_save",             re.compile(r"\bparada\b|\bpara\b|\bdetiene\b|\batrapa\b")),
]

GOALKEEPER_WORD_RE = re.compile(r"\bportero\b|\bportera\b")
PLAYER_NUMBER_RE = re.compile(r"(?:jugador|numero)\s+(\d{1,2})\b")
ZONE_RE = re.compile(r"\b(a|b|c|be|ce|se)\s*-?\s*([1-3])\b")


def extract_zone(text: str):
    """Detecta patrones como 'a1', 'a 1', 'be 2' (confusión de 'b'), 'ce 3' (confusión de 'c')."""
    m = ZONE_RE.search(text)
    if not m:
        return None
    letter = m.group(1)
    if letter == "be":
        letter = "b"
    elif letter in ("ce", "se"):
        letter = "c"
    return f"{letter.upper()}{m.group(2)}"

UNDO_RE = re.compile(r"deshacer|deshace la ultima|elimina la ultima accion|borra la ultima accion")
DELETE_LAST_OF_TYPE_RE = re.compile(
    r"elimina(?:r)? (?:el )?ultimo (gol|tiro|asistenci\w*|perdida|recuperacion|falta) del jugador (\d{1,2})"
)
CHANGE_LAST_TYPE_RE = re.compile(
    r"cambiar? la ultima accion a (gol|asistenci\w*|tiro|perdida|recuperacion|falta|tarjeta amarilla|tarjeta roja)"
)
REASSIGN_LAST_RE = re.compile(r"corregir jugador (\d{1,2}) por jugador (\d{1,2})")
HELP_RE = re.compile(r"^ayuda$|comandos disponibles")

CORRECTION_TYPE_MAP = {
    "gol": "goal", "asistencia": "assist", "asistencias": "assist", "tiro": "shot",
    "perdida": "loss", "recuperacion": "recovery", "falta": "foul_committed",
    "tarjeta amarilla": "card_yellow", "tarjeta roja": "card_red",
}
DELETE_TYPE_MAP = {
    "gol": "goal", "tiro": "shot", "asistencia": "assist", "asistencias": "assist",
    "perdida": "loss", "recuperacion": "recovery", "falta": "foul_committed",
}


def normalize_text(text: str) -> str:
    text = text.lower()
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")  # quita acentos
    for word, digit in NUMBER_WORDS.items():
        text = re.sub(rf"\b{word}\b", digit, text)
    return text


def match_pattern(text: str, patterns):
    for action_type, regex in patterns:
        if regex.search(text):
            return action_type
    return None


class VoiceCommandResult:
    """Resultado estructurado de interpretar una frase."""
    def __init__(self, kind, **kwargs):
        self.kind = kind  # 'action' | 'undo' | 'delete_last_of_type' | 'change_last_type' |
                           # 'reassign_last' | 'help' | 'not_understood'
        self.data = kwargs


def interpret_command(raw_text: str, active_is_gk: bool = None) -> VoiceCommandResult:
    """
    Interpreta una frase transcrita y devuelve qué hay que hacer.

    active_is_gk: si hay un jugador "pegado" (contexto activo) desde el
    último "jugador N" o "portero" dicho, indica si ese jugador activo es
    portero/a (True), jugador de campo (False), o si no hay contexto
    activo todavía (None). Cuando la frase no menciona explícitamente un
    jugador/número/portero, se usa este contexto para poder decir solo
    "gol" o "pierde" durante una racha del mismo jugador.

    No accede a la base de datos: solo interpreta texto. La ejecución real
    (buscar el jugador, aplicar los deltas...) se hace en el router, que sí
    conoce el partido y la plantilla.
    """
    text = normalize_text(raw_text)

    if UNDO_RE.search(text):
        return VoiceCommandResult("undo")

    m = DELETE_LAST_OF_TYPE_RE.search(text)
    if m:
        action_type = DELETE_TYPE_MAP.get(m.group(1))
        if action_type:
            return VoiceCommandResult("delete_last_of_type", player_number=m.group(2), action_type=action_type)
        return VoiceCommandResult("not_understood", raw_text=raw_text)

    m = CHANGE_LAST_TYPE_RE.search(text)
    if m:
        action_type = CORRECTION_TYPE_MAP.get(m.group(1))
        if action_type:
            return VoiceCommandResult("change_last_type", action_type=action_type)
        return VoiceCommandResult("not_understood", raw_text=raw_text)

    m = REASSIGN_LAST_RE.search(text)
    if m:
        return VoiceCommandResult("reassign_last", new_player_number=m.group(2))

    if HELP_RE.search(text):
        return VoiceCommandResult("help")

    zone = extract_zone(text)

    # "portero"/"portera" -> SIEMPRE defensa (portería), tenga o no número.
    # Además fija el contexto activo a portero/a.
    if GOALKEEPER_WORD_RE.search(text):
        action_type = match_pattern(text, GK_PATTERNS)
        if action_type:
            return VoiceCommandResult("action", is_gk=True, player_number=None,
                                       action_type=action_type, raw_text=raw_text, set_context=True, zone=zone)
        # Se dijo "portero" solo, sin acción -> solo cambia el contexto activo
        return VoiceCommandResult("set_context", is_gk=True, raw_text=raw_text)

    # "jugador N" / "numero N" -> SIEMPRE ataque, fija el contexto activo a ese jugador
    m = PLAYER_NUMBER_RE.search(text)
    if m:
        player_number = m.group(1)
        action_type = match_pattern(text, OUTFIELD_PATTERNS)
        if action_type:
            return VoiceCommandResult("action", is_gk=False, player_number=player_number,
                                       action_type=action_type, raw_text=raw_text, set_context=True, zone=zone)
        # Se dijo "jugador 5" solo, sin acción -> solo cambia el contexto activo
        return VoiceCommandResult("set_context", is_gk=False, player_number=player_number, raw_text=raw_text)

    # Ni jugador/numero ni portero mencionados: si hay contexto activo (jugador
    # "pegado" de un comando anterior), interpretar como acción corta sobre él.
    if active_is_gk is not None:
        patterns = GK_PATTERNS if active_is_gk else OUTFIELD_PATTERNS
        action_type = match_pattern(text, patterns)
        if action_type:
            return VoiceCommandResult("action", is_gk=active_is_gk, player_number=None,
                                       action_type=action_type, raw_text=raw_text, set_context=False, zone=zone)

    return VoiceCommandResult("not_understood", raw_text=raw_text)
