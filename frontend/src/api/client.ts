export interface HealthStatus {
  status: string;
  service: string;
  version: string;
}

export interface ApiError {
  error: {
    code: string;
    message: string;
  };
}

export interface WaterBody {
  id: string;
  name: string;
  normalized_name: string;
  country?: string | null;
  state_province?: string | null;
  district?: string | null;
  city?: string | null;
  source: string;
  source_id?: string | null;
  water_body_type?: string | null;
  description?: string | null;
  geometry_geojson?: string | null;
  geometry_hash?: string | null;
  area_sq_km?: number | null;
  centroid_lat?: number | null;
  centroid_lon?: number | null;
  min_lat?: number | null;
  min_lon?: number | null;
  max_lat?: number | null;
  max_lon?: number | null;
  is_active?: boolean;
  created_at?: string;
  updated_at?: string;
}

export interface WaterBodyListResponse {
  items: WaterBody[];
  total: number;
  limit: number;
  offset: number;
}

export interface StorageDatabaseCounts {
  water_bodies: number;
  satellite_scenes: number;
  satellite_assets: number;
  analysis_runs: number;
  cache_entries: number;
  size_bytes: number;
  size_formatted: string;
}

export interface StorageFilesystemSizes {
  satellite_data_bytes: number;
  satellite_data_formatted: string;
  processed_data_bytes: number;
  processed_data_formatted: string;
  cache_bytes: number;
  cache_formatted: string;
  total_bytes: number;
  total_formatted: string;
}

export interface StorageOrphansSummary {
  orphan_scene_directories_count: number;
  orphan_scene_directories: string[];
  missing_scene_directories_count: number;
  missing_scene_directories: string[];
}

export interface StorageStatus {
  database: {
    status: string;
    engine: string;
    url_type: string;
    size_bytes?: number;
    size_formatted?: string;
    water_bodies?: number;
    scenes?: number;
    assets?: number;
    analysis_runs?: number;
    cache_entries?: number;
  };
  directories: Record<string, string>;
  details: Record<
    string,
    {
      path: string;
      exists: boolean;
      is_directory: boolean;
      file_count: number;
    }
  >;
  database_counts?: StorageDatabaseCounts;
  local_storage?: StorageFilesystemSizes;
  orphans?: StorageOrphansSummary;
}

export interface StorageResetResponse {
  success: boolean;
  operation: string;
  message: string;
  database: {
    water_bodies_deleted: number;
    scenes_deleted: number;
    assets_deleted: number;
    analysis_runs_deleted: number;
    cache_entries_deleted: number;
  };
  filesystem: {
    files_deleted: number;
    bytes_freed: number;
    bytes_freed_formatted: string;
  };
}

export interface WaterBodyDiscoveryResult {
  provider: string;
  source_id: string;
  name: string;
  water_body_type?: string | null;
  country?: string | null;
  state_province?: string | null;
  district?: string | null;
  city?: string | null;
  description?: string | null;
  geometry_geojson?: string | null;
  geometry_hash?: string | null;
  min_lat?: number | null;
  min_lon?: number | null;
  max_lat?: number | null;
  max_lon?: number | null;
  centroid_lat?: number | null;
  centroid_lon?: number | null;
  area_sq_km?: number | null;
  source_metadata?: Record<string, any> | null;
}

export interface DiscoverySearchResponse {
  query: string;
  provider: string;
  results: WaterBodyDiscoveryResult[];
}

export interface ProviderStatus {
  name: string;
  enabled: boolean;
  status: string;
  description?: string | null;
}

export interface ProviderListResponse {
  providers: ProviderStatus[];
}

export interface GeocodedLocation {
  display_name: string;
  latitude: number;
  longitude: number;
  type?: string | null;
  boundingbox?: number[] | null;
}

export interface LocationSearchResponse {
  query: string;
  results: GeocodedLocation[];
}

export interface SearchCenter {
  latitude: number;
  longitude: number;
}

export interface SearchBoundingBox {
  min_lat: number;
  min_lon: number;
  max_lat: number;
  max_lon: number;
}

export interface AreaDiscoveryResponse {
  query_location?: string | null;
  center: SearchCenter;
  radius_km: number;
  bounding_box: SearchBoundingBox;
  total_discovered: number;
  results: WaterBodyDiscoveryResult[];
}

export interface BatchImportItemResult {
  source_id: string;
  name: string;
  status: 'imported' | 'already_registered' | 'failed';
  water_body?: WaterBody | null;
  error?: string | null;
}

