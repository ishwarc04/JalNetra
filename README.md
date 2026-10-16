# JalNetra

Backend for monitoring water bodies with Sentinel-2 satellite observations.
This repository currently contains the FastAPI backend; a frontend has not yet
been added here.

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

The initial backend, migrations, storage scripts, and tests were adapted from
[AADi2oo6/JalNetra2.O](https://github.com/AADi2oo6/JalNetra2.O), reference commit
`47567bbdc401a043de4cb53dc097fb915e7e6b62`. Generated data, frontend build artifacts,
credentials, and the reference repository's Git metadata are excluded.
