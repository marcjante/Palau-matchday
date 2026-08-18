# HC Palau Matchday

Sistema completo de estadísticas de partido de hockey patines por voz o
manualmente, para HC Palau. Un solo repositorio, dos partes que se
despliegan por separado:

```
hcpalau-matchday/
├── backend/     ← API en Python (FastAPI) — se despliega en Railway o Render
└── docs/        ← Frontend web — se despliega con GitHub Pages directamente desde esta carpeta
```

Por qué está en un único repo: es un solo producto (backend + interfaz), y
así solo tienes un sitio donde mirar el historial de cambios. Se despliegan
en dos servicios distintos porque son dos tecnologías distintas (Python vs.
HTML/JS estático), pero viven juntos en el mismo control de versiones.

La carpeta del frontend se llama `docs/` a propósito (no `frontend/`):
GitHub Pages solo puede servir directamente desde la raíz del repo o desde
una carpeta llamada `docs/`, así que usando ese nombre no hace falta ninguna
configuración adicional ni una GitHub Action para publicarlo.

---

## Guía paso a paso — subirlo como proyecto nuevo, desde cero

Esto asume que quieres un repositorio nuevo con un nombre nuevo, sin tocar
ninguno de tus repos existentes.

### 1. Crear el repositorio en GitHub

1. Ve a [github.com/new](https://github.com/new).
2. Nombre del repositorio: el que quieras (por ejemplo `hcpalau-matchday`).
   Puede ser público o privado — si lo haces privado, GitHub Pages sigue
   funcionando si tienes GitHub Pro, o puedes hacerlo público si no te
   importa que el frontend (solo el frontend, no el backend ni tu API key)
   sea visible.
3. **No marques** "Add a README" ni ".gitignore" — ya vienen incluidos en
   este proyecto y si los añades ahí, chocan al hacer el primer push.
4. Pulsa "Create repository". GitHub te enseña una pantalla con comandos —
   no los uses todavía, sigue con el paso 2.

### 2. Preparar el proyecto en tu ordenador

1. Descomprime el zip que te he dado en una carpeta de tu ordenador.
2. Abre una terminal dentro de esa carpeta (`hcpalau-matchday/`).
3. Inicializa git y haz el primer commit:
   ```bash
   git init
   git add -A
   git commit -m "Version inicial: backend FastAPI + frontend con voz"
   git branch -M main
   ```

### 3. Conectarlo con GitHub y subirlo

Sustituye `TU-USUARIO` y `NOMBRE-DEL-REPO` por los tuyos reales (el nombre
que le pusiste en el paso 1):

```bash
git remote add origin https://github.com/TU-USUARIO/NOMBRE-DEL-REPO.git
git push -u origin main
```

Si te pide usuario/contraseña y falla, es porque GitHub ya no acepta
contraseña normal por HTTPS — necesitas un [token de acceso
personal](https://github.com/settings/tokens) (Settings → Developer
settings → Personal access tokens → Generate new token, con permiso
`repo`) y lo pegas donde te pida la contraseña.

### 4. Activar GitHub Pages para el frontend

1. En tu repo en GitHub, ve a **Settings → Pages**.
2. En "Build and deployment" → Source: **Deploy from a branch**.
3. Branch: **main**, carpeta: **/docs**. Guarda.
4. Espera 1-2 minutos. Tu frontend quedará publicado en
   `https://TU-USUARIO.github.io/NOMBRE-DEL-REPO/`.

### 5. Desplegar el backend en Railway

1. Crea cuenta en [railway.app](https://railway.app) si no la tienes.
2. **New Project → Deploy from GitHub repo** → selecciona este mismo repo
   (`NOMBRE-DEL-REPO`).
3. **Importante**: Railway por defecto intenta construir desde la raíz del
   repo, pero el backend está en la subcarpeta `backend/`. En la
   configuración del servicio (Settings → General → Root Directory),
   pon: `backend`
4. Railway detecta el `Dockerfile` dentro de esa carpeta automáticamente.
5. Añade una base de datos: botón **New → Database → PostgreSQL** dentro
   del mismo proyecto.
6. En el servicio del backend, pestaña **Variables**, añade:
   - `API_KEY` = una clave larga y aleatoria tuya
   - `DATABASE_URL` = `${{Postgres.DATABASE_URL}}` (referencia a la base de
     datos que acabas de crear, Railway te la sugiere al escribir `${{`)
   - `WHISPER_MODEL_SIZE` = `base` (opcional, es el valor por defecto)
7. Railway te da una URL pública, tipo
   `https://nombre-del-repo-production.up.railway.app`. Compruébala
   abriendo `/health` al final de esa URL — debe responder
   `{"status":"healthy"}`.

### 6. Conectar el frontend con el backend

1. Abre tu frontend ya publicado
   (`https://TU-USUARIO.github.io/NOMBRE-DEL-REPO/`).
2. En la primera pantalla, pon la URL de Railway del paso 5 y la `API_KEY`
   que definiste. Se queda guardado en ese dispositivo/navegador.
3. Ya puedes crear tu equipo, añadir jugadores, y empezar un partido.

---

## Qué contiene cada parte

Consulta `backend/README.md` y `docs/README.md` para el detalle técnico
completo de cada mitad (arquitectura, endpoints, limitaciones conocidas,
cómo funciona el reconocimiento de voz, etc.) — este README raíz es solo la
guía de despliegue conjunta.

## Nota sobre el proyecto Android (Capacitor)

Una iteración anterior de este trabajo generaba también un proyecto Android
nativo con Capacitor para compilar un `.apk`. Ese proyecto no forma parte
de este repositorio — es una vía distinta (sin backend en la nube, todo
local en el dispositivo) que quedó descartada al pasar a esta arquitectura
con backend en Python. Si en algún momento quieres retomarla, hay que
reconstruirla desde cero contra esta versión del frontend.