export interface BatchImportResponse {
  total_requested: number;
  imported_count: number;
  already_existed_count: number;
  failed_count: number;
  results: BatchImportItemResult[];
}

// Revised Satellite Visual Data & Temporal Analysis Models
export interface VisualDataFetchRequest {
  from_date: string;
  to_date: string;
  image_count: number;
}

export interface AvailableObservationItem {
  observation_id: string;
  scene_id: string;
  id: string;
  satellite?: string;
  platform?: string | null;
  sensing_date: string;
  sensing_date_str: string;
  cloud_cover_percent: number;
  quality_label: 'VERY CLEAR' | 'CLEAR' | 'ACCEPTABLE' | 'HIGH CLOUD';
  is_high_cloud: boolean;
  already_acquired?: boolean;
  is_already_available: boolean;
  existing_observation_id?: string | null;
  existing_image_url?: string | null;
  thumbnail_url?: string | null;
  file_size_bytes?: number | null;
}

export interface AvailableObservationsResponse {
  water_body_id: string;
  water_body_name: string;
  from_date: string;
  to_date: string;
  max_cloud: number;
  include_high_cloud: boolean;
  total_found: number;
  items: AvailableObservationItem[];
}

export interface FetchSelectedVisualDataRequest {
  observation_ids: string[];
}

export interface VisualAcquisitionJobError {
  observation_id: string;
  error: string;
}

export interface VisualAcquisitionJobResponse {
  job_id: string;
  water_body_id: string;
  status: 'queued' | 'running' | 'completed' | 'failed';
  current_stage: 'QUEUED' | 'SEARCHING' | 'READING AOI' | 'COMPOSITING RGB' | 'SAVING' | 'COMPLETED' | 'FAILED' | string;
  current_observation_id?: string | null;
  current_scene_id?: string | null;
  current_index?: number;
  total: number;
  completed: number;
  reused?: number;
  failed: number;
  percent: number;
  details?: string | null;
  message: string;
  results: SatelliteObservation[];
  errors: VisualAcquisitionJobError[];
  created_at: string;
  updated_at: string;
}

export interface SatelliteObservation {
  id: string;
  water_body_id: string;
  satellite: string;
  provider: string;
  collection: string;
  external_scene_id: string;
  sensing_date: string;
  cloud_cover_percent?: number | null;
  aoi_bounds?: string | null;
  aoi_geojson?: string | null;
  local_visual_path: string;
  image_url?: string;
  image_width?: number | null;
  image_height?: number | null;
  file_size_bytes?: number | null;
  sha256?: string | null;
  derived_water_area_sq_km?: number | null;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface VisualDataFetchResponse {
  water_body_id: string;
  water_body_name: string;
  from_date: string;
  to_date: string;
  requested_count: number;
  available_count: number;
  acquired_count: number;
  reused_count: number;
  failed_count: number;
  message: string;
  observations: SatelliteObservation[];
}

export interface ObservationTimelineItem {
  id: string;
  water_body_id: string;
  external_scene_id: string;
  sensing_date: string;
  sensing_date_str: string;
  cloud_cover_percent?: number | null;
  quality_label?: string | null;
  image_url: string;
  file_size_bytes?: number | null;
  image_width?: number | null;
  image_height?: number | null;
  water_extent_sq_km?: number | null;
  change_from_previous_sq_km?: number | null;
  status: string;
  is_extent_measured?: boolean;
  is_demo_extent?: boolean;
  registered_area_sq_km?: number | null;
  aoi_bounds?: string | null;
  aoi_geojson?: string | null;
}

export interface IndicatorPlaceholder {
  id: string;
  label: string;
  description: string;
  status: string;
  message: string;
  unit?: string | null;
}

export interface TemporalAnalysisResponse {
  water_body_id: string;
  water_body_name: string;
  country?: string | null;
  area_sq_km?: number | null;
  total_observations: number;
  from_date?: string | null;
  to_date?: string | null;
  timeline: ObservationTimelineItem[];
  indicators: Record<string, IndicatorPlaceholder>;
}

// Phase 3: Satellite STAC Models
export interface NormalizedAsset {
  asset_key: string;
  asset_type?: string | null;
  remote_url: string;
  mime_type?: string | null;
  file_size_bytes?: number | null;
}

export interface NormalizedScene {
  provider: string;
  collection: string;
  external_scene_id: string;
  product_id?: string | null;
  sensing_start: string;
  sensing_end?: string | null;
  cloud_cover_percent?: number | null;
  processing_level?: string | null;
  bbox?: number[] | null;
  footprint_geojson?: Record<string, any> | null;
  assets: Record<string, NormalizedAsset>;
  score?: number | null;
}

export interface SceneSearchResponse {
  water_body_id: string;
  provider: string;
  collection: string;
  results: NormalizedScene[];
}

export interface AssetAcquisitionStatus {
  asset_key: string;
  status: string;
  size_bytes?: number | null;
  sha256?: string | null;
  local_path?: string | null;
  error_message?: string | null;
}

export interface SceneAcquisitionResponse {
  scene_id: string;
  external_scene_id: string;
  status: string;
  downloaded_assets: number;
  failed_assets: number;
  already_present_assets: number;
  assets: AssetAcquisitionStatus[];
}

export const BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

export function resolveApiUrl(url?: string | null): string {
  if (!url) return '';
  if (url.startsWith('http://') || url.startsWith('https://')) return url;
  const cleanPath = url.startsWith('/') ? url : `/${url}`;
  return `${BASE_URL}${cleanPath}`;
}

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let errorMsg = `Server responded with status ${response.status}`;
    try {
      const errData: ApiError = await response.json();
      if (errData?.error?.message) {
        errorMsg = errData.error.message;
      }
    } catch {
      // Fallback
    }
    throw new Error(errorMsg);
  }
  return response.json();
}

