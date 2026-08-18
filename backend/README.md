# HC Palau — Backend de Estadísticas (Python / FastAPI)

API en Python que centraliza la gestión de equipos, jugadores, rivales,
partidos y la interpretación de comandos de voz. Probado end-to-end
localmente (creación de equipos/jugadores/rivales/partidos, comandos de voz,
deshacer, corrección, estadísticas de temporada, histórico contra rival,
exportación CSV/PDF, y autenticación por API key con y sin cabecera).

## Por qué Python aquí (y no solo mejorar el JavaScript)

Lo pediste para poder ampliar más adelante con estadísticas e incorporación
de equipos. Eso es exactamente lo que este diseño resuelve mejor que el
`localStorage` del navegador:

- **Relacional de verdad**: jugadores pertenecen a equipos, partidos
  pertenecen a un equipo y un rival, eventos pertenecen a un partido. Las
  estadísticas se calculan agregando eventos bajo demanda — no se guardan
  contadores sueltos que se puedan desincronizar.
- **Multi-equipo real**: puedes tener varias plantillas propias (infantil,
  juvenil, senior...) y varios rivales, cada uno con su propio histórico,
  sin duplicar código.
- **Comparativas gratis**: estadísticas por temporada, por jugador, o
  histórico completo contra un rival concreto son simples consultas SQL —
  con `localStorage` habría que reconstruir todo eso a mano en JavaScript.
- **Un solo cerebro**: la interpretación de comandos de voz vive en el
  backend (`app/voice_nlu.py`). El frontend (navegador o app Android) solo
  transcribe el audio y manda el texto — toda la lógica de negocio está en
  un único sitio, en Python, fácil de ampliar.

## Estructura

```
hcpalau-backend/
├── app/
│   ├── main.py          ← arranca la app, monta routers, CORS
│   ├── database.py      ← conexión SQLite/Postgres
│   ├── models.py         ← Team, Player, Opponent, Match, MatchEvent
│   ├── schemas.py         ← validación de entrada/salida (Pydantic)
│   ├── voice_nlu.py        ← interpretación de comandos de voz (texto -> acción)
│   ├── auth.py               ← autenticación por API key
│   └── routers/
│       ├── teams.py       ← equipos propios
│       ├── players.py      ← jugadores por equipo
│       ├── opponents.py     ← rivales
│       ├── matches.py        ← partidos
│       ├── events.py          ← registro manual/voz, deshacer, corregir
│       ├── stats.py            ← estadísticas agregadas
│       └── export.py            ← CSV / PDF
├── requirements.txt
├── Dockerfile
└── .env.example
```

## 1. Probarlo en local primero (recomendado antes de desplegar)

```bash
cd hcpalau-backend
python3 -m venv venv
source venv/bin/activate        # en Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # y edita API_KEY con una clave tuya
uvicorn app.main:app --reload --port 8000
```

Abre `http://localhost:8000/docs` — ahí tienes la documentación interactiva
de todos los endpoints, puedes probarlos directamente desde el navegador sin
escribir ni una línea de código adicional.

## 2. Desplegar en la nube (Railway — el más simple)

1. Crea una cuenta en [railway.app](https://railway.app) (tiene un tier
   gratuito con horas limitadas al mes, suficiente para un club).
2. Sube la carpeta `hcpalau-backend/` a un repositorio de GitHub.
3. En Railway: **New Project → Deploy from GitHub repo** → selecciona el
   repositorio. Railway detecta el `Dockerfile` automáticamente.
4. **Añade una base de datos Postgres**: en el proyecto, botón **New → 
   Database → PostgreSQL**. Railway te crea automáticamente la variable
   `DATABASE_URL` y la puedes referenciar en el servicio del backend con
   `${{Postgres.DATABASE_URL}}` desde la pestaña Variables — así los datos
   sobreviven a cada redeploy (con SQLite en el contenedor, no).
5. En el servicio del backend, pestaña **Variables**, añade:
   - `API_KEY` = una clave larga y aleatoria tuya (esto es lo que luego
     pondrás en el frontend).
   - `DATABASE_URL` = la referencia a Postgres del paso anterior.
6. Railway te da una URL pública tipo
   `https://hcpalau-backend-production.up.railway.app`. Esa es la URL que
   configurarás en el frontend.
7. Comprueba que funciona: abre
   `https://tu-url.up.railway.app/health` en el navegador — debe devolver
   `{"status":"healthy"}`.

## 2bis. Alternativa: Render

Mismo Dockerfile, pasos equivalentes: **New → Web Service** → conecta el
repo de GitHub → Render detecta el Dockerfile → en **Environment** añade
`API_KEY` y `DATABASE_URL` (si añades su base de datos Postgres gestionada,
que también tiene tier gratuito) → Deploy. La URL pública tendrá el formato
`https://hcpalau-backend.onrender.com`.

**Aviso sobre el tier gratuito de Render**: el servicio "duerme" tras 15
minutos sin uso y tarda unos segundos en despertar con la primera petición.
Para un partido no es grave (la primera petición del día tarda un poco más),
pero tenlo en cuenta.

## 3. Conectar el frontend a esta API

