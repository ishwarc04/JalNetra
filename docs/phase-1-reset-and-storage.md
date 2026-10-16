> Reference documentation imported from AADi2oo6/JalNetra2.O at commit 47567bbdc401a043de4cb53dc097fb915e7e6b62. Phase completion, test results, reset results, storage measurements, and frontend descriptions below refer to that source project. They are not verification results for this repository. The frontend has not yet been imported here.

# JalNetra 2.0 — Phase 1: Clean Data Reset, Storage Management & Empty Project Baseline

## Overview

Phase 1 establishes a safe, verifiable storage management and project reset subsystem for JalNetra 2.0.
All demo and old development data have been purged from the project through the explicit reset mechanism, preparing the system for a purely user-driven workflow:

$$\text{User discovers/searches water body} \longrightarrow \text{User adds it to database} \longrightarrow \text{No satellite data downloaded automatically}$$

---

## 1. Storage & Reset Architecture

The storage management subsystem is implemented in [`app.services.storage.reset_service.StorageResetService`](../backend/app/services/storage/reset_service.py) and integrated with [`app.services.storage_service.LocalStorageService`](../backend/app/services/storage_service.py).

### Safety Principles
1. **Strict Path Containment:** All filesystem paths are resolved via `resolve_safe_path()`. Operations cannot traverse outside `settings.resolved_data_dir`. Attempts to delete root directories, `database/`, or parent paths raise `StoragePathTraversalError` or `ValueError`.
2. **Schema & Migration Protection:** Reset operations truncate application data records using SQLAlchemy ORM sessions in child-to-parent dependency order (`AnalysisRun` $\rightarrow$ `SatelliteAsset` $\rightarrow$ `SatelliteScene` $\rightarrow$ `CacheEntry` $\rightarrow$ `WaterBody`). The database file (`data/database/jalnetra.db`), Alembic version table (`alembic_version`), and schema tables are completely preserved.
3. **Directory Hierarchy Retention:** All standard subdirectories (`scenes/`, `processed/`, `cache/`, `water_bodies/`, `tiles/`, `exports/`, `manifests/`) have `.gitkeep` files preserved or recreated upon clearing, preventing git tracking loss.
4. **Idempotence:** Consecutive cleanup or reset calls execute cleanly and report 0 deleted / 0 bytes freed without throwing errors.

---

## 2. Maintenance & Cleanup APIs

The maintenance endpoints are mounted at `/api/v1/storage` in [`app/api/v1/storage.py`](../backend/app/api/v1/storage.py):

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/v1/storage/status` | Comprehensive inventory of database counts, local storage sizes, directory status, and orphan detections. |
| `POST` | `/api/v1/storage/clear/cache` | Truncates `cache_entries` and deletes cached JSON files in `data/cache/`. |
| `POST` | `/api/v1/storage/clear/processed` | Truncates `analysis_runs` and deletes generated masks and overlays in `data/processed/`. |
| `POST` | `/api/v1/storage/clear/satellite` | Truncates `satellite_scenes`, `satellite_assets`, and deletes raw Sentinel-2 GeoTIFF directories in `data/scenes/`. |
| `POST` | `/api/v1/storage/reset` | Complete project reset: truncates all application tables and clears all local storage files. |

---

## 3. Maintenance UI

Added to the System Overview dashboard in [`frontend/src/pages/Dashboard.tsx`](../frontend/src/pages/Dashboard.tsx):
- **Database Inventory Cards:** Live counts for Water Bodies, Satellite Scenes, Satellite Assets, Analysis Runs, Cache Entries, and SQLite file size.
- **Local Storage Footprint Cards:** Live sizes for Satellite Data, Processed Data, Cache Storage, and Total Data footprint, alongside orphan scene folder counts.
- **Action Buttons:** `CLEAR CACHE`, `CLEAR PROCESSED DATA`, `CLEAR SATELLITE DATA`, and a highlighted danger button `RESET PROJECT DATA`.
- **Destructive Confirmation Modal:** Requires explicit confirmation before executing destructive operations, with clear impact warning:
  > *"This will permanently remove all stored water bodies, satellite scenes, downloaded imagery, processed results and cache data. Project code and database schema will not be deleted."*

---

## 4. Empty Project Baseline Verification

Following the explicit reset, the project baseline is:

```text
Water bodies:            0
Satellite scenes:        0
Satellite assets:        0
Analysis runs:           0
Cache entries:           0
Downloaded satellite files: 0 B
Processed imagery:       0 B
Cache data:              0 B
Orphan scene folders:    0
```

- **Frontend Monitoring Map:** Renders a neutral geographical view without defaulting to demo lakes. When 0 water bodies exist, displays a message: *"No water bodies registered yet. Use GLOBAL DISCOVERY or CATALOG to register water bodies."*
- **No Automatic Triggers:** Startup lifespan does not seed or download data. No background downloads or STAC queries are initiated until explicitly requested by the user.

---

## 5. Architectural Note: Smaller Satellite Downloads

Phase 0 identified that Earth Search STAC downloads entire 100km $\times$ 100km tile bands (B02, B03, B04, B08 at ~200MB each), consuming ~850MB–1GB per scene.
For upcoming satellite acquisition phases:
- Sentinel-2 cloud-optimized GeoTIFFs (COGs) must eventually be accessed via HTTP range requests or windowed reads based strictly on the water body AOI bounding box.
- Only the spatial bounding box intersecting the target water body should be acquired and stored locally, dramatically reducing disk usage from hundreds of megabytes to a few megabytes per observation.