export async function checkHealth(): Promise<HealthStatus> {
  const response = await fetch(`${BASE_URL}/api/v1/health`, {
    headers: { 'Accept': 'application/json' },
  });
  return handleResponse<HealthStatus>(response);
}

export async function getStorageStatus(): Promise<StorageStatus> {
  const response = await fetch(`${BASE_URL}/api/v1/storage/status`, {
    headers: { 'Accept': 'application/json' },
  });
  return handleResponse<StorageStatus>(response);
}

export async function clearCache(): Promise<StorageResetResponse> {
  const response = await fetch(`${BASE_URL}/api/v1/storage/clear/cache`, {
    method: 'POST',
    headers: { 'Accept': 'application/json' },
  });
  return handleResponse<StorageResetResponse>(response);
}

export async function clearProcessedData(): Promise<StorageResetResponse> {
  const response = await fetch(`${BASE_URL}/api/v1/storage/clear/processed`, {
    method: 'POST',
    headers: { 'Accept': 'application/json' },
  });
  return handleResponse<StorageResetResponse>(response);
}

export async function clearSatelliteData(): Promise<StorageResetResponse> {
  const response = await fetch(`${BASE_URL}/api/v1/storage/clear/satellite`, {
    method: 'POST',
    headers: { 'Accept': 'application/json' },
  });
  return handleResponse<StorageResetResponse>(response);
}

export async function resetProjectData(): Promise<StorageResetResponse> {
  const response = await fetch(`${BASE_URL}/api/v1/storage/reset`, {
    method: 'POST',
    headers: { 'Accept': 'application/json' },
  });
  return handleResponse<StorageResetResponse>(response);
}

export async function listWaterBodies(limit = 50, offset = 0): Promise<WaterBodyListResponse> {
  const response = await fetch(`${BASE_URL}/api/v1/water-bodies?limit=${limit}&offset=${offset}`, {
    headers: { 'Accept': 'application/json' },
  });
  return handleResponse<WaterBodyListResponse>(response);
}

export async function createWaterBody(data: {
  name: string;
  country?: string;
  state_province?: string;
  source?: string;
  source_id?: string;
  area_sq_km?: number;
}): Promise<WaterBody> {
  const response = await fetch(`${BASE_URL}/api/v1/water-bodies`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Accept': 'application/json',
    },
    body: JSON.stringify(data),
  });
  return handleResponse<WaterBody>(response);
}

export async function searchDiscoveredWaterBodies(
  query: string,
  limit = 10,
  provider?: string
): Promise<DiscoverySearchResponse> {
  const params = new URLSearchParams({ q: query, limit: String(limit) });
  if (provider) {
    params.append('provider', provider);
  }
  const response = await fetch(`${BASE_URL}/api/v1/discovery/water-bodies/search?${params.toString()}`, {
    headers: { 'Accept': 'application/json' },
  });
  return handleResponse<DiscoverySearchResponse>(response);
}

export async function searchLocation(query: string, limit = 5): Promise<LocationSearchResponse> {
  const params = new URLSearchParams({ q: query, limit: String(limit) });
  const response = await fetch(`${BASE_URL}/api/v1/discovery/location/search?${params.toString()}`, {
    headers: { 'Accept': 'application/json' },
  });
  return handleResponse<LocationSearchResponse>(response);
}

