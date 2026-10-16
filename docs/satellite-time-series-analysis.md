> Reference documentation imported from AADi2oo6/JalNetra2.O at commit 47567bbdc401a043de4cb53dc097fb915e7e6b62. Phase completion, test results, reset results, storage measurements, and frontend descriptions below refer to that source project. They are not verification results for this repository. The frontend has not yet been imported here.

# JalNetra 2.0 — Water-Body-Centric Satellite Time-Series & Analysis Architecture

## 1. Architectural Paradigm Shift

The previous architecture in JalNetra was scene-oriented: it acquired complete Sentinel-2 tile scenes (often exceeding 500 MB to 1 GB per acquisition) and rendered large satellite extents.

The new **Water-Body-Centric and Time-Series-Centric Architecture** refactors the remote sensing workflow around the registered water body as the primary operational entity:

```text
SEARCH / DISCOVER WATER BODY
        ↓
SELECT WATER BODY
        ↓
MONITORING MAP
        ↓
FETCH VISUAL DATA
(User selects: From Date, To Date, Image Count)
        ↓
STAC Archive Query (S2 L2A across water body AOI)
        ↓
Temporal Distribution Selection (N samples across period)
        ↓
Visual Bands Stream & Crop (B04, B03, B02 cropped to AOI + 10% padding)
        ↓
Atomic Storage (rgb.jpg ~20-200 KB + metadata.json; zero raw GeoTIFFs retained)
        ↓
ANALYSIS PAGE (/analysis)
(Timeline gallery, side-by-side / swipe slider comparison, surface extent time series, indicator proxies)
```

---

## 2. Core Principles & Strict Invariants

1. **Water Body is Primary**: All observations belong to a registered water body (`water_body_id`), not arbitrary standalone scenes.
2. **Visual Only (Level 1)**: Only Red (B04), Green (B03), and Blue (B02) 10m bands are fetched.
3. **Strict Storage Minimization**:
   - Bands are streamed to isolated temporary workspaces.
   - Rasters are clipped strictly to the water body bounding box + 10% padding.
   - Compressed JPEG (`rgb.jpg`, quality 92) and `metadata.json` are written to `data/water_bodies/{wb_id}/observations/{scene_id}/`.
   - All raw band GeoTIFFs (100MB+ each) are immediately purged.
   - Storage footprint reduced from ~500 MB per scene down to ~20–200 KB per observation (~99.9% savings).
4. **Cloud Cover Tolerance**:
   - Cloud cover is **not** a hard exclusion filter ("Don't care about cloud or clarity").
   - Temporal availability and chronological distribution take precedence over clarity.
   - Cloud cover percentage is preserved as metadata for user reference.
5. **Uniform Temporal Distribution**:
   - The requested interval $[T_{\text{from}}, T_{\text{to}}]$ is partitioned into $N$ equal bins.
   - For each bin, the candidate scene closest to the bin midpoint is selected.
   - If fewer than $N$ observations exist in the archive, all available observations are captured.
6. **Deduplication & Idempotency**:
   - If an observation scene already exists on disk and in the database for the given water body, it is reused immediately without re-downloading (`reused_count`).
7. **Strict Phase Boundaries**:
   - Dedicated Analysis Page (`/analysis`) is separated from the Monitoring Map (`/map`).
   - Remote-sensing indicator proxies (turbidity, chlorophyll-a, algal bloom, anomaly detection) are present as extensible architecture placeholders and explicitly labeled `COMING IN ANALYSIS PHASE` without dummy or simulated values.
   - No Celery, Redis, Docker, PostgreSQL, IoT, or external bot dependencies.

---

## 3. Database Schema

### Table: `satellite_observations`