En el frontend (la app web/Android), hay que configurar dos cosas antes de
usarla contra este backend en vez de contra `localStorage`:

- La URL base de la API (la que te da Railway/Render en el paso anterior).
- La `API_KEY` que definiste, para mandarla en la cabecera `X-API-Key` en
  cada petición.

Esto se hace en la app de HC Palau con voz — ver el README de ese proyecto
para el paso de integración concreto.

## 4. Migraciones de esquema en el futuro

Ahora mismo, las tablas se crean automáticamente al arrancar
(`Base.metadata.create_all`), lo cual es perfecto para empezar pero no sirve
para cambios de esquema en una base de datos ya en producción con datos
reales (por ejemplo, añadir una columna nueva). Cuando llegue ese momento,
lo correcto es introducir **Alembic** (herramienta de migraciones de
SQLAlchemy) en vez de seguir con `create_all`. No lo he añadido ahora para
no complicar el arranque inicial, pero es el siguiente paso natural en
cuanto haya datos reales de partidos que no se puedan permitir perder.

## 5. Seguridad — limitaciones actuales

- La autenticación es una única API key compartida, no hay usuarios ni
  contraseñas individuales por entrenador. Vale para un cuerpo técnico que
  confía entre sí; no distingue quién hizo qué cambio.
- CORS está abierto a cualquier origen (`allow_origins=["*"]`) para que el
  frontend en GitHub Pages pueda llamar a la API sin fricciones. Si en algún
  momento quieres restringirlo solo a tu dominio, es una línea en
  `app/main.py`.

## 5bis. Transcripción de voz con Whisper (reducción de ruido)

Además de `/voice-command` (texto ya transcrito, típicamente por la Web
Speech API del navegador), existe `/voice-audio`: recibe un clip de audio
corto y lo transcribe con Whisper (`faster-whisper`) ejecutándose en el
propio servidor, en vez de depender del reconocimiento del navegador.

**Por qué esto ayuda con el ruido del pabellón**: el frontend pide el
micrófono con `echoCancellation`, `noiseSuppression` y `autoGainControl`
activados explícitamente — algo que el `SpeechRecognition` del navegador no
permite configurar. Whisper además suele ser más robusto ante ruido de
fondo constante que el reconocimiento del navegador.

**Aviso importante — esto no lo he podido probar de extremo a extremo**:
la primera vez que se usa, `faster-whisper` descarga el modelo (unos
40-150 MB según `WHISPER_MODEL_SIZE`) desde Hugging Face. Ese dominio no
está accesible desde el entorno donde desarrollé esto, así que solo pude
verificar que el código instala, importa, y falla de forma controlada (con
un mensaje de error claro, no un crash) cuando no puede descargar el
modelo — no pude confirmar que la transcripción en sí funcione bien con
audio real. En Railway/Render, con acceso normal a internet, la descarga
del modelo debería funcionar sin problema, pero la primera prueba real con
voz de verdad la tienes que hacer tú tras desplegar.

**Rendimiento a tener en cuenta**: Whisper corriendo en CPU (los tiers
gratuitos de Railway/Render no dan GPU) tarda más que la Web Speech API en
devolver un resultado — con el modelo `base` y clips de 2-3 segundos,
espera algo así como 1-4 segundos de latencia por comando, quizás más en
el arranque en frío del contenedor. Si notas que va lento para el ritmo de
un partido, cambia `WHISPER_MODEL_SIZE=tiny` (más rápido, algo menos
preciso) en las variables de entorno del servicio desplegado.

## Endpoints principales

| Método | Ruta | Qué hace |
|---|---|---|
| POST | `/teams` | Crear equipo propio (con categoría) |
| GET | `/teams` | Listar equipos propios |
| POST | `/teams/{id}/players` | Añadir jugador/a a un equipo |
| GET | `/teams/{id}/players` | Listar plantilla |
| POST | `/opponents` | Crear/obtener rival |
| POST | `/matches` | Crear partido (equipo + rival + temporada) |
| POST | `/matches/{id}/voice-command` | Interpretar y registrar un comando de voz (texto ya transcrito) |
| POST | `/matches/{id}/voice-audio` | Interpretar y registrar un comando a partir de un clip de audio, transcrito con Whisper en el propio servidor (mejor con ruido de fondo que la Web Speech API del navegador) |
| POST | `/matches/{id}/events` | Registrar acción manual (botón) |
| PATCH | `/events/{id}` | Corregir jugador/tipo de un evento del historial |
| DELETE | `/events/{id}` | Eliminar un evento del historial |
| POST | `/matches/{id}/undo-last` | Deshacer la última acción |
| GET | `/matches/{id}/summary` | Resumen completo del partido (jugadores + historial) |
| GET | `/players/{id}/stats` | Estadísticas de un jugador (filtrable por temporada/rival) |
| GET | `/teams/{id}/season-summary` | Resumen de toda la temporada del equipo |
| GET | `/opponents/{id}/history` | Histórico de partidos contra un rival |
| GET | `/matches/{id}/export/csv` | Exportar CSV |
| GET | `/matches/{id}/export/pdf` | Exportar PDF |

Todos exigen la cabecera `X-API-Key` si `API_KEY` está definida en el
servidor.