export async function discoverWaterBodiesByArea(
  latitude: number,
  longitude: number,
  radiusKm = 1.0,
  limit = 30,
  queryLocation?: string
): Promise<AreaDiscoveryResponse> {
  const params = new URLSearchParams({
    latitude: String(latitude),
    longitude: String(longitude),
    radius_km: String(radiusKm),
    limit: String(limit),
  });
  if (queryLocation) {
    params.set('query_location', queryLocation);
  }
  const response = await fetch(`${BASE_URL}/api/v1/discovery/water-bodies/area?${params.toString()}`, {
    headers: { 'Accept': 'application/json' },
  });
  return handleResponse<AreaDiscoveryResponse>(response);
}

export async function importDiscoveredWaterBody(
  result: WaterBodyDiscoveryResult
): Promise<WaterBody> {
  const response = await fetch(`${BASE_URL}/api/v1/discovery/water-bodies/import`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Accept': 'application/json',
    },
    body: JSON.stringify(result),
  });
  return handleResponse<WaterBody>(response);
}

export async function importWaterBodiesBatch(
  waterBodies: WaterBodyDiscoveryResult[]
): Promise<BatchImportResponse> {
  const response = await fetch(`${BASE_URL}/api/v1/discovery/water-bodies/import-batch`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Accept': 'application/json',
    },
    body: JSON.stringify({ water_bodies: waterBodies }),
  });
  return handleResponse<BatchImportResponse>(response);
}

export async function getDiscoveryProviders(): Promise<ProviderListResponse> {
  const response = await fetch(`${BASE_URL}/api/v1/discovery/providers`, {
    headers: { 'Accept': 'application/json' },
  });
  return handleResponse<ProviderListResponse>(response);
}

// Satellite API
export async function searchSatelliteScenes(
  waterBodyId?: string,
  startDate?: string,
  endDate?: string,
  maxCloudCover = 30,
  limit = 10,
  bbox?: string
): Promise<SceneSearchResponse> {
  const params = new URLSearchParams({
    max_cloud_cover: String(maxCloudCover),
    limit: String(limit),
  });
  if (waterBodyId) params.append('water_body_id', waterBodyId);
  if (bbox) params.append('bbox', bbox);
  if (startDate) params.append('start_date', startDate);
  if (endDate) params.append('end_date', endDate);

  const response = await fetch(`${BASE_URL}/api/v1/satellite/scenes/search?${params.toString()}`, {
    headers: { 'Accept': 'application/json' },
  });
  return handleResponse<SceneSearchResponse>(response);
}

export async function acquireSceneAssets(
  externalSceneId: string,
  assets: string[]
): Promise<SceneAcquisitionResponse> {
  const response = await fetch(`${BASE_URL}/api/v1/satellite/scenes/${encodeURIComponent(externalSceneId)}/acquire`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Accept': 'application/json',
    },
    body: JSON.stringify({ assets }),
  });
  return handleResponse<SceneAcquisitionResponse>(response);
}

// Map & Raster API (Phase 4)
export interface MapGeoBounds {
  west: number;
  south: number;
  east: number;
  north: number;
}

export interface MapSceneItem {
  scene_id: string;
  external_scene_id: string;
  provider: string;
  collection: string;
  sensing_start: string;
  cloud_cover_percent?: number | null;
  status: string;
  footprint?: any;
  bbox?: number[] | null;
  downloaded_assets: string[];
  has_rgb: boolean;
  covers_water_body?: boolean;
}

export interface SceneRasterMetadata {
  scene_id: string;
  external_scene_id: string;
  provider: string;
  collection: string;
  sensing_start: string;
  cloud_cover_percent?: number | null;
  crs?: string | null;
  geographic_bounds?: MapGeoBounds | null;
  native_bounds?: Record<string, any> | null;
  available_assets: Array<{
    asset_key: string;
    asset_type?: string | null;
    file_size_bytes?: number | null;
    crs?: string | null;
    width?: number | null;
    height?: number | null;
    resolution_meters?: number | null;
    nodata?: number | null;
    is_downloaded: boolean;
  }>;
  rgb_available: boolean;
  rgb_cached: boolean;
  image_url?: string | null;
}