| Column | Type | Constraints / Description |
|---|---|---|
| `id` | VARCHAR(36) | Primary Key (UUID) |
| `water_body_id` | VARCHAR(36) | Foreign Key -> `water_bodies.id` (Indexed) |
| `satellite` | VARCHAR(32) | Default `'Sentinel-2'` |
| `provider` | VARCHAR(32) | Default `'earth_search'` |
| `collection` | VARCHAR(64) | Default `'sentinel-2-c1-l2a'` |
| `external_scene_id`| VARCHAR(128) | STAC Item ID (e.g. `S2B_T44QKJ_20240123T052221_L2A`) |
| `sensing_date` | DATETIME | Observation capture timestamp (Indexed) |
| `cloud_cover_percent` | FLOAT | Scene/AOI cloud coverage percentage |
| `aoi_bounds` | VARCHAR(256) | Bounding box `[min_lon, min_lat, max_lon, max_lat]` |
| `aoi_geojson` | TEXT | Clipped AOI geometry |
| `local_visual_path`| VARCHAR(512) | Relative path to `rgb.jpg` |
| `image_width` | INTEGER | Cropped image width in pixels |
| `image_height` | INTEGER | Cropped image height in pixels |
| `file_size_bytes` | INTEGER | Size of `rgb.jpg` |
| `sha256` | VARCHAR(64) | SHA-256 hash of `rgb.jpg` |
| `derived_water_area_sq_km` | FLOAT | Water body surface area |
| `status` | VARCHAR(32) | `'ready'`, `'pending'`, `'failed'` |
| `metadata_json` | TEXT | Complete STAC and acquisition metadata JSON |
| `created_at` | DATETIME | Record creation timestamp |
| `updated_at` | DATETIME | Record update timestamp |

---

## 4. REST API Endpoints

### 1. `POST /api/v1/water-bodies/{wb_id}/visual-data/fetch`
Trigger water-body-centric visual satellite observation acquisition across a specified date range.

**Request Body:**
```json
{
  "from_date": "2023-01-01",
  "to_date": "2024-01-01",
  "image_count": 10
}
```

**Response:**
```json
{
  "water_body_id": "7047b147-600d-493d-aa15-adeefb12923b",
  "water_body_name": "Ambazari Lake",
  "from_date": "2023-01-01",
  "to_date": "2024-01-01",
  "requested_count": 10,
  "available_count": 10,
  "acquired_count": 8,
  "reused_count": 2,
  "failed_count": 0,
  "message": "Successfully acquired 8 and reused 2 observations distributed across 2023-01-01 to 2024-01-01.",
  "observations": [ ... ]
}
```

### 2. `GET /api/v1/water-bodies/{wb_id}/observations`
Returns chronological list of observations recorded for the specified water body.

### 3. `GET /api/v1/water-bodies/{wb_id}/observations/{obs_id}/image`
Directly serves the cropped high-resolution JPEG (`image/jpeg`) with path-traversal prevention and caching headers.

### 4. `GET /api/v1/analysis/water-bodies/{wb_id}`
Returns complete analysis data for the water body, including:
- Water body metadata
- Chronological timeline with relative water-extent changes
- Remote-sensing indicator proxies with explicit phase labeling

---

## 5. Frontend User Experience

1. **Navigation**:
   - `ANALYSIS (TIME-SERIES)` tab is accessible from the top navigation bar.
2. **Monitoring Map (`/map`)**:
   - Top status bar displays `🛰 FETCH VISUAL DATA` and `📊 ANALYSIS →` whenever a water body is selected.
   - Sidebar `LAYERS` tab provides water body metadata and action buttons to launch the acquisition modal or jump to analysis.
3. **Fetch Visual Data Modal**:
   - Select `from_date`, `to_date`, and `image_count` (with presets: 3, 5, 10, 15, 20).
   - Real-time progress feedback through STAC query, stratified distribution, and visual acquisition stages.
   - Direct button `VIEW IN ANALYSIS PAGE →` upon completion.
4. **Analysis Page (`/analysis`)**:
   - Water body selector dropdown.
   - Chronological observation cards with cloud cover badges, dimensions, and file sizes.
   - Modal image inspector for full-resolution view.
   - **Comparison Tool**:
     - Toggle between **Side-by-Side** and **Interactive Swipe Slider**.
     - Date selectors for Observation A and Observation B.
   - **Surface Water Extent Chart**:
     - SVG time series visualization illustrating surface area trend across observation dates.
   - **Remote Sensing Indicator Proxies**:
     - Turbidity / Sediment Proxy (`NDTI`)
     - Chlorophyll-a Proxy (`NDCI`)
     - Algal Activity Proxy (`FAI`)
     - Surface Spectral Anomaly (`Z-score`)
     - Explicitly badged `COMING IN ANALYSIS PHASE` without simulated or fake data.

