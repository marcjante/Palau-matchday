"""
Transcripción de audio a texto con Whisper, ejecutándose en el propio
servidor — no se manda el audio a Google ni a ningún tercero, a diferencia
de la Web Speech API del navegador.

Por qué esto es mejor para el ruido del pabellón:
- El frontend captura el audio pidiendo explícitamente supresión de ruido,
  cancelación de eco y control automático de ganancia al micrófono
  (echoCancellation, noiseSuppression, autoGainControl) — algo que el
  SpeechRecognition del navegador no permite configurar porque gestiona el
  micrófono internamente sin exponer esas opciones.
- Whisper es, en general, más robusto ante ruido de fondo y acentos que el
  reconocimiento del navegador, especialmente en clips cortos y con ruido
  constante de fondo (grada, pista) más que picos puntuales.

Primera ejecución: descarga el modelo elegido desde Hugging Face (unos
40-150 MB según el tamaño) — necesita conexión a internet la primera vez
que se llama; después queda cacheado en el disco del contenedor. En
Railway/Render con almacenamiento efímero, esto significa que se puede
volver a descargar tras cada redeploy (tarda unos segundos, no es grave,
pero conviene saberlo).
"""
import os
import tempfile
from faster_whisper import WhisperModel

# tiny = más rápido, menos preciso. base = buen equilibrio. small = más preciso, más lento.
# En CPU de un tier gratuito de Railway/Render, "tiny" o "base" son las opciones realistas
# para no introducir demasiada latencia durante un partido en directo.
MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "base")

_model = None


def get_model() -> WhisperModel:
    global _model
    if _model is None:
        # compute_type="int8" reduce memoria y acelera la inferencia en CPU,
        # a costa de una pérdida de precisión mínima — apropiado aquí.
        _model = WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8")
    return _model


def transcribe_audio_bytes(audio_bytes: bytes, suffix: str = ".webm") -> str:
    """
    Transcribe un clip de audio corto (una orden de voz) a texto en español.
    Lanza excepción si el audio no se puede decodificar o el modelo falla;
    el router se encarga de convertir eso en una respuesta clara al usuario.
    """
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
        tmp.write(audio_bytes)
        tmp.flush()
        model = get_model()
        segments, _info = model.transcribe(
            tmp.name,
            language="es",
            beam_size=1,          # prioriza velocidad sobre precisión máxima, para uso en directo
            vad_filter=True,      # recorta silencios al principio/final del clip
        )
        text = " ".join(seg.text.strip() for seg in segments).strip()
        return text