export interface RGBVisualizationData {
  scene_id: string;
  external_scene_id: string;
  water_body_id?: string | null;
  is_focused?: boolean;
  crs: string;
  source_crs?: string;
  resolution_m?: number;
  bands?: string[];
  sensing_date?: string | null;
  bounds: MapGeoBounds;
  width: number;
  height: number;
  image_url: string;
  cached: boolean;
  description: string;
}

export async function getWaterBodiesGeoJson(): Promise<any> {
  const response = await fetch(`${BASE_URL}/api/v1/map/water-bodies/geojson`, {
    headers: { 'Accept': 'application/json' },
  });
  return handleResponse<any>(response);
}

export async function getMapScenes(waterBodyId: string): Promise<MapSceneItem[]> {
  const response = await fetch(`${BASE_URL}/api/v1/map/scenes?water_body_id=${encodeURIComponent(waterBodyId)}`, {
    headers: { 'Accept': 'application/json' },
  });
  return handleResponse<MapSceneItem[]>(response);
}

export async function getSceneRasterMetadata(sceneId: string): Promise<SceneRasterMetadata> {
  const response = await fetch(`${BASE_URL}/api/v1/map/scenes/${encodeURIComponent(sceneId)}/metadata`, {
    headers: { 'Accept': 'application/json' },
  });
  return handleResponse<SceneRasterMetadata>(response);
}

export async function getSceneRGBVisualization(
  sceneId: string,
  waterBodyId?: string,
  forceRegenerate = false,
  bbox?: [number, number, number, number] | string,
  paddingPercent?: number,
): Promise<RGBVisualizationData> {
  const params = new URLSearchParams();
  if (waterBodyId) params.append('water_body_id', waterBodyId);
  if (forceRegenerate) params.append('force_regenerate', 'true');
  if (bbox) {
    const bboxStr = Array.isArray(bbox) ? bbox.join(',') : bbox;
    params.append('bbox', bboxStr);
  }
  if (paddingPercent != null) params.append('padding_percent', String(paddingPercent));
  const qs = params.toString() ? `?${params.toString()}` : '';
  const response = await fetch(`${BASE_URL}/api/v1/map/scenes/${encodeURIComponent(sceneId)}/rgb${qs}`, {
    headers: { 'Accept': 'application/json' },
  });
  return handleResponse<RGBVisualizationData>(response);
}

export function getSceneRGBImageUrl(
  sceneId: string,
  waterBodyId?: string,
  bbox?: [number, number, number, number] | string,
  paddingPercent?: number,
): string {
  const params = new URLSearchParams();
  if (waterBodyId) params.append('water_body_id', waterBodyId);
  if (bbox) {
    const bboxStr = Array.isArray(bbox) ? bbox.join(',') : bbox;
    params.append('bbox', bboxStr);
  }
  if (paddingPercent != null) params.append('padding_percent', String(paddingPercent));
  const qs = params.toString() ? `?${params.toString()}` : '';
  return `${BASE_URL}/api/v1/map/scenes/${encodeURIComponent(sceneId)}/rgb/image${qs}`;
}

// Processing API (Phase 5)
export interface CloudMaskMetadata {
  source_layer: string;
  masked_classes: number[];
  total_pixels: number;
  valid_pixels: number;
  cloud_shadow_pixels: number;
  valid_pixel_percentage: number;
  cloud_shadow_percentage: number;
}

export interface WaterDetectionMetadata {
  method: string;
  threshold: number;
  source_bands: string[];
  total_pixels: number;
  valid_pixels_evaluated: number;
  water_pixels: number;
  water_extent_percentage_of_valid: number;
  water_extent_percentage_of_total: number;
  estimated_water_area_sq_km?: number | null;
}

export interface ProcessingStatusResponse {
  scene_id: string;
  external_scene_id: string;
  status: 'ready' | 'unprocessed' | 'missing_assets';
  cloud_mask_available: boolean;
  water_mask_available: boolean;
  cloud_mask?: CloudMaskMetadata | null;
  water_detection?: WaterDetectionMetadata | null;
  source_bands_present: string[];
  missing_required_bands: string[];
  created_at?: string | null;
  cloud_mask_image_url?: string | null;
  water_mask_image_url?: string | null;
}

export interface MaskVisualizationResponse {
  scene_id: string;
  mask_type: string;
  crs: string;
  bounds: MapGeoBounds;
  width: number;
  height: number;
  image_url: string;
  cached: boolean;
  description: string;
}

export async function getProcessingStatus(sceneId: string): Promise<ProcessingStatusResponse> {
  const response = await fetch(`${BASE_URL}/api/v1/processing/scenes/${encodeURIComponent(sceneId)}`, {
    headers: { 'Accept': 'application/json' },
  });
  return handleResponse<ProcessingStatusResponse>(response);
}

