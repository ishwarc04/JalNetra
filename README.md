# JalNetra

Backend for monitoring water bodies with Sentinel-2 satellite observations.
This repository contains the FastAPI backend and an initial React/Vite frontend
shell. Frontend components and monitoring pages are being imported separately.

## Backend setup (Windows PowerShell)

Requires Python 3.10 or later. From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
Copy-Item .env.example .env
Set-Location backend
..\.venv\Scripts\python.exe -m alembic upgrade head
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/docs` for the API documentation. Database migrations
must run before using catalog endpoints. Storage directories are created at
runtime under the repository's `data/` directory.

Configuration files are resolved from the repository location, regardless of the
launch directory. The root `.env` overrides an optional `backend/.env`; process
environment variables override both files. Unrelated `.env` files in the launch
directory or its parent are not loaded.

## Frontend setup (Windows PowerShell)

From the repository root, in a separate terminal:

```powershell
Set-Location frontend
npm ci
Copy-Item .env.example .env
npm run dev
```

The development server uses port 5173. `VITE_API_BASE_URL` defaults to
`http://localhost:8000`; run the backend separately using the commands above.
`npm run build` checks TypeScript and creates the production bundle.

The frontend import is split into three commits:

1. React/Vite configuration and a minimal application shell (current).
2. Shared components and the backend API client.
3. Monitoring pages, application navigation, and styling from the reference.

## Tests

From `backend/`:

```powershell
..\.venv\Scripts\python.exe -m pytest tests -q
```

The tests use temporary databases and synthetic raster fixtures. Live discovery
and satellite downloads additionally require network access. AI and Telegram
integrations require your own credentials and are disabled in `.env.example`.
Never commit `.env`, local databases, downloaded images, or virtual environments.

## Backend modules

- Water-body catalog: create, filter, update, and deactivate records in SQLite.
- Discovery: search OpenStreetMap and import water bodies into the catalog.
- Satellite acquisition: search and rank STAC scenes, acquire assets, and track observations.
- Raster processing: generate RGB overlays, cloud masks, water masks, and spectral indices.
- Storage: inspect runtime data and perform explicit storage resets.
- Optional integrations: AI summaries and Telegram commands.

Spectral water-quality indicators are remote-sensing proxies, not laboratory
measurements of drinking-water safety. This local development API has no
authentication and should remain bound to localhost.

## Source reference

Backend workflow references imported from the original project:

- [Storage management and reset APIs](docs/phase-1-reset-and-storage.md)
- [Location search and water-body discovery](docs/phase-2-discovery.md)
- [Water-body selection and batch import](docs/phase-3-import.md)
- [Satellite observations and time-series architecture](docs/satellite-time-series-analysis.md)

These documents describe the source project's development phases, including its
frontend and historical validation results. They do not establish completion or
test results for this repository. Backend verification here remains incomplete.

The initial backend, migrations, storage scripts, tests, and frontend tooling were adapted from
[AADi2oo6/JalNetra2.O](https://github.com/AADi2oo6/JalNetra2.O), reference commit
`47567bbdc401a043de4cb53dc097fb915e7e6b62`. Generated data, frontend build artifacts,
credentials, and the reference repository's Git metadata are excluded.