export async function runSceneProcessing(sceneId: string, threshold = 0.0, force = false): Promise<ProcessingStatusResponse> {
  const response = await fetch(`${BASE_URL}/api/v1/processing/scenes/${encodeURIComponent(sceneId)}?threshold=${threshold}&force_recompute=${force}`, {
    method: 'POST',
    headers: { 'Accept': 'application/json' },
  });
  return handleResponse<ProcessingStatusResponse>(response);
}

export async function getCloudMaskVisualization(
  sceneId: string,
  waterBodyId?: string,
  bbox?: [number, number, number, number] | string,
  paddingPercent?: number,
): Promise<MaskVisualizationResponse> {
  const params = new URLSearchParams();
  if (waterBodyId) params.append('water_body_id', waterBodyId);
  if (bbox) {
    const bboxStr = Array.isArray(bbox) ? bbox.join(',') : bbox;
    params.append('bbox', bboxStr);
  }
  if (paddingPercent != null) params.append('padding_percent', String(paddingPercent));
  const qs = params.toString() ? `?${params.toString()}` : '';
  const response = await fetch(`${BASE_URL}/api/v1/processing/scenes/${encodeURIComponent(sceneId)}/cloud-mask${qs}`, {
    headers: { 'Accept': 'application/json' },
  });
  return handleResponse<MaskVisualizationResponse>(response);
}

export async function getWaterMaskVisualization(
  sceneId: string,
  waterBodyId?: string,
  bbox?: [number, number, number, number] | string,
  paddingPercent?: number,
): Promise<MaskVisualizationResponse> {
  const params = new URLSearchParams();
  if (waterBodyId) params.append('water_body_id', waterBodyId);
  if (bbox) {
    const bboxStr = Array.isArray(bbox) ? bbox.join(',') : bbox;
    params.append('bbox', bboxStr);
  }
  if (paddingPercent != null) params.append('padding_percent', String(paddingPercent));
  const qs = params.toString() ? `?${params.toString()}` : '';
  const response = await fetch(`${BASE_URL}/api/v1/processing/scenes/${encodeURIComponent(sceneId)}/water-mask${qs}`, {
    headers: { 'Accept': 'application/json' },
  });
  return handleResponse<MaskVisualizationResponse>(response);
}

export function getCloudMaskImageUrl(
  sceneId: string,
  waterBodyId?: string,
  bbox?: [number, number, number, number] | string,
  paddingPercent?: number,
): string {
  const params = new URLSearchParams();
  if (waterBodyId) params.append('water_body_id', waterBodyId);
  if (bbox) {
    const bboxStr = Array.isArray(bbox) ? bbox.join(',') : bbox;
    params.append('bbox', bboxStr);
  }
  if (paddingPercent != null) params.append('padding_percent', String(paddingPercent));
  const qs = params.toString() ? `?${params.toString()}` : '';
  return `${BASE_URL}/api/v1/processing/scenes/${encodeURIComponent(sceneId)}/cloud-mask/image${qs}`;
}

export function getWaterMaskImageUrl(
  sceneId: string,
  waterBodyId?: string,
  bbox?: [number, number, number, number] | string,
  paddingPercent?: number,
): string {
  const params = new URLSearchParams();
  if (waterBodyId) params.append('water_body_id', waterBodyId);
  if (bbox) {
    const bboxStr = Array.isArray(bbox) ? bbox.join(',') : bbox;
    params.append('bbox', bboxStr);
  }
  if (paddingPercent != null) params.append('padding_percent', String(paddingPercent));
  const qs = params.toString() ? `?${params.toString()}` : '';
  return `${BASE_URL}/api/v1/processing/scenes/${encodeURIComponent(sceneId)}/water-mask/image${qs}`;
}

// ─── Revised Visual Data & Temporal Analysis APIs ─────────────────────────────

export async function fetchVisualData(
  waterBodyId: string,
  request: VisualDataFetchRequest,
): Promise<VisualDataFetchResponse> {
  const response = await fetch(`${BASE_URL}/api/v1/water-bodies/${encodeURIComponent(waterBodyId)}/visual-data/fetch`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Accept': 'application/json',
    },
    body: JSON.stringify(request),
  });
  return handleResponse<VisualDataFetchResponse>(response);
}

export async function getWaterBodyObservations(
  waterBodyId: string,
  fromDate?: string,
  toDate?: string,
): Promise<SatelliteObservation[]> {
  const params = new URLSearchParams();
  if (fromDate) params.append('from_date', fromDate);
  if (toDate) params.append('to_date', toDate);
  const qs = params.toString() ? `?${params.toString()}` : '';

  const response = await fetch(`${BASE_URL}/api/v1/water-bodies/${encodeURIComponent(waterBodyId)}/observations${qs}`, {
    headers: { 'Accept': 'application/json' },
  });
  return handleResponse<SatelliteObservation[]>(response);
}

export function getObservationImageUrl(waterBodyId: string, observationId: string): string {
  return `${BASE_URL}/api/v1/water-bodies/${encodeURIComponent(waterBodyId)}/observations/${encodeURIComponent(observationId)}/image`;
}

export async function getWaterBodyTemporalAnalysis(
  waterBodyId: string,
  fromDate?: string,
  toDate?: string,
): Promise<TemporalAnalysisResponse> {
  const params = new URLSearchParams();
  if (fromDate) params.append('from_date', fromDate);
  if (toDate) params.append('to_date', toDate);
  const qs = params.toString() ? `?${params.toString()}` : '';

  const response = await fetch(`${BASE_URL}/api/v1/analysis/water-bodies/${encodeURIComponent(waterBodyId)}${qs}`, {
    headers: { 'Accept': 'application/json' },
  });
  return handleResponse<TemporalAnalysisResponse>(response);
}

export async function getAvailableVisualObservations(
  waterBodyId: string,
  params: {
    from_date: string;
    to_date: string;
    max_cloud?: number;
    include_high_cloud?: boolean;
    sort?: 'newest' | 'oldest' | 'lowest_cloud';
  },
): Promise<AvailableObservationsResponse> {
  const q = new URLSearchParams();
  q.append('from_date', params.from_date);
  q.append('to_date', params.to_date);
  if (params.max_cloud != null) q.append('max_cloud', String(params.max_cloud));
  if (params.include_high_cloud != null) q.append('include_high_cloud', String(params.include_high_cloud));
  if (params.sort) q.append('sort', params.sort);

  const response = await fetch(`${BASE_URL}/api/v1/water-bodies/${encodeURIComponent(waterBodyId)}/visual-data/available?${q.toString()}`, {
    headers: { 'Accept': 'application/json' },
  });
  return handleResponse<AvailableObservationsResponse>(response);
}

export async function fetchSelectedVisualData(
  waterBodyId: string,
  request: FetchSelectedVisualDataRequest,
): Promise<VisualAcquisitionJobResponse> {
  const response = await fetch(`${BASE_URL}/api/v1/water-bodies/${encodeURIComponent(waterBodyId)}/visual-data/fetch-selected`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Accept': 'application/json',
    },
    body: JSON.stringify(request),
  });
  return handleResponse<VisualAcquisitionJobResponse>(response);
}

export async function getVisualDataJobStatus(
  waterBodyId: string,
  jobId: string,
): Promise<VisualAcquisitionJobResponse> {
  const response = await fetch(`${BASE_URL}/api/v1/water-bodies/${encodeURIComponent(waterBodyId)}/visual-data/jobs/${encodeURIComponent(jobId)}`, {
    headers: { 'Accept': 'application/json' },
  });
  return handleResponse<VisualAcquisitionJobResponse>(response);
}

// ─── Spectral Analysis Interfaces & Functions ──────────────────────────────

export type SpectralIndicatorId = 'ndti' | 'ndci' | 'fai' | 'anomaly';

export interface BandAvailabilityInfo {
  observation_id: string;
  external_scene_id: string;
  indicator: string;
  required_bands: string[];
  available_bands: string[];
  missing_bands: string[];
  is_ready: boolean;
  message: string;
}

export interface SpectralAnalysisResult {
  id: string;
  water_body_id: string;
  water_body_name: string;
  observation_id: string;
  external_scene_id: string;
  sensing_date: string;
  sensing_date_str: string;
  indicator: string;
  indicator_label: string;
  index_name: string;
  value: number | null;
  mean: number | null;
  median: number | null;
  std: number | null;
  minimum: number | null;
  maximum: number | null;
  valid_pixel_count: number;
  total_water_pixels: number;
  valid_pixel_percent: number;
  cloud_pixel_percent: number;
  quality: 'GOOD' | 'LIMITED' | 'INSUFFICIENT';
  quality_reason?: string | null;
  classification: string;
  classification_desc: string;
  baseline_mean?: number | null;
  baseline_std?: number | null;
  anomaly_score?: number | null;
  preview_url?: string | null;
  formula: string;
  disclaimer: string;
  required_bands: string[];
  available_bands: string[];
  missing_bands: string[];
  formula_version: string;
  processing_version: string;
  is_cached: boolean;
  created_at: string;
}

export interface MultiIndicatorSummary {
  water_body_id: string;
  observation_id: string;
  sensing_date_str: string;
  indicators: Record<string, SpectralAnalysisResult | null>;
}

export interface TimeSeriesSpectralResponse {
  water_body_id: string;
  water_body_name: string;
  indicator: string;
  total_requested: number;
  total_analyzed: number;
  results: SpectralAnalysisResult[];
}

export async function checkBandAvailability(
  waterBodyId: string,
  observationId: string,
  indicator: SpectralIndicatorId,
): Promise<BandAvailabilityInfo> {
  const response = await fetch(
    `${BASE_URL}/api/v1/water-bodies/${encodeURIComponent(waterBodyId)}/spectral/bands?observation_id=${encodeURIComponent(observationId)}&indicator=${encodeURIComponent(indicator)}`,
    { headers: { 'Accept': 'application/json' } }
  );
  return handleResponse<BandAvailabilityInfo>(response);
}

export async function analyzeSpectralIndicator(
  waterBodyId: string,
  request: {
    observation_id: string;
    indicator: SpectralIndicatorId;
    force_recompute?: boolean;
  },
): Promise<SpectralAnalysisResult> {
  const response = await fetch(
    `${BASE_URL}/api/v1/water-bodies/${encodeURIComponent(waterBodyId)}/spectral/analyze`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
      },
      body: JSON.stringify(request),
    }
  );
  return handleResponse<SpectralAnalysisResult>(response);
}

export function getSpectralPreviewImageUrl(
  waterBodyId: string,
  resultId: string,
): string {
  return `${BASE_URL}/api/v1/water-bodies/${encodeURIComponent(waterBodyId)}/spectral/results/${encodeURIComponent(resultId)}/image`;
}

export async function getSpectralSummary(
  waterBodyId: string,
  observationId: string,
): Promise<MultiIndicatorSummary> {
  const response = await fetch(
    `${BASE_URL}/api/v1/water-bodies/${encodeURIComponent(waterBodyId)}/spectral/summary?observation_id=${encodeURIComponent(observationId)}`,
    { headers: { 'Accept': 'application/json' } }
  );
  return handleResponse<MultiIndicatorSummary>(response);
}

export async function calculateTimeSeriesSpectral(
  waterBodyId: string,
  request: {
    observation_ids: string[];
    indicator: SpectralIndicatorId;
    force_recompute?: boolean;
  },
): Promise<TimeSeriesSpectralResponse> {
  const response = await fetch(
    `${BASE_URL}/api/v1/water-bodies/${encodeURIComponent(waterBodyId)}/spectral/time-series`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
      },
      body: JSON.stringify(request),
    }
  );
  return handleResponse<TimeSeriesSpectralResponse>(response);
}

export interface AIStatusResponse {
  enabled: boolean;
  configured: boolean;
  model: string;
  provider: string;
}

export interface AIAnalysisRequest {
  water_body_id?: string | null;
  observation_id?: string | null;
  question: string;
}

export interface AIAnalysisResponse {
  answer: string;
  water_body_name?: string | null;
  observation_date?: string | null;
  model: string;
  disclaimer: string;
}

export interface TelegramStatusResponse {
  enabled: boolean;
  configured: boolean;
  connected: boolean;
  bot_username?: string | null;
}

export async function getAIStatus(): Promise<AIStatusResponse> {
  const response = await fetch(`${BASE_URL}/api/v1/ai/status`, {
    headers: { 'Accept': 'application/json' },
  });
  return handleResponse<AIStatusResponse>(response);
}

export async function askAIAnalysis(request: AIAnalysisRequest): Promise<AIAnalysisResponse> {
  const response = await fetch(`${BASE_URL}/api/v1/ai/analyze`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Accept': 'application/json',
    },
    body: JSON.stringify(request),
  });
  return handleResponse<AIAnalysisResponse>(response);
}

export async function getTelegramStatus(): Promise<TelegramStatusResponse> {
  const response = await fetch(`${BASE_URL}/api/v1/telegram/status`, {
    headers: { 'Accept': 'application/json' },
  });
  return handleResponse<TelegramStatusResponse>(response);
}
