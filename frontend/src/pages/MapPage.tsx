import React, { useEffect, useState, useRef, useCallback, useMemo } from 'react';
import {
  MapContainer,
  TileLayer,
  GeoJSON,
  ImageOverlay,
  useMap,
  Rectangle,
  Circle,
  CircleMarker,
  Popup,
  useMapEvents,
} from 'react-leaflet';
import type L from 'leaflet';
import {
  getWaterBodiesGeoJson,
  getMapScenes,
  getSceneRasterMetadata,
  getSceneRGBVisualization,
  resolveApiUrl,
  getProcessingStatus,
  runSceneProcessing,
  getCloudMaskVisualization,
  getWaterMaskVisualization,
  getCloudMaskImageUrl,
  getWaterMaskImageUrl,
  searchSatelliteScenes,
  acquireSceneAssets,
  searchLocation,
  discoverWaterBodiesByArea,
  importDiscoveredWaterBody,
  importWaterBodiesBatch,
  MapSceneItem,
  SceneRasterMetadata,
  RGBVisualizationData,
  ProcessingStatusResponse,
  MaskVisualizationResponse,
  WaterBodyDiscoveryResult,
  AreaDiscoveryResponse,
  GeocodedLocation,
  WaterBody,
} from '../api/client';
import { FetchVisualDataModal } from '../components/FetchVisualDataModal';
import { CompactWeatherBadge } from '../components/CompactWeatherBadge';

// ─── LocalStorage helpers ─────────────────────────────────────────────────────
const LS_WB_KEY = 'jalnetra_selected_wb_id';

function saveWbToStorage(id: string) {
  try { localStorage.setItem(LS_WB_KEY, id); } catch { /* ignore */ }
}
function loadWbFromStorage(): string | null {
  try { return localStorage.getItem(LS_WB_KEY); } catch { return null; }
}

// ─── FitBoundsHelper ──────────────────────────────────────────────────────────
interface FitBoundsHelperProps {
  bounds: L.LatLngBoundsExpression | null;
  trigger: number; // increment to force re-fit even when bounds object is the same
}

const FitBoundsHelper: React.FC<FitBoundsHelperProps> = ({ bounds, trigger }) => {
  const map = useMap();
  useEffect(() => {
    if (!bounds) return;
    try { map.fitBounds(bounds as any, { padding: [35, 35], maxZoom: 15 }); }
    catch (err) { console.warn('fitBounds error:', err); }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bounds, trigger, map]);
  return null;
};

// ─── Manual AOI Draw Handler ──────────────────────────────────────────────────
interface DrawAoiHandlerProps {
  active: boolean;
  onComplete: (bounds: [[number, number], [number, number]]) => void;
}

const DrawAoiHandler: React.FC<DrawAoiHandlerProps> = ({ active, onComplete }) => {
  const startRef = useRef<L.LatLng | null>(null);
  const [rect, setRect] = useState<[[number, number], [number, number]] | null>(null);

  const map = useMapEvents({
    mousedown(e) {
      if (!active) return;
      startRef.current = e.latlng;
      setRect(null);
      map.dragging.disable();
    },
    mousemove(e) {
      if (!active || !startRef.current) return;
      const s = startRef.current;
      setRect([[s.lat, s.lng], [e.latlng.lat, e.latlng.lng]]);
    },
    mouseup(e) {
      if (!active || !startRef.current) return;
      map.dragging.enable();
      const s = startRef.current;
      const result: [[number, number], [number, number]] = [
        [Math.min(s.lat, e.latlng.lat), Math.min(s.lng, e.latlng.lng)],
        [Math.max(s.lat, e.latlng.lat), Math.max(s.lng, e.latlng.lng)],
      ];
      onComplete(result);
      startRef.current = null;
      setRect(null);
    },
  });
  void map; // suppress unused warning

  if (!rect) return null;
  return (
    <Rectangle
      bounds={rect}
      pathOptions={{ color: '#f59e0b', weight: 2, dashArray: '6 4', fillOpacity: 0.1 }}
    />
  );
};

// ─── FloatingPanel ─────────────────────────────────────────────────────────────
interface FloatingPanelProps {
  children: React.ReactNode;
  style?: React.CSSProperties;
}

const FloatingPanel: React.FC<FloatingPanelProps> = ({ children, style }) => {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const stop = (e: Event) => e.stopPropagation();
    el.addEventListener('wheel', stop, { passive: false });
    el.addEventListener('mousedown', stop);
    el.addEventListener('mouseup', stop);
    el.addEventListener('dblclick', stop);
    el.addEventListener('touchstart', stop, { passive: true });
    el.addEventListener('touchmove', stop, { passive: true });
    el.addEventListener('pointerdown', stop);
    return () => {
      el.removeEventListener('wheel', stop);
      el.removeEventListener('mousedown', stop);
      el.removeEventListener('mouseup', stop);
      el.removeEventListener('dblclick', stop);
      el.removeEventListener('touchstart', stop);
      el.removeEventListener('touchmove', stop);
      el.removeEventListener('pointerdown', stop);
    };
  }, []);
  return <div ref={ref} style={style}>{children}</div>;
};

// ─── Types ─────────────────────────────────────────────────────────────────────
type AoiMode = 'auto' | 'manual';

interface OperationProgress {
  active: boolean;
  stage: string;
  detail?: string;
  percent?: number;
  error?: string | null;
}

interface PerSceneProcessing {
  status: ProcessingStatusResponse | null;
  cloudVis: MaskVisualizationResponse | null;
  waterVis: MaskVisualizationResponse | null;
  isProcessing: boolean;
  error: string | null;
}

export interface MapPageProps {
  onNavigateToAnalysis?: (waterBodyId?: string) => void;
}

// ─── MapPage ──────────────────────────────────────────────────────────────────
export const MapPage: React.FC<MapPageProps> = ({ onNavigateToAnalysis }) => {
  // Request identity tracker to completely eliminate async race conditions
  const requestIdRef = useRef<number>(0);
  const [opProgress, setOpProgress] = useState<OperationProgress | null>(null);

  // ── Vector data ──────────────────────────────────────────────────────────────
  const [geoJsonData, setGeoJsonData] = useState<any | null>(null);
  const [selectedWaterBodyId, setSelectedWaterBodyId] = useState<string>('');
  const [selectedWaterBodyProps, setSelectedWaterBodyProps] = useState<any | null>(null);
  const [isFetchVisualDataOpen, setIsFetchVisualDataOpen] = useState<boolean>(false);

  const selectedWaterBodyObj: WaterBody | null = useMemo(() => {
    if (!selectedWaterBodyId) return null;
    const p = selectedWaterBodyProps || {};
    return {
      id: selectedWaterBodyId,
      name: p.name || 'Selected Water Body',
      normalized_name: p.normalized_name || (p.name || '').toLowerCase(),
      country: p.country,
      state_province: p.state_province,
      district: p.district,
      city: p.city,
      source: p.source || 'osm',
      water_body_type: p.water_body_type,
      area_sq_km: p.area_sq_km,
      centroid_lat: p.centroid_lat,
      centroid_lon: p.centroid_lon,
    };
  }, [selectedWaterBodyId, selectedWaterBodyProps]);

  // ── Scenes ────────────────────────────────────────────────────────────────────
  const [scenes, setScenes] = useState<MapSceneItem[]>([]);
  const [selectedSceneId, setSelectedSceneId] = useState<string>('');
  const [selectedSceneItem, setSelectedSceneItem] = useState<MapSceneItem | null>(null);
  const [isAutoSelected, setIsAutoSelected] = useState<boolean>(true);
  const [sceneMetadata, setSceneMetadata] = useState<SceneRasterMetadata | null>(null);

  // ── RGB ───────────────────────────────────────────────────────────────────────
  const [rgbData, setRgbData] = useState<RGBVisualizationData | null>(null);
  const [isLoadingRgb, setIsLoadingRgb] = useState<boolean>(false);

  // ── Per-scene processing state ────────────────────────────────────────────────
  const [processingByScene, setProcessingByScene] = useState<Record<string, PerSceneProcessing>>({});

  // ── AOI ───────────────────────────────────────────────────────────────────────
  const [aoiMode, setAoiMode] = useState<AoiMode>('auto');
  const [autoPaddingPct, setAutoPaddingPct] = useState<number>(10);
  const [manualAoi, setManualAoi] = useState<[[number, number], [number, number]] | null>(null);
  const [isDrawingAoi, setIsDrawingAoi] = useState<boolean>(false);

  // ── Satellite refresh / acquire ───────────────────────────────────────────────
  const [isRefetchingScenes, setIsRefetchingScenes] = useState<boolean>(false);
  const [refetchError, setRefetchError] = useState<string | null>(null);
  const [acquiringSceneId, setAcquiringSceneId] = useState<string | null>(null);
  const [acquireMessage, setAcquireMessage] = useState<string | null>(null);

  // ── Layer controls ────────────────────────────────────────────────────────────
  const [showBaseMap, setShowBaseMap] = useState<boolean>(true);
  const [showWaterBodies, setShowWaterBodies] = useState<boolean>(true);
  const [showRasterExtent, setShowRasterExtent] = useState<boolean>(true);
  const [showSceneFootprint, setShowSceneFootprint] = useState<boolean>(false);
  const [showRgbImagery, setShowRgbImagery] = useState<boolean>(true);
  const [showCloudMask, setShowCloudMask] = useState<boolean>(false);
  const [showWaterMask, setShowWaterMask] = useState<boolean>(true);
  const [rasterOpacity, setRasterOpacity] = useState<number>(0.90);
  const [cloudMaskOpacity, setCloudMaskOpacity] = useState<number>(0.70);
  const [waterMaskOpacity, setWaterMaskOpacity] = useState<number>(0.85);

  // ── Map camera ────────────────────────────────────────────────────────────────
  const [targetBounds, setTargetBounds] = useState<L.LatLngBoundsExpression | null>(null);
  const [fitTrigger, setFitTrigger] = useState<number>(0);

  // ── UI ────────────────────────────────────────────────────────────────────────
  const [error, setError] = useState<string | null>(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState<boolean>(false);
  const [activeSidebarTab, setActiveSidebarTab] = useState<'discovery' | 'layers' | 'scenes' | 'aoi'>('layers');
  const [metricsCollapsed, setMetricsCollapsed] = useState<boolean>(false);

  // ── Discovery (Phase 2) ──────────────────────────────────────────────────────
  const [discoveryQuery, setDiscoveryQuery] = useState<string>('');
  const [discoveryRadiusKm, setDiscoveryRadiusKm] = useState<number>(1.0);
  const [isSearchingLocation, setIsSearchingLocation] = useState<boolean>(false);
  const [isDiscoveringArea, setIsDiscoveringArea] = useState<boolean>(false);
  const [isRegisteringWb, setIsRegisteringWb] = useState<boolean>(false);
  const [discoveryError, setDiscoveryError] = useState<string | null>(null);
  const [discoverySuccess, setDiscoverySuccess] = useState<string | null>(null);
  const [matchedLocations, setMatchedLocations] = useState<GeocodedLocation[]>([]);
  const [selectedLocation, setSelectedLocation] = useState<GeocodedLocation | null>(null);
  const [areaDiscoveryData, setAreaDiscoveryData] = useState<AreaDiscoveryResponse | null>(null);
  const [selectedDiscoveredWb, setSelectedDiscoveredWb] = useState<WaterBodyDiscoveryResult | null>(null);
  const [selectedForImportIds, setSelectedForImportIds] = useState<Set<string>>(new Set());
  const [registeredSourceIds, setRegisteredSourceIds] = useState<Set<string>>(new Set());

  // ── Derived per-scene data ────────────────────────────────────────────────────
  const currentProc: PerSceneProcessing = selectedSceneId
    ? (processingByScene[selectedSceneId] || { status: null, cloudVis: null, waterVis: null, isProcessing: false, error: null })
    : { status: null, cloudVis: null, waterVis: null, isProcessing: false, error: null };

  // ─── Helpers ──────────────────────────────────────────────────────────────────
  const formatSensingDate = (dateStr?: string | null): string => {
    if (!dateStr) return '';
    try {
      const d = new Date(dateStr);
      return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' });
    } catch {
      return dateStr;
    }
  };

  const computeBoundsFromProps = useCallback((properties: any, paddingPct = 0.10): L.LatLngBoundsExpression | null => {
    if (
      Array.isArray(properties?.bbox) &&
      properties.bbox.length === 4 &&
      properties.bbox.every((v: any) => typeof v === 'number' && !isNaN(v) && isFinite(v))
    ) {
      const [w, s, e, n] = properties.bbox;
      const padLat = Math.max((n - s) * paddingPct, 0.0001);
      const padLon = Math.max((e - w) * paddingPct, 0.0001);
      return [[s - padLat, w - padLon], [n + padLat, e + padLon]];
    }
    if (
      typeof properties?.centroid_lat === 'number' && isFinite(properties.centroid_lat) &&
      typeof properties?.centroid_lon === 'number' && isFinite(properties.centroid_lon)
    ) {
      return [
        [properties.centroid_lat - 0.01, properties.centroid_lon - 0.01],
        [properties.centroid_lat + 0.01, properties.centroid_lon + 0.01],
      ];
    }
    return null;
  }, []);

  const updateProcState = useCallback((sceneId: string, patch: Partial<PerSceneProcessing>) => {
    setProcessingByScene(prev => ({
      ...prev,
      [sceneId]: { ...(prev[sceneId] || { status: null, cloudVis: null, waterVis: null, isProcessing: false, error: null }), ...patch },
    }));
  }, []);

  // ─── Data loaders ─────────────────────────────────────────────────────────────
  const loadWaterBodies = useCallback(async () => {
    setError(null);
    try {
      const data = await getWaterBodiesGeoJson();
      setGeoJsonData(data);

      if (data?.features?.length > 0) {
        // Restore previous selection from localStorage
        const savedId = loadWbFromStorage();
        const savedFeature = savedId
          ? data.features.find((f: any) => f.properties.id === savedId)
          : null;
        const firstFeature = data.features[0];
        const target = savedFeature || firstFeature;
        // Use a ref to avoid stale closures - call select after data is set
        handleSelectWaterBody(target.properties.id, target.properties, data);
      } else {
        setSelectedWaterBodyId('');
        setSelectedWaterBodyProps(null);
        setSelectedSceneId('');
        setSelectedSceneItem(null);
        setSceneMetadata(null);
        setRgbData(null);
        setScenes([]);
        try { localStorage.removeItem(LS_WB_KEY); } catch { /* ignore */ }
        setActiveSidebarTab('discovery');
      }
    } catch (err: any) {
      setError(err.message || 'Failed to load water body map data');
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleSelectWaterBody = useCallback(async (wbId: string, props?: any, sourceGeoJson?: any) => {
    if (!wbId) return;
    const reqId = ++requestIdRef.current;
    setSelectedWaterBodyId(wbId);
    saveWbToStorage(wbId);

    // Reset scene-level state and overlays synchronously to isolate water body
    setSelectedSceneId('');
    setSelectedSceneItem(null);
    setSceneMetadata(null);
    setRgbData(null);
    setAcquireMessage(null);
    setRefetchError(null);
    setOpProgress(null);

    const currentData = sourceGeoJson || geoJsonData;
    const matchedFeature = currentData?.features?.find((f: any) => f.properties.id === wbId);
    const properties = props || matchedFeature?.properties;
    setSelectedWaterBodyProps(properties);

    // Fit map to water body
    const bounds = computeBoundsFromProps(properties, autoPaddingPct / 100);
    if (bounds) {
      setTargetBounds(bounds);
      setFitTrigger(t => t + 1);
    }

    // Load scenes strictly for this water body
    try {
      const sceneList = await getMapScenes(wbId);
      if (requestIdRef.current !== reqId) return; // Stale request discarded
      setScenes(sceneList);

      // Auto-select ONLY if a scene genuinely covers this water body
      const bestValidScene = sceneList.find(s => s.covers_water_body && s.has_rgb)
        || sceneList.find(s => s.covers_water_body);

      if (bestValidScene) {
        handleSelectScene(bestValidScene, wbId, true, reqId);
      } else {
        // Explicitly clear scene & imagery: Never reuse another water body's scene!
        setSelectedSceneId('');
        setSelectedSceneItem(null);
        setSceneMetadata(null);
        setRgbData(null);
      }
    } catch (err) {
      if (requestIdRef.current !== reqId) return;
      console.error('Failed to load scenes:', err);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [geoJsonData, autoPaddingPct, computeBoundsFromProps]);

  // ─── Phase 2: Sync registered water bodies source IDs ─────────────────────────
  useEffect(() => {
    if (geoJsonData?.features) {
      const ids = new Set<string>();
      geoJsonData.features.forEach((f: any) => {
        if (f.properties?.source_id) ids.add(String(f.properties.source_id));
      });
      setRegisteredSourceIds(ids);
    }
  }, [geoJsonData]);

  const isWbRegistered = useCallback((wb: WaterBodyDiscoveryResult) => {
    if (wb.source_id && registeredSourceIds.has(String(wb.source_id))) return true;
    if (!geoJsonData?.features) return false;
    return geoJsonData.features.some((f: any) =>
      (f.properties?.source_id && String(f.properties.source_id) === String(wb.source_id)) ||
      (f.properties?.name && wb.name && f.properties.name.trim().toLowerCase() === wb.name.trim().toLowerCase())
    );
  }, [registeredSourceIds, geoJsonData]);

  const handleExecuteAreaSearch = useCallback(async (overrideLoc?: GeocodedLocation, overrideRadius?: number) => {
    const query = discoveryQuery.trim();
    if (!overrideLoc && !query) {
      setDiscoveryError('Please enter a location name (e.g. Delhi, Pune, Nagpur, Ooty)');
      return;
    }
    setDiscoveryError(null);
    setDiscoverySuccess(null);
    setIsSearchingLocation(true);
    setIsDiscoveringArea(true);
    const radiusToUse = overrideRadius !== undefined ? overrideRadius : discoveryRadiusKm;

    setOpProgress({
      active: true,
      stage: overrideLoc ? 'Discovering area water bodies...' : 'Geocoding location...',
      detail: overrideLoc
        ? `Searching OSM around ${overrideLoc.display_name.slice(0, 35)} (${radiusToUse} km radius)`
        : `Resolving "${query}" via Nominatim`,
      percent: 25,
    });

    try {
      let loc = overrideLoc;
      if (!loc) {
        const geocodeRes = await searchLocation(query, 5);
        if (!geocodeRes.results || geocodeRes.results.length === 0) {
          throw new Error(`Location "${query}" not found. Please try another city or landmark.`);
        }
        setMatchedLocations(geocodeRes.results);
        loc = geocodeRes.results[0];
        setSelectedLocation(loc);
      }

      setOpProgress({
        active: true,
        stage: 'Discovering water bodies in area...',
        detail: `Querying OpenStreetMap (radius ${radiusToUse} km around ${loc.display_name.slice(0, 30)})`,
        percent: 65,
      });

      const areaRes = await discoverWaterBodiesByArea(
        loc.latitude,
        loc.longitude,
        radiusToUse,
        40,
        query || loc.display_name
      );
      setAreaDiscoveryData(areaRes);
      setSelectedForImportIds(new Set());
      setSelectedDiscoveredWb(null);

      // Fit map to discovery area
      if (areaRes.bounding_box) {
        setTargetBounds([
          [areaRes.bounding_box.min_lat, areaRes.bounding_box.min_lon],
          [areaRes.bounding_box.max_lat, areaRes.bounding_box.max_lon],
        ]);
        setFitTrigger(t => t + 1);
      } else {
        const dLat = (radiusToUse / 111.0) * 1.1;
        const dLon = (radiusToUse / (111.0 * Math.cos((loc.latitude * Math.PI) / 180))) * 1.1;
        setTargetBounds([
          [loc.latitude - dLat, loc.longitude - dLon],
          [loc.latitude + dLat, loc.longitude + dLon],
        ]);
        setFitTrigger(t => t + 1);
      }

      setOpProgress({
        active: false,
        stage: 'Area discovery complete ✓',
        detail: `Found ${areaRes.total_discovered} water bodies in ${radiusToUse} km radius.`,
        percent: 100,
      });

      const cityName = loc.display_name.split(',')[0].trim();
      if (areaRes.total_discovered === 0) {
        setDiscoverySuccess(`No water bodies found within ${radiusToUse} km of ${cityName}. Try increasing the radius to 5 km or 10 km.`);
      } else {
        setDiscoverySuccess(`Discovered ${areaRes.total_discovered} water bodies within ${radiusToUse} km of ${cityName}. Select one or multiple to review and import into JalNetra.`);
      }
    } catch (err: any) {
      console.error('Area discovery failed:', err);
      setDiscoveryError(err.message || 'Area discovery failed');
      setOpProgress({
        active: false,
        stage: 'Discovery failed',
        detail: err.message,
        error: err.message,
      });
    } finally {
      setIsSearchingLocation(false);
      setIsDiscoveringArea(false);
    }
  }, [discoveryQuery, discoveryRadiusKm]);

  // ─── Phase 3: Spatial distance calculation helpers ────────────────────────────
  const calculateDistanceKm = useCallback((lat1: number, lon1: number, lat2: number, lon2: number): number => {
    const r = 6371.0;
    const dLat = ((lat2 - lat1) * Math.PI) / 180.0;
    const dLon = ((lon2 - lon1) * Math.PI) / 180.0;
    const a =
      Math.sin(dLat / 2.0) ** 2 +
      Math.cos((lat1 * Math.PI) / 180.0) *
        Math.cos((lat2 * Math.PI) / 180.0) *
        Math.sin(dLon / 2.0) ** 2;
    const c = 2.0 * Math.atan2(Math.sqrt(a), Math.sqrt(1.0 - a));
    return r * c;
  }, []);

  const formatDistance = useCallback((distKm: number): string => {
    if (distKm < 1.0) {
      return `${Math.round(distKm * 1000)} m`;
    }
    return `${distKm.toFixed(2)} km`;
  }, []);

  // ─── Phase 3: Selection management ───────────────────────────────────────────
  const toggleSelectForImport = useCallback((sourceId: string) => {
    setSelectedForImportIds(prev => {
      const next = new Set(prev);
      if (next.has(sourceId)) {
        next.delete(sourceId);
      } else {
        next.add(sourceId);
      }
      return next;
    });
  }, []);

  const handleSelectAllUnregistered = useCallback(() => {
    if (!areaDiscoveryData?.results) return;
    const unregistered = areaDiscoveryData.results.filter(wb => !isWbRegistered(wb));
    setSelectedForImportIds(new Set(unregistered.map(wb => wb.source_id)));
  }, [areaDiscoveryData, isWbRegistered]);

  const handleClearSelection = useCallback(() => {
    setSelectedForImportIds(new Set());
  }, []);

  const handleRegisterWaterBody = useCallback(async (wb: WaterBodyDiscoveryResult) => {
    setIsRegisteringWb(true);
    setOpProgress({
      active: true,
      stage: 'Registering water body in JalNetra...',
      detail: `Adding "${wb.name || 'water body'}" to local database`,
      percent: 40,
    });
    setDiscoveryError(null);
    try {
      const registered = await importDiscoveredWaterBody(wb);
      setRegisteredSourceIds(prev => new Set(prev).add(String(wb.source_id)));
      setSelectedForImportIds(prev => {
        const next = new Set(prev);
        next.delete(wb.source_id);
        return next;
      });

      // Refresh water body vectors
      const freshGeoJson = await getWaterBodiesGeoJson();
      setGeoJsonData(freshGeoJson);

      // Auto-select this newly registered water body (DOES NOT acquire satellite scenes)
      handleSelectWaterBody(registered.id, registered, freshGeoJson);

      setOpProgress({
        active: false,
        stage: 'Water body registered ✓',
        detail: `"${registered.name}" is now stored in the database. Satellite scenes can be acquired on-demand in the SCENES tab.`,
        percent: 100,
      });
      setDiscoverySuccess(`✓ "${registered.name}" was added to JalNetra! You can view it in the LAYERS tab or search satellite scenes on-demand.`);
    } catch (err: any) {
      console.error('Failed to register water body:', err);
      setDiscoveryError(err.message || 'Failed to register water body');
      setOpProgress({
        active: false,
        stage: 'Registration failed',
        detail: err.message,
        error: err.message,
      });
    } finally {
      setIsRegisteringWb(false);
    }
  }, [handleSelectWaterBody]);

  // ─── Phase 3: Deliberate Batch Import ─────────────────────────────────────────
  const handleBatchImport = useCallback(async () => {
    if (!areaDiscoveryData?.results || selectedForImportIds.size === 0) return;
    const itemsToImport = areaDiscoveryData.results.filter(wb => selectedForImportIds.has(wb.source_id));
    if (itemsToImport.length === 0) return;

    setIsRegisteringWb(true);
    setOpProgress({
      active: true,
      stage: `Importing ${itemsToImport.length} water bodies...`,
      detail: `Registering selected water bodies into local database`,
      percent: 45,
    });
    setDiscoveryError(null);

    try {
      const batchRes = await importWaterBodiesBatch(itemsToImport);

      // Update registered source IDs with any imported or already registered items
      const newRegisteredIds = new Set(registeredSourceIds);
      batchRes.results.forEach(item => {
        if (item.status === 'imported' || item.status === 'already_registered') {
          newRegisteredIds.add(item.source_id);
        }
      });
      setRegisteredSourceIds(newRegisteredIds);

      // Remove successfully processed items from selection
      setSelectedForImportIds(prev => {
        const next = new Set(prev);
        batchRes.results.forEach(item => {
          if (item.status === 'imported' || item.status === 'already_registered') {
            next.delete(item.source_id);
          }
        });
        return next;
      });

      // Refresh water body vectors
      const freshGeoJson = await getWaterBodiesGeoJson();
      setGeoJsonData(freshGeoJson);

      // Auto-select the first successfully imported water body if available
      const firstSuccessful = batchRes.results.find(r => r.water_body && r.status === 'imported')?.water_body;
      if (firstSuccessful) {
        handleSelectWaterBody(firstSuccessful.id, firstSuccessful, freshGeoJson);
      }

      setOpProgress({
        active: false,
        stage: 'Batch import complete ✓',
        detail: `${batchRes.imported_count} added, ${batchRes.already_existed_count} already existed, ${batchRes.failed_count} failed. Zero satellite scenes acquired.`,
        percent: 100,
      });

      let summaryMsg = `✓ ${batchRes.imported_count} water ${batchRes.imported_count === 1 ? 'body' : 'bodies'} added to JalNetra!`;
      if (batchRes.already_existed_count > 0) {
        summaryMsg += ` (${batchRes.already_existed_count} were already registered)`;
      }
      if (batchRes.failed_count > 0) {
        summaryMsg += ` (${batchRes.failed_count} failed)`;
      }
      setDiscoverySuccess(summaryMsg);
    } catch (err: any) {
      console.error('Batch import failed:', err);
      setDiscoveryError(err.message || 'Batch import failed');
      setOpProgress({
        active: false,
        stage: 'Batch import failed ✕',
        detail: err.message,
        error: err.message,
      });
    } finally {
      setIsRegisteringWb(false);
    }
  }, [areaDiscoveryData, selectedForImportIds, registeredSourceIds, handleSelectWaterBody]);

  const handleSelectScene = useCallback(async (
    sceneItem: MapSceneItem,
    wbId?: string,
    auto = false,
    reqIdParam?: number
  ) => {
    const curReqId = reqIdParam !== undefined ? reqIdParam : ++requestIdRef.current;
    const targetWbId = wbId || selectedWaterBodyId;
    setSelectedSceneId(sceneItem.scene_id);
    setSelectedSceneItem(sceneItem);
    setIsAutoSelected(auto);
    setRgbData(null);
    setAcquireMessage(null);

    // Fetch raster metadata
    try {
      const meta = await getSceneRasterMetadata(sceneItem.scene_id);
      if (requestIdRef.current !== curReqId) return;
      setSceneMetadata(meta);
      if (meta.rgb_available || meta.rgb_cached || sceneItem.has_rgb) {
        loadRGBVisualization(sceneItem.scene_id, targetWbId, false, undefined, undefined, curReqId);
      }
    } catch (err) {
      if (requestIdRef.current !== curReqId) return;
      console.warn('Failed to load scene raster metadata:', err);
      if (sceneItem.has_rgb) {
        loadRGBVisualization(sceneItem.scene_id, targetWbId, false, undefined, undefined, curReqId);
      }
    }

    // Load per-scene processing status
    loadProcessingStatus(sceneItem.scene_id);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedWaterBodyId]);

  const loadRGBVisualization = useCallback(async (
    sceneId: string,
    wbId?: string,
    force = false,
    customAoi?: [[number, number], [number, number]] | null,
    paddingPct?: number,
    reqIdParam?: number
  ) => {
    const curReqId = reqIdParam !== undefined ? reqIdParam : requestIdRef.current;
    setIsLoadingRgb(true);
    setOpProgress({
      active: true,
      stage: 'Rendering Sentinel-2 RGB image...',
      detail: 'Aligning spectral bands & stretching contrast (2-98%)',
      percent: 85,
    });
    try {
      const targetWbId = wbId || selectedWaterBodyId;
      const effectiveAoi = customAoi !== undefined ? customAoi : (aoiMode === 'manual' ? manualAoi : null);
      const effectivePad = paddingPct !== undefined ? paddingPct : autoPaddingPct;

      let bboxParam: [number, number, number, number] | undefined = undefined;
      if (effectiveAoi) {
        const [[s, w], [n, e]] = effectiveAoi;
        bboxParam = [w, s, e, n];
      }

      const data = await getSceneRGBVisualization(
        sceneId,
        targetWbId || undefined,
        force,
        bboxParam,
        effectiveAoi ? undefined : effectivePad
      );
      if (requestIdRef.current !== curReqId) return;
      setRgbData(data);
      setOpProgress({
        active: false,
        stage: 'Satellite imagery ready ✓',
        detail: `Rendered ${data.width}x${data.height} overlay (${data.cached ? 'from cache' : 'fresh render'})`,
        percent: 100,
      });

      // If focused, center camera on cropped extent
      if (
        data.bounds && data.is_focused &&
        isFinite(data.bounds.south) && isFinite(data.bounds.north)
      ) {
        setTargetBounds([[data.bounds.south, data.bounds.west], [data.bounds.north, data.bounds.east]]);
        setFitTrigger(t => t + 1);
      }
    } catch (err: any) {
      if (requestIdRef.current !== curReqId) return;
      console.warn('Failed to render RGB imagery:', err);
      setOpProgress({
        active: false,
        stage: 'Rendering failed',
        detail: err.message || 'Could not render RGB visualization',
        error: err.message,
      });
    } finally {
      if (requestIdRef.current === curReqId) {
        setIsLoadingRgb(false);
      }
    }
  }, [selectedWaterBodyId, aoiMode, manualAoi, autoPaddingPct]);

  const loadProcessingStatus = useCallback(async (sceneId: string) => {
    try {
      const status = await getProcessingStatus(sceneId);
      updateProcState(sceneId, { status });
      if (status.cloud_mask_available && status.water_mask_available) {
        let bboxParam: [number, number, number, number] | undefined = undefined;
        if (aoiMode === 'manual' && manualAoi) {
          const [[s, w], [n, e]] = manualAoi;
          bboxParam = [w, s, e, n];
        }
        const effectiveWbId = aoiMode === 'manual' ? undefined : (selectedWaterBodyId || undefined);
        const effectivePad = aoiMode === 'manual' ? undefined : autoPaddingPct;
        const [cm, wm] = await Promise.all([
          getCloudMaskVisualization(sceneId, effectiveWbId, bboxParam, effectivePad),
          getWaterMaskVisualization(sceneId, effectiveWbId, bboxParam, effectivePad),
        ]);
        updateProcState(sceneId, { cloudVis: cm, waterVis: wm });
      }
    } catch (err) {
      console.warn('Failed to check processing status:', err);
    }
  }, [updateProcState, aoiMode, manualAoi, selectedWaterBodyId, autoPaddingPct]);

  const handleRunProcessing = useCallback(async (force = false) => {
    if (!selectedSceneId) return;
    const sceneId = selectedSceneId;
    updateProcState(sceneId, { isProcessing: true, error: null });
    setOpProgress({
      active: true,
      stage: 'Phase 5 Processing running...',
      detail: 'Processing cloud mask (SCL) and spectral water detection...',
      percent: 50,
    });
    try {
      const status = await runSceneProcessing(sceneId, 0.0, force);
      let bboxParam: [number, number, number, number] | undefined = undefined;
      if (aoiMode === 'manual' && manualAoi) {
        const [[s, w], [n, e]] = manualAoi;
        bboxParam = [w, s, e, n];
      }
      const effectiveWbId = aoiMode === 'manual' ? undefined : (selectedWaterBodyId || undefined);
      const effectivePad = aoiMode === 'manual' ? undefined : autoPaddingPct;
      const [cm, wm] = await Promise.all([
        getCloudMaskVisualization(sceneId, effectiveWbId, bboxParam, effectivePad),
        getWaterMaskVisualization(sceneId, effectiveWbId, bboxParam, effectivePad),
      ]);
      updateProcState(sceneId, { status, cloudVis: cm, waterVis: wm, isProcessing: false, error: null });
      setShowCloudMask(true);
      setShowWaterMask(true);
      setOpProgress({
        active: false,
        stage: 'Analysis complete ✓',
        detail: 'Cloud/shadow mask and water detection layers ready',
        percent: 100,
      });
    } catch (err: any) {
      updateProcState(sceneId, { isProcessing: false, error: err.message || 'Processing pipeline failed' });
      setOpProgress({
        active: false,
        stage: 'Analysis failed ✕',
        detail: err.message || 'Processing pipeline failed',
        error: err.message,
      });
    }
  }, [selectedSceneId, updateProcState, aoiMode, manualAoi, selectedWaterBodyId, autoPaddingPct]);

  // ─── STAC Refresh ─────────────────────────────────────────────────────────────
  const handleRefetchScenes = useCallback(async () => {
    if (!selectedWaterBodyId) return;
    const reqId = ++requestIdRef.current;
    setIsRefetchingScenes(true);
    setRefetchError(null);
    setAcquireMessage(null);
    setOpProgress({
      active: true,
      stage: 'Refreshing satellite data...',
      detail: 'Querying Sentinel-2 STAC for recent scenes (last 180 days)...',
      percent: 30,
    });
    try {
      const end = new Date();
      const start = new Date();
      start.setDate(start.getDate() - 180);
      const fmt = (d: Date) => d.toISOString().split('T')[0];

      const searchRes = await searchSatelliteScenes(selectedWaterBodyId, fmt(start), fmt(end), 30, 10);
      if (requestIdRef.current !== reqId) return;

      setOpProgress({
        active: true,
        stage: 'STAC search complete',
        detail: `Found ${searchRes.results?.length || 0} candidate scenes`,
        percent: 60,
      });

      const sceneList = await getMapScenes(selectedWaterBodyId);
      if (requestIdRef.current !== reqId) return;
      setScenes(sceneList);

      const bestValidScene = sceneList.find(s => s.covers_water_body && s.has_rgb)
        || sceneList.find(s => s.covers_water_body);

      if (bestValidScene) {
        handleSelectScene(bestValidScene, selectedWaterBodyId, true, reqId);
      }

      setOpProgress({
        active: false,
        stage: 'Satellite data refreshed ✓',
        detail: `${sceneList.length} scenes available`,
        percent: 100,
      });
    } catch (err: any) {
      if (requestIdRef.current !== reqId) return;
      setRefetchError(err.message || 'STAC search failed');
      setOpProgress({
        active: false,
        stage: 'Refresh failed',
        detail: err.message || 'STAC search failed',
        error: err.message,
      });
    } finally {
      if (requestIdRef.current === reqId) {
        setIsRefetchingScenes(false);
      }
    }
  }, [selectedWaterBodyId, handleSelectScene]);

  // ─── Acquire Scene ────────────────────────────────────────────────────────────
  const handleAcquireScene = useCallback(async (sceneItem: MapSceneItem) => {
    setAcquiringSceneId(sceneItem.scene_id);
    setAcquireMessage(null);
    setOpProgress({
      active: true,
      stage: 'Acquiring scene assets...',
      detail: `Downloading spectral bands for ${sceneItem.external_scene_id.slice(0, 20)}…`,
      percent: 50,
    });
    try {
      const result = await acquireSceneAssets(sceneItem.external_scene_id, ['B02', 'B03', 'B04', 'SCL', 'thumbnail']);
      const msg = `Acquired: ${result.downloaded_assets} new, ${result.already_present_assets} already present, ${result.failed_assets} failed`;
      setAcquireMessage(msg);
      setOpProgress({
        active: false,
        stage: 'Scene assets ready ✓',
        detail: msg,
        percent: 100,
      });

      // Reload scenes
      const sceneList = await getMapScenes(selectedWaterBodyId);
      setScenes(sceneList);
      if (sceneItem.scene_id === selectedSceneId) {
        const updatedScene = sceneList.find(s => s.scene_id === sceneItem.scene_id);
        if (updatedScene?.has_rgb) {
          loadRGBVisualization(sceneItem.scene_id, selectedWaterBodyId, true);
        }
      }
    } catch (err: any) {
      const msg = `Acquisition failed: ${err.message}`;
      setAcquireMessage(msg);
      setOpProgress({
        active: false,
        stage: 'Acquisition failed',
        detail: msg,
        error: err.message,
      });
    } finally {
      setAcquiringSceneId(null);
    }
  }, [selectedWaterBodyId, selectedSceneId, loadRGBVisualization]);

  // ─── AOI Refocus & Manual AOI Fetch ──────────────────────────────────────────
  const handleFocusToWaterBody = useCallback(() => {
    if (!selectedWaterBodyProps) return;
    const bounds = computeBoundsFromProps(selectedWaterBodyProps, autoPaddingPct / 100);
    if (bounds) {
      setTargetBounds(bounds);
      setFitTrigger(t => t + 1);
    }
    // Reload RGB with updated water body focus
    if (selectedSceneId) {
      loadRGBVisualization(selectedSceneId, selectedWaterBodyId, true);
    }
  }, [selectedWaterBodyProps, autoPaddingPct, computeBoundsFromProps, selectedSceneId, selectedWaterBodyId, loadRGBVisualization]);

  const handleFetchAoiImagery = useCallback(async (bounds: [[number, number], [number, number]]) => {
    const reqId = ++requestIdRef.current;
    // 1. Immediately wipe old imagery and old AOI
    setRgbData(null);
    setManualAoi(bounds);
    setIsDrawingAoi(false);

    // Center map to new AOI
    setTargetBounds(bounds);
    setFitTrigger(t => t + 1);

    const [[s, w], [n, e]] = bounds;
    const aoiBboxStr = `${w},${s},${e},${n}`;

    setOpProgress({
      active: true,
      stage: '1. AOI selected ✓',
      detail: `Bounds: [${s.toFixed(4)}, ${w.toFixed(4)}] to [${n.toFixed(4)}, ${e.toFixed(4)}]`,
      percent: 20,
    });

    try {
      // 2. Finding scene
      setOpProgress({
        active: true,
        stage: '2. Finding scene ●',
        detail: 'Querying Sentinel-2 catalog for overlapping passes...',
        percent: 40,
      });

      await searchSatelliteScenes(
        selectedWaterBodyId || undefined,
        undefined,
        undefined,
        30,
        10,
        aoiBboxStr
      );
      if (requestIdRef.current !== reqId) return;

      const sceneList = await getMapScenes(selectedWaterBodyId);
      if (requestIdRef.current !== reqId) return;
      setScenes(sceneList);

      const coveringScene = sceneList.find(sc => {
        if (!sc.bbox || sc.bbox.length !== 4) return false;
        const [scW, scS, scE, scN] = sc.bbox;
        return !(e < scW || w > scE || n < scS || s > scN);
      }) || (sceneList.length > 0 ? sceneList[0] : null);

      if (!coveringScene) {
        setOpProgress({
          active: false,
          stage: 'No scenes found ✕',
          detail: 'No Sentinel-2 scenes cover the drawn AOI',
          error: 'No scenes found',
        });
        return;
      }

      // 3. Loading bands
      setOpProgress({
        active: true,
        stage: '3. Loading bands ●',
        detail: `Verifying bands B02, B03, B04 for ${coveringScene.external_scene_id.slice(0, 20)}...`,
        percent: 65,
      });

      if (!coveringScene.has_rgb) {
        await acquireSceneAssets(coveringScene.external_scene_id, ['B02', 'B03', 'B04', 'SCL', 'thumbnail']);
        if (requestIdRef.current !== reqId) return;
      }

      setSelectedSceneId(coveringScene.scene_id);
      setSelectedSceneItem(coveringScene);

      // 4. Cropping & Rendering
      setOpProgress({
        active: true,
        stage: '4. Cropping & Rendering ●',
        detail: 'Cropping native 10m resolution raster to AOI window...',
        percent: 85,
      });

      await loadRGBVisualization(coveringScene.scene_id, selectedWaterBodyId, true, bounds, undefined, reqId);
      if (requestIdRef.current !== reqId) return;

      // 5. Ready ✓
      setOpProgress({
        active: false,
        stage: '5. Ready ✓',
        detail: `Focused 10m imagery loaded successfully for ${coveringScene.sensing_start ? formatSensingDate(coveringScene.sensing_start) : coveringScene.external_scene_id.slice(0, 20)}`,
        percent: 100,
      });
    } catch (err: any) {
      if (requestIdRef.current !== reqId) return;
      setOpProgress({
        active: false,
        stage: 'AOI Imagery Failed ✕',
        detail: err.message || 'Could not fetch imagery for AOI',
        error: err.message,
      });
    }
  }, [selectedWaterBodyId, loadRGBVisualization]);

  const handleManualAoiComplete = useCallback((bounds: [[number, number], [number, number]]) => {
    handleFetchAoiImagery(bounds);
  }, [handleFetchAoiImagery]);

  const handleClearAoi = useCallback(() => {
    setManualAoi(null);
    setIsDrawingAoi(false);
    setOpProgress(null);
    if (selectedWaterBodyProps) {
      const bounds = computeBoundsFromProps(selectedWaterBodyProps, autoPaddingPct / 100);
      if (bounds) {
        setTargetBounds(bounds);
        setFitTrigger(t => t + 1);
      }
    }
    if (selectedSceneId) {
      loadRGBVisualization(selectedSceneId, selectedWaterBodyId, true, null, autoPaddingPct);
    }
  }, [selectedWaterBodyProps, autoPaddingPct, computeBoundsFromProps, selectedSceneId, selectedWaterBodyId, loadRGBVisualization]);

  // ─── Lifecycle ────────────────────────────────────────────────────────────────
  useEffect(() => {
    loadWaterBodies();
  }, [loadWaterBodies]);

  // ─── Overlay bounds ───────────────────────────────────────────────────────────
  const rasterOverlayBounds: L.LatLngBoundsExpression | null = rgbData?.bounds
    ? [[rgbData.bounds.south, rgbData.bounds.west], [rgbData.bounds.north, rgbData.bounds.east]]
    : null;

  const cloudMaskBounds: L.LatLngBoundsExpression | null = currentProc.cloudVis?.bounds
    ? [[currentProc.cloudVis.bounds.south, currentProc.cloudVis.bounds.west], [currentProc.cloudVis.bounds.north, currentProc.cloudVis.bounds.east]]
    : null;

  const waterMaskBounds: L.LatLngBoundsExpression | null = currentProc.waterVis?.bounds
    ? [[currentProc.waterVis.bounds.south, currentProc.waterVis.bounds.west], [currentProc.waterVis.bounds.north, currentProc.waterVis.bounds.east]]
    : null;

  // ─── Render ───────────────────────────────────────────────────────────────────
  return (
    <div style={styles.pageContainer}>
      {/* ── Full-viewport Leaflet Map ─────────────────────────────────────── */}
      <div style={styles.mapCanvas}>
        <MapContainer
          center={[22.0, 79.0]}
          zoom={5}
          style={styles.mapContainer}
          scrollWheelZoom={true}
        >
          <FitBoundsHelper bounds={targetBounds} trigger={fitTrigger} />

          <DrawAoiHandler
            active={isDrawingAoi}
            onComplete={handleManualAoiComplete}
          />

          {showBaseMap && (
            <TileLayer
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              maxZoom={19}
            />
          )}

          {showWaterBodies && geoJsonData && (
            <GeoJSON
              key={`wb-geojson-${selectedWaterBodyId}`}
              data={geoJsonData}
              style={(feature) => ({
                color: feature?.properties.id === selectedWaterBodyId ? '#c2410c' : '#15803d',
                weight: feature?.properties.id === selectedWaterBodyId ? 3.5 : 1.5,
                fillColor: feature?.properties.id === selectedWaterBodyId ? '#fb923c' : '#22c55e',
                fillOpacity: feature?.properties.id === selectedWaterBodyId ? 0.25 : 0.12,
              })}
              onEachFeature={(feature, layer) => {
                layer.on({ click: () => handleSelectWaterBody(feature.properties.id, feature.properties) });
                layer.bindPopup(
                  `<div style="font-family:sans-serif;font-size:12px;line-height:1.4">
                    <strong style="color:#15803d">${feature.properties.name}</strong><br/>
                    <b>Type:</b> ${feature.properties.water_body_type || 'Inland Water'}<br/>
                    <b>Area:</b> ${feature.properties.area_sq_km ? Number(feature.properties.area_sq_km).toFixed(2) + ' km²' : 'N/A'}
                  </div>`
                );
              }}
            />
          )}

          {showSceneFootprint && selectedSceneItem?.footprint && (
            <GeoJSON
              key={`footprint-${selectedSceneItem.scene_id}`}
              data={selectedSceneItem.footprint}
              style={{ color: '#ea580c', weight: 1.8, dashArray: '6, 6', fillColor: '#fff7ed', fillOpacity: 0.05 }}
            />
          )}

          {/* Satellite Raster Extent (AOI) */}
          {showRasterExtent && rasterOverlayBounds && (
            <Rectangle
              bounds={rasterOverlayBounds}
              pathOptions={{
                color: '#0284c7',
                weight: 1.8,
                dashArray: '5 5',
                fillColor: '#0284c7',
                fillOpacity: 0.02,
              }}
            />
          )}

          {showRgbImagery && rgbData && rasterOverlayBounds && (
            <ImageOverlay
              key={`rgb-${rgbData.scene_id}-${rgbData.water_body_id || 'full'}-${aoiMode}-${aoiMode === 'manual' ? (manualAoi ? manualAoi.flat().join(',') : 'none') : autoPaddingPct}-${rgbData.image_url}`}
              url={resolveApiUrl(rgbData.image_url)}
              bounds={rasterOverlayBounds}
              opacity={rasterOpacity}
            />
          )}

          {showCloudMask && currentProc.cloudVis && cloudMaskBounds && (
            <ImageOverlay
              key={`cloud-${currentProc.cloudVis.scene_id}-${selectedWaterBodyId}-${aoiMode}-${aoiMode === 'manual' ? (manualAoi ? manualAoi.flat().join(',') : 'none') : autoPaddingPct}`}
              url={getCloudMaskImageUrl(
                currentProc.cloudVis.scene_id,
                aoiMode === 'manual' ? undefined : (selectedWaterBodyId || undefined),
                aoiMode === 'manual' && manualAoi ? [manualAoi[0][1], manualAoi[0][0], manualAoi[1][1], manualAoi[1][0]] : undefined,
                aoiMode === 'manual' ? undefined : autoPaddingPct
              )}
              bounds={cloudMaskBounds}
              opacity={cloudMaskOpacity}
            />
          )}

          {showWaterMask && currentProc.waterVis && waterMaskBounds && (
            <ImageOverlay
              key={`water-${currentProc.waterVis.scene_id}-${selectedWaterBodyId}-${aoiMode}-${aoiMode === 'manual' ? (manualAoi ? manualAoi.flat().join(',') : 'none') : autoPaddingPct}`}
              url={getWaterMaskImageUrl(
                currentProc.waterVis.scene_id,
                aoiMode === 'manual' ? undefined : (selectedWaterBodyId || undefined),
                aoiMode === 'manual' && manualAoi ? [manualAoi[0][1], manualAoi[0][0], manualAoi[1][1], manualAoi[1][0]] : undefined,
                aoiMode === 'manual' ? undefined : autoPaddingPct
              )}
              bounds={waterMaskBounds}
              opacity={waterMaskOpacity}
            />
          )}

          {/* Manual AOI rectangle */}
          {aoiMode === 'manual' && manualAoi && (
            <Rectangle
              bounds={manualAoi}
              pathOptions={{ color: '#f59e0b', weight: 2, dashArray: '4 4', fillOpacity: 0.08 }}
            />
          )}

          {/* Phase 2: Area Discovery Search Radius Circle */}
          {areaDiscoveryData && (
            <Circle
              center={[areaDiscoveryData.center.latitude, areaDiscoveryData.center.longitude]}
              radius={areaDiscoveryData.radius_km * 1000}
              pathOptions={{
                color: '#0891b2',
                weight: 2,
                dashArray: '6 6',
                fillColor: '#06b6d4',
                fillOpacity: 0.05,
              }}
            />
          )}

          {/* Phase 2: Area Discovery Center Marker */}
          {areaDiscoveryData && (
            <CircleMarker
              center={[areaDiscoveryData.center.latitude, areaDiscoveryData.center.longitude]}
              radius={5}
              pathOptions={{
                color: '#0891b2',
                fillColor: '#ffffff',
                fillOpacity: 1,
                weight: 2,
              }}
            >
              <Popup>
                <div style={{ fontSize: '12px', fontFamily: 'sans-serif' }}>
                  <strong style={{ color: '#0891b2' }}>Search Center</strong><br />
                  {areaDiscoveryData.query_location || 'Area Search'}<br />
                  <b>Radius:</b> {areaDiscoveryData.radius_km} km
                </div>
              </Popup>
            </CircleMarker>
          )}

          {/* Phase 2/3: Discovered Water Bodies Overlays with Selection Highlight */}
          {areaDiscoveryData?.results?.map((wb, idx) => {
            let parsedGeo = null;
            if (wb.geometry_geojson) {
              try {
                parsedGeo = typeof wb.geometry_geojson === 'string' ? JSON.parse(wb.geometry_geojson) : wb.geometry_geojson;
              } catch { /* ignore */ }
            }
            const isRegistered = isWbRegistered(wb);
            const isSelected = selectedDiscoveredWb?.source_id === wb.source_id;
            const isSelectedForImport = selectedForImportIds.has(wb.source_id);
            const distFromCenter = (wb.centroid_lat != null && wb.centroid_lon != null && areaDiscoveryData.center)
              ? calculateDistanceKm(areaDiscoveryData.center.latitude, areaDiscoveryData.center.longitude, wb.centroid_lat, wb.centroid_lon)
              : null;

            return (
              <React.Fragment key={`disc-${wb.source_id || idx}`}>
                {parsedGeo && (
                  <GeoJSON
                    key={`disc-poly-${wb.source_id}-${isSelectedForImport ? 'importsel' : isSelected ? 'sel' : 'unsel'}`}
                    data={parsedGeo}
                    style={{
                      color: isSelectedForImport ? '#2563eb' : isSelected ? '#0284c7' : isRegistered ? '#16a34a' : '#0891b2',
                      weight: isSelectedForImport ? 3.5 : isSelected ? 3 : 2,
                      dashArray: isSelectedForImport ? undefined : '4 4',
                      fillColor: isSelectedForImport ? '#38bdf8' : isSelected ? '#38bdf8' : isRegistered ? '#4ade80' : '#22d3ee',
                      fillOpacity: isSelectedForImport ? 0.45 : isSelected ? 0.35 : 0.16,
                    }}
                    eventHandlers={{
                      click: () => setSelectedDiscoveredWb(wb),
                    }}
                  />
                )}

                {wb.centroid_lat != null && wb.centroid_lon != null && (
                  <CircleMarker
                    center={[wb.centroid_lat, wb.centroid_lon]}
                    radius={isSelectedForImport ? 9 : isSelected ? 8 : 6}
                    pathOptions={{
                      color: isSelectedForImport ? '#1d4ed8' : isRegistered ? '#15803d' : isSelected ? '#0284c7' : '#0891b2',
                      fillColor: isSelectedForImport ? '#60a5fa' : isRegistered ? '#22c55e' : isSelected ? '#38bdf8' : '#06b6d4',
                      fillOpacity: 0.95,
                      weight: isSelectedForImport ? 3 : 2,
                    }}
                    eventHandlers={{
                      click: () => setSelectedDiscoveredWb(wb),
                    }}
                  >
                    <Popup>
                      <div style={{ fontFamily: 'sans-serif', fontSize: '12px', minWidth: '210px' }}>
                        <div style={{ fontWeight: 700, fontSize: '13px', color: '#0f172a', marginBottom: '4px' }}>
                          {wb.name || 'Unnamed Water Body'}
                        </div>
                        <div style={{ color: '#475569', fontSize: '11px', marginBottom: '2px' }}>
                          <b>Type:</b> {wb.water_body_type || 'water'}
                        </div>
                        <div style={{ color: '#475569', fontSize: '11px', marginBottom: '2px' }}>
                          <b>Area:</b> {wb.area_sq_km ? `${wb.area_sq_km.toFixed(2)} km²` : 'N/A'}
                        </div>
                        {distFromCenter != null && (
                          <div style={{ color: '#0284c7', fontSize: '11px', marginBottom: '2px', fontWeight: 600 }}>
                            <b>Distance:</b> {formatDistance(distFromCenter)} from center
                          </div>
                        )}
                        <div style={{ color: '#64748b', fontSize: '10px', marginBottom: '8px' }}>
                          <b>Source:</b> {wb.provider} ({wb.source_id})
                        </div>
                        {isRegistered ? (
                          <div style={{
                            padding: '4px 8px',
                            backgroundColor: '#dcfce7',
                            color: '#15803d',
                            borderRadius: '3px',
                            fontWeight: 700,
                            fontSize: '11px',
                            textAlign: 'center',
                          }}>
                            ✓ IN JALNETRA
                          </div>
                        ) : (
                          <div style={{ display: 'flex', flexDirection: 'column', gap: '5px' }}>
                            <button
                              type="button"
                              style={{
                                width: '100%',
                                padding: '5px 8px',
                                backgroundColor: isSelectedForImport ? '#dbeafe' : '#f1f5f9',
                                color: isSelectedForImport ? '#1d4ed8' : '#334155',
                                border: isSelectedForImport ? '1px solid #3b82f6' : '1px solid #cbd5e1',
                                borderRadius: '3px',
                                cursor: 'pointer',
                                fontWeight: 700,
                                fontSize: '11px',
                              }}
                              onClick={(e) => {
                                e.stopPropagation();
                                toggleSelectForImport(wb.source_id);
                              }}
                            >
                              {isSelectedForImport ? '✓ SELECTED FOR IMPORT' : '☑ SELECT FOR IMPORT'}
                            </button>
                            <button
                              type="button"
                              style={{
                                width: '100%',
                                padding: '6px 10px',
                                backgroundColor: '#0284c7',
                                color: '#ffffff',
                                border: 'none',
                                borderRadius: '3px',
                                cursor: 'pointer',
                                fontWeight: 700,
                                fontSize: '11px',
                              }}
                              disabled={isRegisteringWb}
                              onClick={(e) => {
                                e.stopPropagation();
                                handleRegisterWaterBody(wb);
                              }}
                            >
                              {isRegisteringWb && selectedDiscoveredWb?.source_id === wb.source_id ? 'ADDING...' : '+ ADD DIRECTLY TO JALNETRA'}
                            </button>
                          </div>
                        )}
                      </div>
                    </Popup>
                  </CircleMarker>
                )}
              </React.Fragment>
            );
          })}
        </MapContainer>
      </div>

      {/* ── Top Status Pill ───────────────────────────────────────────────── */}
      <div style={styles.topStatusPill}>
        <div style={styles.statusDotLive} />
        <span style={styles.topStatusTitle}>JALNETRA GIS WORKSTATION</span>
        <span style={styles.topStatusDivider}>|</span>
        <span style={styles.topStatusMeta}>CRS: EPSG:4326</span>
        {rgbData?.is_focused && (
          <>
            <span style={styles.topStatusDivider}>|</span>
            <span style={styles.badgeCropActive}>FOCUSED EXTENT ({autoPaddingPct}% PAD)</span>
          </>
        )}
        {(rgbData?.sensing_date || selectedSceneItem?.sensing_start) && (
          <>
            <span style={styles.topStatusDivider}>|</span>
            <span style={styles.sensingDateBadge}>
              OBSERVATION: {formatSensingDate(rgbData?.sensing_date || selectedSceneItem?.sensing_start)} • 10m
            </span>
          </>
        )}
        {areaDiscoveryData && (
          <>
            <span style={styles.topStatusDivider}>|</span>
            <span style={styles.badgeDiscoveryActive}>
              AREA: {areaDiscoveryData.query_location || 'Search'} ({areaDiscoveryData.radius_km}km • {areaDiscoveryData.total_discovered} found)
            </span>
          </>
        )}
        {isDrawingAoi && (
          <>
            <span style={styles.topStatusDivider}>|</span>
            <span style={styles.badgeDrawing}>DRAWING AOI — click &amp; drag on map</span>
          </>
        )}
        <span style={styles.topStatusDivider}>|</span>
        <button
          style={activeSidebarTab === 'discovery' ? styles.topDiscoveryBtnActive : styles.topDiscoveryBtn}
          onClick={() => {
            setActiveSidebarTab('discovery');
            setSidebarCollapsed(false);
          }}
        >
          🔍 AREA DISCOVERY
        </button>
        {selectedWaterBodyId && (
          <>
            <span style={styles.topStatusDivider}>|</span>
            <button
              style={styles.topVisualDataBtn}
              onClick={() => setIsFetchVisualDataOpen(true)}
              title="Fetch Visual Satellite Observations across time for this water body"
            >
              🛰 FETCH VISUAL DATA
            </button>
            {onNavigateToAnalysis && (
              <button
                style={styles.topAnalysisBtn}
                onClick={() => onNavigateToAnalysis(selectedWaterBodyId)}
                title="Open Temporal Analysis for this water body"
              >
                📊 ANALYSIS →
              </button>
            )}
          </>
        )}
      </div>

      {/* ── Prominent Operation Progress Panel ───────────────────────────── */}
      {opProgress && (
        <FloatingPanel style={styles.progressPanel}>
          <div style={styles.progressHeader}>
            <span style={styles.progressTitle}>
              {opProgress.error ? '✕ ERROR' : opProgress.percent === 100 ? '✓ READY' : '● PROCESSING'}
            </span>
            <button
              style={styles.progressDismissBtn}
              onClick={() => setOpProgress(null)}
              title="Dismiss"
            >
              ✕
            </button>
          </div>
          <div style={styles.progressStageRow}>
            <strong>{opProgress.stage}</strong>
          </div>
          {opProgress.detail && (
            <div style={styles.progressDetail}>{opProgress.detail}</div>
          )}
          {opProgress.percent != null && (
            <div style={styles.progressBarContainer}>
              <div
                style={{
                  ...styles.progressBarFill,
                  width: `${opProgress.percent}%`,
                  backgroundColor: opProgress.error ? '#ef4444' : opProgress.percent === 100 ? '#22c55e' : '#3b82f6',
                }}
              />
            </div>
          )}
        </FloatingPanel>
      )}

      {/* Error banner */}
      {error && (
        <div style={styles.errorBanner}>
          <span>{error}</span>
          <button style={styles.closeBtn} onClick={() => setError(null)}>✕</button>
        </div>
      )}

      {/* ── Left Sidebar ──────────────────────────────────────────────────── */}
      <FloatingPanel style={{
        ...styles.sidebar,
        width: sidebarCollapsed ? '42px' : '320px',
      }}>
        {/* Sidebar header */}
        <div style={styles.sidebarHeader}>
          {!sidebarCollapsed && (
            <span style={styles.sidebarHeaderTitle}>MONITORING CONTROLS</span>
          )}
          <button
            style={styles.sidebarCollapseBtn}
            onClick={() => setSidebarCollapsed(v => !v)}
            title={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            {sidebarCollapsed ? '▶' : '◀'}
          </button>
        </div>

        {!sidebarCollapsed && (
          <>
            {/* Tab bar */}
            <div style={styles.tabBar}>
              {(['discovery', 'layers', 'scenes', 'aoi'] as const).map(tab => (
                <button
                  key={tab}
                  data-tab={tab}
                  style={{
                    ...styles.tabBtn,
                    ...(activeSidebarTab === tab ? styles.tabBtnActive : {}),
                  }}
                  onClick={() => setActiveSidebarTab(tab)}
                >
                  {tab === 'discovery' ? 'DISCOVERY' : tab === 'layers' ? 'LAYERS' : tab === 'scenes' ? 'SCENES' : 'AOI'}
                </button>
              ))}
            </div>

            {/* ── Tab: DISCOVERY ─────────────────────────────────────────── */}
            {activeSidebarTab === 'discovery' && (
              <div style={styles.tabContent}>
                <div style={styles.sectionBlock}>
                  <label style={styles.sectionLabel}>AREA-BASED WATER BODY DISCOVERY</label>
                  <div style={styles.helpTextSmall}>
                    Search any city or region to discover water bodies via OpenStreetMap, visualize the area, and register water bodies without downloading satellite imagery.
                  </div>

                  <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem', marginTop: '0.3rem' }}>
                    <label style={styles.subLabel}>TARGET LOCATION</label>
                    <div style={{ display: 'flex', gap: '0.3rem' }}>
                      <input
                        type="text"
                        placeholder="e.g. Delhi, Pune, Nagpur, Ooty..."
                        value={discoveryQuery}
                        onChange={(e) => setDiscoveryQuery(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') handleExecuteAreaSearch();
                        }}
                        style={styles.textInput}
                      />
                      <button
                        style={styles.actionBtnSmall}
                        onClick={() => handleExecuteAreaSearch()}
                        disabled={isSearchingLocation || isDiscoveringArea || !discoveryQuery.trim()}
                      >
                        {isSearchingLocation || isDiscoveringArea ? '...' : 'SEARCH'}
                      </button>
                    </div>
                  </div>

                  {/* Matched geocoded locations selector if multiple found */}
                  {matchedLocations.length > 1 && (
                    <div style={{ marginTop: '0.35rem' }}>
                      <label style={styles.subLabel}>RESOLVED LOCATION</label>
                      <select
                        style={styles.selectInput}
                        value={selectedLocation?.display_name || ''}
                        onChange={(e) => {
                          const loc = matchedLocations.find(l => l.display_name === e.target.value);
                          if (loc) {
                            setSelectedLocation(loc);
                            handleExecuteAreaSearch(loc);
                          }
                        }}
                      >
                        {matchedLocations.map((loc, idx) => (
                          <option key={idx} value={loc.display_name}>
                            {loc.display_name.slice(0, 48)}…
                          </option>
                        ))}
                      </select>
                    </div>
                  )}

                  {/* Search Radius */}
                  <div style={{ marginTop: '0.4rem' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <label style={styles.subLabel}>SEARCH RADIUS</label>
                      <span style={styles.radiusPill}>{discoveryRadiusKm < 1 ? `${discoveryRadiusKm * 1000} m` : `${discoveryRadiusKm} km`}</span>
                    </div>
                    <div style={styles.radiusButtonGrid}>
                      {[0.5, 1.0, 2.0, 5.0, 10.0, 25.0].map(r => (
                        <button
                          key={r}
                          style={{
                            ...styles.radiusChoiceBtn,
                            ...(discoveryRadiusKm === r ? styles.radiusChoiceBtnActive : {}),
                          }}
                          onClick={() => {
                            setDiscoveryRadiusKm(r);
                            if (selectedLocation) {
                              handleExecuteAreaSearch(selectedLocation, r);
                            }
                          }}
                        >
                          {r < 1 ? `${r * 1000}m` : `${r}km`}
                        </button>
                      ))}
                    </div>
                  </div>

                  <button
                    style={{
                      ...styles.searchAreaMainBtn,
                      opacity: isSearchingLocation || isDiscoveringArea ? 0.7 : 1,
                    }}
                    onClick={() => handleExecuteAreaSearch(selectedLocation || undefined)}
                    disabled={isSearchingLocation || isDiscoveringArea || !discoveryQuery.trim()}
                  >
                    {isSearchingLocation || isDiscoveringArea ? 'DISCOVERING AREA WATER BODIES...' : '🔍 DISCOVER WATER BODIES IN AREA'}
                  </button>

                  {/* Success / Info note */}
                  {discoverySuccess && (
                    <div style={styles.discoverySuccessNote}>
                      {discoverySuccess}
                    </div>
                  )}

                  {/* Discovery Error */}
                  {discoveryError && (
                    <div style={styles.errorTextSmall}>
                      {discoveryError}
                    </div>
                  )}
                </div>

                {/* Discovered Water Bodies Results */}
                {areaDiscoveryData && (
                  <div style={styles.sectionBlock}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <label style={styles.sectionLabel}>
                        DISCOVERED WATER BODIES ({areaDiscoveryData.total_discovered})
                      </label>
                      <button
                        style={styles.clearBtn}
                        onClick={() => {
                          setAreaDiscoveryData(null);
                          setSelectedDiscoveredWb(null);
                          setSelectedForImportIds(new Set());
                          setMatchedLocations([]);
                          setSelectedLocation(null);
                          setDiscoverySuccess(null);
                          setDiscoveryError(null);
                        }}
                      >
                        Clear
                      </button>
                    </div>

                    <div style={styles.areaInfoBox}>
                      <div><strong>Center:</strong> {areaDiscoveryData.center.latitude.toFixed(4)}, {areaDiscoveryData.center.longitude.toFixed(4)}</div>
                      <div><strong>Radius:</strong> {areaDiscoveryData.radius_km} km</div>
                    </div>

                    {/* Phase 3: Batch Selection Summary Bar */}
                    {selectedForImportIds.size > 0 && (
                      <div style={styles.selectionSummaryBar}>
                        <div style={styles.selectionCountLabel}>
                          <strong>{selectedForImportIds.size}</strong> WATER {selectedForImportIds.size === 1 ? 'BODY' : 'BODIES'} SELECTED FOR IMPORT
                        </div>
                        <div style={styles.selectionBarActions}>
                          <button
                            type="button"
                            style={styles.batchImportBtn}
                            disabled={isRegisteringWb}
                            onClick={handleBatchImport}
                          >
                            {isRegisteringWb ? 'IMPORTING...' : `⬇ IMPORT SELECTED (${selectedForImportIds.size})`}
                          </button>
                          <button
                            type="button"
                            style={styles.clearSelectionBtn}
                            onClick={handleClearSelection}
                            disabled={isRegisteringWb}
                          >
                            CLEAR
                          </button>
                        </div>
                      </div>
                    )}

                    {/* Phase 3: Quick Action Row */}
                    {areaDiscoveryData.results.length > 0 && (
                      <div style={styles.quickActionRow}>
                        <button
                          type="button"
                          style={styles.quickActionBtn}
                          onClick={handleSelectAllUnregistered}
                        >
                          Select All Unregistered
                        </button>
                        {selectedForImportIds.size > 0 && (
                          <button
                            type="button"
                            style={styles.quickActionBtn}
                            onClick={handleClearSelection}
                          >
                            Deselect All
                          </button>
                        )}
                      </div>
                    )}

                    <div style={styles.discoveredScrollList}>
                      {areaDiscoveryData.results.length === 0 ? (
                        <div style={styles.emptyResultsText}>
                          No water bodies found in this {areaDiscoveryData.radius_km} km zone. Try increasing radius to 5 km or 10 km.
                        </div>
                      ) : (
                        areaDiscoveryData.results.map((wb, idx) => {
                          const registered = isWbRegistered(wb);
                          const isSelected = selectedDiscoveredWb?.source_id === wb.source_id;
                          const isSelectedForImport = selectedForImportIds.has(wb.source_id);
                          const distFromCenter = (wb.centroid_lat != null && wb.centroid_lon != null && areaDiscoveryData.center)
                            ? calculateDistanceKm(areaDiscoveryData.center.latitude, areaDiscoveryData.center.longitude, wb.centroid_lat, wb.centroid_lon)
                            : null;

                          return (
                            <div
                              key={wb.source_id || idx}
                              style={{
                                ...styles.discoveredCard,
                                ...(isSelectedForImport ? styles.discoveredCardImportSelected : isSelected ? styles.discoveredCardSelected : {}),
                              }}
                              onClick={() => {
                                setSelectedDiscoveredWb(wb);
                                if (wb.centroid_lat != null && wb.centroid_lon != null) {
                                  setTargetBounds([
                                    [wb.centroid_lat - 0.008, wb.centroid_lon - 0.008],
                                    [wb.centroid_lat + 0.008, wb.centroid_lon + 0.008],
                                  ]);
                                  setFitTrigger(t => t + 1);
                                }
                              }}
                            >
                              <div style={styles.wbCardTitleRow}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '6px', minWidth: 0 }}>
                                  {!registered ? (
                                    <input
                                      type="checkbox"
                                      checked={isSelectedForImport}
                                      onChange={() => toggleSelectForImport(wb.source_id)}
                                      onClick={e => e.stopPropagation()}
                                      title="Select for batch import"
                                      style={{ cursor: 'pointer', margin: 0 }}
                                    />
                                  ) : (
                                    <span style={{ color: '#16a34a', fontSize: '0.75rem', fontWeight: 700 }} title="Already registered">✓</span>
                                  )}
                                  <span style={styles.wbCardTitle}>{wb.name || 'Unnamed Water Body'}</span>
                                </div>
                                <span style={styles.wbCardTypeBadge}>{wb.water_body_type || 'water'}</span>
                              </div>

                              <div style={styles.wbCardMetaRow}>
                                <span>Area: {wb.area_sq_km ? `${wb.area_sq_km.toFixed(2)} km²` : 'N/A'}</span>
                                {distFromCenter != null && (
                                  <span style={{ color: '#0284c7', fontWeight: 600 }}>{formatDistance(distFromCenter)} away</span>
                                )}
                                <span>{wb.provider}</span>
                              </div>

                              <div style={styles.wbCardActionRow}>
                                {registered ? (
                                  <span style={styles.badgeAlreadyAdded}>✓ IN JALNETRA</span>
                                ) : (
                                  <div style={{ display: 'flex', gap: '6px' }}>
                                    <button
                                      type="button"
                                      style={isSelectedForImport ? styles.selectToggleBtnActive : styles.selectToggleBtn}
                                      onClick={(e) => {
                                        e.stopPropagation();
                                        toggleSelectForImport(wb.source_id);
                                      }}
                                    >
                                      {isSelectedForImport ? '✓ SELECTED' : '+ SELECT'}
                                    </button>
                                    <button
                                      type="button"
                                      style={styles.addWbBtn}
                                      disabled={isRegisteringWb}
                                      onClick={(e) => {
                                        e.stopPropagation();
                                        handleRegisterWaterBody(wb);
                                      }}
                                    >
                                      {isRegisteringWb && selectedDiscoveredWb?.source_id === wb.source_id ? 'ADDING...' : '+ ADD TO JALNETRA'}
                                    </button>
                                  </div>
                                )}
                              </div>
                            </div>
                          );
                        })
                      )}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* ── Tab: LAYERS ─────────────────────────────────────────────── */}
            {activeSidebarTab === 'layers' && (
              <div style={styles.tabContent}>
                {/* Water Body selector */}
                <div style={styles.sectionBlock}>
                  <label style={styles.sectionLabel}>SELECTED WATER BODY</label>
                  {(!geoJsonData?.features || geoJsonData.features.length === 0) ? (
                    <div style={{
                      padding: '0.75rem',
                      backgroundColor: 'var(--color-surface-subtle)',
                      border: '1px dashed var(--border-color)',
                      fontSize: '0.75rem',
                      color: 'var(--color-text-secondary)',
                      lineHeight: 1.4,
                    }}>
                      <div>No water bodies registered yet. Search and discover any area using the <b>DISCOVERY</b> tab.</div>
                      <button
                        style={styles.openDiscoveryBtn}
                        onClick={() => setActiveSidebarTab('discovery')}
                      >
                        🔍 OPEN AREA DISCOVERY
                      </button>
                    </div>
                  ) : (
                    <select
                      style={styles.selectInput}
                      value={selectedWaterBodyId}
                      onChange={(e) => handleSelectWaterBody(e.target.value)}
                    >
                      {geoJsonData.features.map((f: any) => (
                        <option key={f.properties.id} value={f.properties.id}>
                          {f.properties.name} {f.properties.country ? `(${f.properties.country})` : ''}
                        </option>
                      ))}
                    </select>
                  )}

                  {selectedWaterBodyProps && (
                    <div style={styles.wbInfoCard}>
                      {selectedWaterBodyProps.water_body_type && (
                        <div style={styles.wbInfoRow}>
                          <span style={styles.wbInfoKey}>Type:</span>
                          <span>{selectedWaterBodyProps.water_body_type}</span>
                        </div>
                      )}
                      {selectedWaterBodyProps.area_sq_km && (
                        <div style={styles.wbInfoRow}>
                          <span style={styles.wbInfoKey}>Area:</span>
                          <span>{Number(selectedWaterBodyProps.area_sq_km).toFixed(2)} km²</span>
                        </div>
                      )}
                      <button style={styles.refocusBtn} onClick={handleFocusToWaterBody}>
                        FOCUS MAP TO WATER BODY
                      </button>

                      <CompactWeatherBadge
                        waterBodyId={selectedWaterBodyId}
                        onNavigateToAnalysis={onNavigateToAnalysis}
                      />

                      <div style={styles.wbActionGroup}>
                        <button
                          style={styles.fetchVisualDataBtn}
                          onClick={() => setIsFetchVisualDataOpen(true)}
                        >
                          🛰 FETCH VISUAL DATA
                        </button>
                        {onNavigateToAnalysis && (
                          <button
                            style={styles.openAnalysisBtn}
                            onClick={() => onNavigateToAnalysis(selectedWaterBodyId)}
                          >
                            📈 OPEN IN ANALYSIS PAGE →
                          </button>
                        )}
                      </div>
                    </div>
                  )}
                </div>

                {/* Layer Visibility */}
                <div style={styles.sectionBlock}>
                  <label style={styles.sectionLabel}>LAYER VISIBILITY &amp; OPACITY</label>

                  <LayerRow label="1. Base Map" checked={showBaseMap} onChange={setShowBaseMap} />
                  <LayerRow label="2. Water Body Vector Boundaries" checked={showWaterBodies} onChange={setShowWaterBodies} />
                  <LayerRow
                    label="3. Satellite Raster Extent (AOI)"
                    checked={showRasterExtent}
                    onChange={setShowRasterExtent}
                    disabled={!rasterOverlayBounds}
                  />

                  <LayerRow
                    label={`4. Sentinel-2 RGB Overlay ${rgbData ? `(${rgbData.width}×${rgbData.height} • 10m)` : ''}`}
                    checked={showRgbImagery}
                    onChange={setShowRgbImagery}
                    loading={isLoadingRgb}
                  />
                  {showRgbImagery && (
                    <OpacitySlider label="RGB" value={rasterOpacity} onChange={setRasterOpacity} />
                  )}

                  <LayerRow
                    label={`5. Cloud/Shadow Mask ${currentProc.cloudVis ? '' : '(Not run)'}`}
                    checked={showCloudMask}
                    onChange={setShowCloudMask}
                    disabled={!currentProc.cloudVis}
                  />
                  {showCloudMask && currentProc.cloudVis && (
                    <OpacitySlider label="Cloud Mask" value={cloudMaskOpacity} onChange={setCloudMaskOpacity} />
                  )}

                  <LayerRow
                    label={`6. Detected Water ${currentProc.waterVis ? '' : '(Not run)'}`}
                    checked={showWaterMask}
                    onChange={setShowWaterMask}
                    disabled={!currentProc.waterVis}
                  />
                  {showWaterMask && currentProc.waterVis && (
                    <OpacitySlider label="Water Mask" value={waterMaskOpacity} onChange={setWaterMaskOpacity} />
                  )}

                  <LayerRow
                    label="Scene Footprint (Full Tile 100km)"
                    checked={showSceneFootprint}
                    onChange={setShowSceneFootprint}
                  />
                </div>

                {/* Legend */}
                <div style={styles.sectionBlock}>
                  <label style={styles.sectionLabel}>MAP SYMBOLOGY</label>
                  <div style={styles.legendList}>
                    <LegendRow color="rgba(34,197,94,0.3)" borderColor="#15803d" label="Water Body Vector" />
                    <LegendRow color="rgba(251,146,60,0.4)" borderColor="#c2410c" label="Selected Water Body" />
                    <LegendRow color="rgba(2,132,199,0.05)" borderColor="#0284c7" label="Satellite Raster Extent (AOI)" dashed />
                    <LegendRow color="#38bdf8" borderColor="#0284c7" label="Sentinel-2 RGB Overlay" />
                    <LegendRow color="#f59e0b" borderColor="#d97706" label="Cloud/Shadow Mask" />
                    <LegendRow color="#0ea5e9" borderColor="#0284c7" label="Detected Water" />
                    {showSceneFootprint && (
                      <LegendRow color="transparent" borderColor="#ea580c" label="Full Scene Footprint (100km)" dashed />
                    )}
                    {aoiMode === 'manual' && manualAoi && (
                      <LegendRow color="rgba(245,158,11,0.1)" borderColor="#f59e0b" label="Manual AOI" dashed />
                    )}
                    {areaDiscoveryData && (
                      <>
                        <LegendRow color="rgba(6,182,212,0.06)" borderColor="#0891b2" label={`Search Radius Area (${areaDiscoveryData.radius_km}km)`} dashed />
                        <LegendRow color="#22d3ee" borderColor="#0891b2" label="Discovered Water Body" />
                      </>
                    )}
                  </div>
                </div>
              </div>
            )}

            {/* ── Tab: SCENES ─────────────────────────────────────────────── */}
            {activeSidebarTab === 'scenes' && (
              <div style={styles.tabContent}>
                {/* Refresh + acquire notice */}
                <div style={styles.sectionBlock}>
                  <label style={styles.sectionLabel}>
                    REGISTERED SCENES ({scenes.length})
                  </label>

                  <button
                    style={styles.refreshBtn}
                    onClick={handleRefetchScenes}
                    disabled={isRefetchingScenes || !selectedWaterBodyId}
                  >
                    {isRefetchingScenes ? 'SEARCHING STAC...' : '⟳ REFRESH / SEARCH NEW SCENES'}
                  </button>

                  {refetchError && (
                    <div style={styles.errorTextSmall}>{refetchError}</div>
                  )}
                  {acquireMessage && (
                    <div style={styles.acquireMessage}>{acquireMessage}</div>
                  )}
                </div>

                {/* Scene list */}
                <div style={styles.scenesScrollList}>
                  {scenes.length === 0 ? (
                    <div style={styles.emptyNotice}>
                      No scenes registered. Use ⟳ to search STAC or go to "Satellite Acquisition" tab.
                    </div>
                  ) : (
                    scenes.map((sc, index) => {
                      const isSelected = sc.scene_id === selectedSceneId;
                      const isTop = index === 0;
                      const isAcquiring = acquiringSceneId === sc.scene_id;

                      return (
                        <div
                          key={sc.scene_id}
                          style={{
                            ...styles.sceneCard,
                            borderColor: isSelected ? 'var(--color-primary)' : 'var(--border-color)',
                            backgroundColor: isSelected ? 'var(--color-primary-subtle)' : 'var(--color-surface)',
                          }}
                        >
                          {/* Clickable top part to select */}
                          <div
                            style={{ cursor: 'pointer' }}
                            onClick={() => handleSelectScene(sc, selectedWaterBodyId, false)}
                          >
                            <div style={styles.sceneCardTopRow}>
                              <span style={styles.sceneExternalId} title={sc.external_scene_id}>
                                {sc.external_scene_id}
                              </span>
                              {isSelected && isAutoSelected ? (
                                <span style={styles.badgeAutoSelected}>✓ AUTO</span>
                              ) : isSelected ? (
                                <span style={styles.badgeManualSelected}>MANUAL</span>
                              ) : isTop ? (
                                <span style={styles.badgeCandidate}>BEST</span>
                              ) : null}
                            </div>

                            <div style={styles.sceneCardMetaRow}>
                              <span>{new Date(sc.sensing_start).toLocaleDateString()}</span>
                              <span>Cloud: {sc.cloud_cover_percent != null ? `${sc.cloud_cover_percent.toFixed(1)}%` : 'N/A'}</span>
                              <span style={sc.has_rgb ? styles.badgeRgbReady : styles.badgePartialBands}>
                                {sc.has_rgb ? 'RGB ✓' : 'PARTIAL'}
                              </span>
                            </div>

                            <div style={styles.sceneCardFooterRow}>
                              <span style={sc.covers_water_body ? styles.textCoverageYes : styles.textCoverageNo}>
                                {sc.covers_water_body ? '● Covers WB' : '○ Partial/Ext'}
                              </span>
                              <span style={styles.assetsLabel}>
                                {sc.downloaded_assets.join(', ') || 'no assets'}
                              </span>
                            </div>
                          </div>

                          {/* Acquire button */}
                          {!sc.has_rgb && (
                            <button
                              style={styles.acquireBtn}
                              disabled={isAcquiring}
                              onClick={() => handleAcquireScene(sc)}
                            >
                              {isAcquiring ? 'ACQUIRING...' : '⬇ ACQUIRE SCENE ASSETS'}
                            </button>
                          )}
                        </div>
                      );
                    })
                  )}
                </div>

                {/* Phase 5 Processing for selected scene */}
                {selectedSceneItem && (
                  <div style={styles.procSection}>
                    <label style={styles.sectionLabel}>PHASE 5 PROCESSING — SCENE: {selectedSceneItem.external_scene_id.slice(0, 20)}…</label>

                    {currentProc.error && (
                      <div style={styles.errorTextSmall}>{currentProc.error}</div>
                    )}

                    <div style={styles.pillsRow}>
                      <ProcPill
                        label="Cloud Mask"
                        ready={!!currentProc.status?.cloud_mask_available}
                        processing={currentProc.isProcessing}
                        failed={!!currentProc.error}
                      />
                      <ProcPill
                        label="Water Mask"
                        ready={!!currentProc.status?.water_mask_available}
                        processing={currentProc.isProcessing}
                        failed={!!currentProc.error}
                      />
                    </div>

                    <button
                      style={{
                        ...styles.runAnalysisBtn,
                        backgroundColor: currentProc.error
                          ? '#dc2626'
                          : currentProc.status?.status === 'ready'
                            ? '#16a34a'
                            : 'var(--color-primary)',
                      }}
                      onClick={() => handleRunProcessing(true)}
                      disabled={currentProc.isProcessing}
                    >
                      {currentProc.isProcessing
                        ? 'PROCESSING CLOUD & WATER ANALYSIS...'
                        : currentProc.error
                          ? '✕ PROCESSING FAILED — CLICK TO RETRY'
                          : currentProc.status?.status === 'ready'
                            ? '✓ MASKS READY — CLICK TO RE-RUN'
                            : 'RUN CLOUD & WATER ANALYSIS'}
                    </button>

                    {sceneMetadata && (
                      <div style={styles.sceneMetaBox}>
                        <div style={styles.sceneMetaRow}>
                          <span style={styles.sceneMetaKey}>CRS:</span>
                          <span style={styles.sceneMetaVal}>{sceneMetadata.crs || 'UTM auto'}</span>
                        </div>
                        <div style={styles.sceneMetaRow}>
                          <span style={styles.sceneMetaKey}>Extent:</span>
                          <span style={styles.sceneMetaVal}>{rgbData?.is_focused ? 'WB Cropped' : 'Full Tile'}</span>
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}

            {/* ── Tab: AOI ────────────────────────────────────────────────── */}
            {activeSidebarTab === 'aoi' && (
              <div style={styles.tabContent}>
                <div style={styles.sectionBlock}>
                  <label style={styles.sectionLabel}>AREA OF INTEREST (AOI) MODE</label>

                  <div style={styles.aoiModeToggle}>
                    <button
                      style={{ ...styles.aoiModeBtn, ...(aoiMode === 'auto' ? styles.aoiModeBtnActive : {}) }}
                      onClick={() => { setAoiMode('auto'); setIsDrawingAoi(false); }}
                    >
                      AUTO (Water Body)
                    </button>
                    <button
                      style={{ ...styles.aoiModeBtn, ...(aoiMode === 'manual' ? styles.aoiModeBtnActive : {}) }}
                      onClick={() => setAoiMode('manual')}
                    >
                      MANUAL (Draw)
                    </button>
                  </div>
                </div>

                {aoiMode === 'auto' && (
                  <div style={styles.sectionBlock}>
                    <label style={styles.sectionLabel}>AUTO PADDING: {autoPaddingPct}%</label>
                    <input
                      type="range"
                      min={5} max={25} step={5}
                      value={autoPaddingPct}
                      onChange={e => setAutoPaddingPct(Number(e.target.value))}
                      style={styles.rangeSlider}
                    />
                    <div style={styles.paddingSteps}>
                      {[5, 10, 15, 20, 25].map(v => (
                        <span
                          key={v}
                          style={{ ...styles.paddingStep, fontWeight: v === autoPaddingPct ? 700 : 400 }}
                          onClick={() => setAutoPaddingPct(v)}
                        >
                          {v}%
                        </span>
                      ))}
                    </div>
                    <button style={styles.refocusBtn} onClick={handleFocusToWaterBody}>
                      APPLY PADDING &amp; FOCUS MAP
                    </button>
                  </div>
                )}

                {aoiMode === 'manual' && (
                  <div style={styles.sectionBlock}>
                    <p style={styles.aoiHelpText}>
                      Draw a rectangle on the map to define a custom AOI for satellite imagery. The drawn AOI will be used to filter and focus imagery.
                    </p>

                    {manualAoi ? (
                      <div style={styles.aoiInfoCard}>
                        <div style={styles.wbInfoRow}>
                          <span style={styles.wbInfoKey}>SW:</span>
                          <span>{manualAoi[0][0].toFixed(4)}°, {manualAoi[0][1].toFixed(4)}°</span>
                        </div>
                        <div style={styles.wbInfoRow}>
                          <span style={styles.wbInfoKey}>NE:</span>
                          <span>{manualAoi[1][0].toFixed(4)}°, {manualAoi[1][1].toFixed(4)}°</span>
                        </div>
                      </div>
                    ) : (
                      <div style={styles.aoiEmptyNotice}>No AOI drawn yet.</div>
                    )}

                    <button
                      style={{
                        ...styles.drawAoiBtn,
                        ...(isDrawingAoi ? styles.drawAoiBtnActive : {}),
                      }}
                      onClick={() => setIsDrawingAoi(v => !v)}
                    >
                      {isDrawingAoi ? '✕ CANCEL DRAWING' : '✎ DRAW RECTANGLE ON MAP'}
                    </button>

                    {manualAoi && (
                      <>
                        <button
                          style={styles.fetchAoiBtn}
                          onClick={() => handleFetchAoiImagery(manualAoi)}
                        >
                          FETCH SATELLITE DATA FOR AOI
                        </button>
                        <button
                          style={styles.clearAoiBtn}
                          onClick={handleClearAoi}
                        >
                          CLEAR AOI
                        </button>
                      </>
                    )}
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </FloatingPanel>

      {/* ── Bottom Metrics Bar ────────────────────────────────────────────── */}
      {currentProc.status?.status === 'ready' && currentProc.status.water_detection && (
        <FloatingPanel style={styles.metricsBar}>
          <div style={styles.metricsHeaderBar}>
            <span style={styles.metricsHeaderTitle}>
              OBSERVATIONAL METRICS — {selectedSceneItem?.external_scene_id?.slice(0, 25)}
            </span>
            <button style={styles.collapseMetricsBtn} onClick={() => setMetricsCollapsed(v => !v)}>
              {metricsCollapsed ? 'SHOW ▲' : 'HIDE ▼'}
            </button>
          </div>
          {!metricsCollapsed && (
            <div style={styles.metricsGrid}>
              <MetricCell
                label="WATER EXTENT"
                value={`${currentProc.status.water_detection.water_extent_percentage_of_valid}% of valid`}
                primary
              />
              <MetricCell
                label="WATER AREA"
                value={currentProc.status.water_detection.estimated_water_area_sq_km != null
                  ? `${currentProc.status.water_detection.estimated_water_area_sq_km.toFixed(2)} km²`
                  : 'N/A'}
                primary
              />
              <MetricCell
                label="CLOUD/SHADOW"
                value={currentProc.status.cloud_mask?.cloud_shadow_percentage != null
                  ? `${currentProc.status.cloud_mask.cloud_shadow_percentage}%`
                  : 'N/A'}
              />
              <MetricCell
                label="VALID PIXELS"
                value={currentProc.status.cloud_mask?.valid_pixel_percentage != null
                  ? `${currentProc.status.cloud_mask.valid_pixel_percentage}%`
                  : 'N/A'}
              />
              <MetricCell
                label="METHOD"
                value={`${currentProc.status.water_detection.method} (> ${currentProc.status.water_detection.threshold})`}
              />
            </div>
          )}
        </FloatingPanel>
      )}

      {isFetchVisualDataOpen && selectedWaterBodyObj && (
        <FetchVisualDataModal
          waterBody={selectedWaterBodyObj}
          isOpen={isFetchVisualDataOpen}
          onClose={() => setIsFetchVisualDataOpen(false)}
          onNavigateToAnalysis={(wbId) => {
            setIsFetchVisualDataOpen(false);
            if (onNavigateToAnalysis) {
              onNavigateToAnalysis(wbId);
            }
          }}
        />
      )}
    </div>
  );
};

// ─── Micro-components ──────────────────────────────────────────────────────────
interface LayerRowProps {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
  loading?: boolean;
}
const LayerRow: React.FC<LayerRowProps> = ({ label, checked, onChange, disabled, loading }) => (
  <div style={styles.layerItemRow}>
    <label style={{ ...styles.checkboxLabel, opacity: disabled ? 0.5 : 1 }}>
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={e => onChange(e.target.checked)}
      />
      <span>{label}</span>
      {loading && <span style={styles.loadingDot}>⟳</span>}
    </label>
  </div>
);

interface OpacitySliderProps {
  label: string;
  value: number;
  onChange: (v: number) => void;
}
const OpacitySlider: React.FC<OpacitySliderProps> = ({ label, value, onChange }) => (
  <div style={styles.opacityBox}>
    <div style={styles.opacityLabelRow}>
      <span>{label} Opacity</span>
      <span style={styles.monoPercent}>{Math.round(value * 100)}%</span>
    </div>
    <input
      type="range" min="0.1" max="1.0" step="0.05"
      value={value}
      onChange={e => onChange(parseFloat(e.target.value))}
      style={styles.rangeSlider}
    />
  </div>
);

interface LegendRowProps {
  color: string;
  borderColor: string;
  label: string;
  dashed?: boolean;
}
const LegendRow: React.FC<LegendRowProps> = ({ color, borderColor, label, dashed }) => (
  <div style={styles.legendRow}>
    <span style={{
      ...styles.legendBox,
      backgroundColor: color,
      borderColor,
      borderStyle: dashed ? 'dashed' : 'solid',
    }} />
    <span>{label}</span>
  </div>
);

interface ProcPillProps {
  label: string;
  ready: boolean;
  processing?: boolean;
  failed?: boolean;
}
const ProcPill: React.FC<ProcPillProps> = ({ label, ready, processing, failed }) => (
  <div style={styles.statusPillItem}>
    <span style={styles.statusPillTag}>{label}:</span>
    <span
      style={
        ready
          ? styles.pillTagReady
          : failed
            ? styles.pillTagFailed
            : processing
              ? styles.pillTagProcessing
              : styles.pillTagPending
      }
    >
      {ready ? '✓ Ready' : failed ? '✕ Failed' : processing ? '● Running...' : '○ Pending'}
    </span>
  </div>
);

interface MetricCellProps { label: string; value: string; primary?: boolean; }
const MetricCell: React.FC<MetricCellProps> = ({ label, value, primary }) => (
  <div style={styles.metricCell}>
    <span style={styles.metricKey}>{label}</span>
    <span style={primary ? styles.metricValPrimary : styles.metricVal}>{value}</span>
  </div>
);

// ─── Styles ────────────────────────────────────────────────────────────────────
const styles: Record<string, React.CSSProperties> = {
  pageContainer: {
    position: 'relative',
    flex: 1,
    width: '100%',
    height: '100%',
    minHeight: '600px',
    overflow: 'hidden',
    backgroundColor: '#0f172a',
  },
  mapCanvas: {
    position: 'absolute',
    inset: 0,
    width: '100%',
    height: '100%',
    minHeight: '600px',
    zIndex: 1,
  },
  mapContainer: {
    width: '100%',
    height: '100%',
    minHeight: '600px',
  },

  // ── Top pill ────────────────────────────────────────────────────────────────
  topStatusPill: {
    position: 'absolute',
    top: '10px',
    left: '50%',
    transform: 'translateX(-50%)',
    zIndex: 1020,
    backgroundColor: 'rgba(255,255,255,0.96)',
    border: '1px solid var(--border-color)',
    padding: '0.3rem 0.85rem',
    display: 'flex',
    alignItems: 'center',
    gap: '0.55rem',
    fontSize: '0.7rem',
    boxShadow: '0 2px 6px rgba(0,0,0,0.12)',
    whiteSpace: 'nowrap',
  },
  statusDotLive: {
    width: '8px',
    height: '8px',
    borderRadius: '50%',
    backgroundColor: '#15803d',
    flexShrink: 0,
  },
  topStatusTitle: { fontWeight: 700, letterSpacing: '0.04em', color: 'var(--color-primary-dark)' },
  topStatusDivider: { color: '#94a3b8', fontWeight: 300 },
  topStatusMeta: { fontFamily: 'var(--font-mono)', color: 'var(--color-text-secondary)' },
  badgeCropActive: {
    fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: '0.65rem',
    color: '#c2410c', backgroundColor: '#ffedd5', padding: '0.1rem 0.35rem',
    border: '1px solid #fed7aa',
  },
  badgeDrawing: {
    fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: '0.65rem',
    color: '#92400e', backgroundColor: '#fef3c7', padding: '0.1rem 0.35rem',
    border: '1px solid #fde68a', animation: 'pulse 1s infinite',
  },
  sensingDateBadge: {
    fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: '0.65rem',
    color: '#0369a1', backgroundColor: '#e0f2fe', padding: '0.1rem 0.35rem',
    border: '1px solid #bae6fd',
  },

  // ── Error banner ────────────────────────────────────────────────────────────
  errorBanner: {
    position: 'absolute',
    top: '48px',
    left: '50%',
    transform: 'translateX(-50%)',
    zIndex: 1030,
    backgroundColor: '#fef2f2',
    border: '1px solid #ef4444',
    color: '#991b1b',
    padding: '0.45rem 1rem',
    fontSize: '0.78rem',
    display: 'flex',
    alignItems: 'center',
    gap: '1rem',
    boxShadow: '0 2px 6px rgba(0,0,0,0.12)',
    maxWidth: '600px',
  },
  closeBtn: {
    background: 'none', border: 'none', cursor: 'pointer',
    color: '#991b1b', fontWeight: 700, padding: 0,
  },

  // ── Sidebar ─────────────────────────────────────────────────────────────────
  sidebar: {
    position: 'absolute',
    top: '10px',
    left: '10px',
    bottom: '10px',
    zIndex: 1010,
    backgroundColor: 'rgba(255,255,255,0.97)',
    border: '1px solid var(--border-color)',
    boxShadow: '0 4px 16px rgba(0,0,0,0.15)',
    display: 'flex',
    flexDirection: 'column',
    transition: 'width 0.2s ease',
    overflow: 'hidden',
  },
  sidebarHeader: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: '0.5rem 0.6rem',
    backgroundColor: 'var(--color-surface-subtle)',
    borderBottom: '1px solid var(--border-color)',
    flexShrink: 0,
  },
  sidebarHeaderTitle: {
    fontSize: '0.68rem',
    fontWeight: 700,
    letterSpacing: '0.05em',
    color: 'var(--color-primary-dark)',
  },
  sidebarCollapseBtn: {
    background: 'none',
    border: 'none',
    cursor: 'pointer',
    color: 'var(--color-text-secondary)',
    fontSize: '0.78rem',
    fontWeight: 700,
    padding: '0.1rem 0.2rem',
    lineHeight: 1,
  },

  // ── Tab bar ─────────────────────────────────────────────────────────────────
  tabBar: {
    display: 'flex',
    borderBottom: '1px solid var(--border-color)',
    flexShrink: 0,
    backgroundColor: 'var(--color-surface-subtle)',
  },
  tabBtn: {
    flex: 1,
    padding: '0.45rem 0',
    background: 'none',
    border: 'none',
    borderBottom: '2px solid transparent',
    cursor: 'pointer',
    fontSize: '0.65rem',
    fontWeight: 700,
    letterSpacing: '0.04em',
    color: 'var(--color-text-secondary)',
  },
  tabBtnActive: {
    borderBottomColor: 'var(--color-primary)',
    color: 'var(--color-primary)',
  },
  tabContent: {
    flex: 1,
    overflowY: 'auto',
    padding: '0.65rem',
    display: 'flex',
    flexDirection: 'column',
    gap: '0.75rem',
  },

  // ── Section blocks ───────────────────────────────────────────────────────────
  sectionBlock: {
    display: 'flex',
    flexDirection: 'column',
    gap: '0.35rem',
  },
  sectionLabel: {
    fontSize: '0.66rem',
    fontWeight: 700,
    letterSpacing: '0.04em',
    color: 'var(--color-text-secondary)',
    textTransform: 'uppercase' as const,
  },
  selectInput: {
    width: '100%',
    padding: '0.42rem',
    border: '1px solid var(--border-color)',
    backgroundColor: '#fff',
    fontSize: '0.78rem',
    fontWeight: 500,
    cursor: 'pointer',
  },
  wbInfoCard: {
    padding: '0.45rem',
    backgroundColor: 'var(--color-surface-subtle)',
    border: '1px solid var(--border-color)',
    display: 'flex',
    flexDirection: 'column',
    gap: '0.22rem',
    fontSize: '0.72rem',
  },
  wbInfoRow: {
    display: 'flex',
    justifyContent: 'space-between',
    fontSize: '0.7rem',
  },
  wbInfoKey: { fontWeight: 600, color: 'var(--color-text-secondary)' },
  refocusBtn: {
    marginTop: '0.2rem',
    padding: '0.35rem',
    backgroundColor: '#fff',
    border: '1px solid var(--border-color)',
    color: 'var(--color-primary)',
    fontWeight: 700,
    fontSize: '0.66rem',
    cursor: 'pointer',
    textAlign: 'center' as const,
    letterSpacing: '0.03em',
  },

  // ── Layer rows ───────────────────────────────────────────────────────────────
  layerItemRow: { padding: '0.12rem 0' },
  checkboxLabel: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.4rem',
    fontSize: '0.74rem',
    fontWeight: 500,
    cursor: 'pointer',
  },
  loadingDot: { fontSize: '0.7rem', color: '#c2410c', animation: 'spin 1s linear infinite' },
  opacityBox: { paddingLeft: '1.2rem', marginBottom: '0.2rem' },
  opacityLabelRow: {
    display: 'flex',
    justifyContent: 'space-between',
    fontSize: '0.66rem',
    color: 'var(--color-text-secondary)',
    marginBottom: '0.12rem',
  },
  monoPercent: {
    fontFamily: 'var(--font-mono)',
    fontWeight: 600,
    color: 'var(--color-primary)',
  },
  rangeSlider: { width: '100%', cursor: 'pointer' },

  // ── Legend ──────────────────────────────────────────────────────────────────
  legendList: {
    display: 'flex',
    flexDirection: 'column',
    gap: '0.28rem',
    fontSize: '0.7rem',
  },
  legendRow: { display: 'flex', alignItems: 'center', gap: '0.45rem' },
  legendBox: {
    width: '11px',
    height: '11px',
    flexShrink: 0,
    border: '1px solid',
  },

  // ── Scenes tab ───────────────────────────────────────────────────────────────
  refreshBtn: {
    width: '100%',
    padding: '0.4rem',
    backgroundColor: 'var(--color-surface-subtle)',
    border: '1px solid var(--border-color)',
    color: 'var(--color-primary)',
    fontWeight: 700,
    fontSize: '0.68rem',
    cursor: 'pointer',
    letterSpacing: '0.03em',
  },
  errorTextSmall: {
    fontSize: '0.68rem',
    color: '#b91c1c',
    padding: '0.2rem',
  },
  acquireMessage: {
    fontSize: '0.68rem',
    color: '#15803d',
    padding: '0.2rem',
    backgroundColor: '#f0fdf4',
    border: '1px solid #bbf7d0',
  },
  scenesScrollList: {
    display: 'flex',
    flexDirection: 'column',
    gap: '0.4rem',
    maxHeight: '260px',
    overflowY: 'auto',
  },
  emptyNotice: {
    fontSize: '0.7rem',
    fontStyle: 'italic',
    color: 'var(--color-text-muted)',
    padding: '0.4rem',
  },
  sceneCard: {
    padding: '0.42rem',
    border: '1px solid var(--border-color)',
    display: 'flex',
    flexDirection: 'column',
    gap: '0.22rem',
    fontSize: '0.7rem',
    transition: 'background-color 0.1s',
  },
  sceneCardTopRow: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  sceneExternalId: {
    fontFamily: 'var(--font-mono)',
    fontWeight: 700,
    fontSize: '0.65rem',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap' as const,
    maxWidth: '170px',
  },
  badgeAutoSelected: {
    fontSize: '0.6rem', fontWeight: 700,
    color: '#15803d', backgroundColor: '#dcfce7',
    border: '1px solid #bbf7d0', padding: '0.08rem 0.28rem',
    flexShrink: 0,
  },
  badgeManualSelected: {
    fontSize: '0.6rem', fontWeight: 700,
    color: '#0369a1', backgroundColor: '#e0f2fe',
    border: '1px solid #bae6fd', padding: '0.08rem 0.28rem',
    flexShrink: 0,
  },
  badgeCandidate: {
    fontSize: '0.6rem', fontWeight: 700,
    color: '#6b7280', backgroundColor: '#f3f4f6',
    padding: '0.08rem 0.28rem', flexShrink: 0,
  },
  sceneCardMetaRow: {
    display: 'flex',
    justifyContent: 'space-between',
    fontSize: '0.66rem',
    color: 'var(--color-text-secondary)',
  },
  badgeRgbReady: { fontWeight: 700, color: '#15803d', fontSize: '0.62rem' },
  badgePartialBands: { fontWeight: 700, color: '#b45309', fontSize: '0.62rem' },
  sceneCardFooterRow: {
    display: 'flex',
    justifyContent: 'space-between',
    fontSize: '0.63rem',
    color: 'var(--color-text-muted)',
    borderTop: '1px dashed #e2e8f0',
    paddingTop: '0.18rem',
  },
  textCoverageYes: { color: '#15803d', fontWeight: 600 },
  textCoverageNo: { color: '#94a3b8' },
  assetsLabel: {
    fontFamily: 'var(--font-mono)',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap' as const,
    maxWidth: '130px',
  },
  acquireBtn: {
    width: '100%',
    padding: '0.32rem',
    marginTop: '0.1rem',
    backgroundColor: '#fff',
    border: '1px solid var(--color-primary)',
    color: 'var(--color-primary)',
    fontWeight: 700,
    fontSize: '0.64rem',
    cursor: 'pointer',
    letterSpacing: '0.03em',
  },

  // ── Processing section ───────────────────────────────────────────────────────
  procSection: {
    borderTop: '1px solid var(--border-color)',
    paddingTop: '0.5rem',
    display: 'flex',
    flexDirection: 'column',
    gap: '0.35rem',
  },
  pillsRow: { display: 'flex', gap: '0.35rem' },
  statusPillItem: {
    flex: 1,
    padding: '0.28rem 0.4rem',
    backgroundColor: 'var(--color-surface-subtle)',
    border: '1px solid var(--border-color)',
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    fontSize: '0.65rem',
  },
  statusPillTag: { fontWeight: 600, color: 'var(--color-text-secondary)' },
  pillTagReady: {
    fontWeight: 700, color: '#15803d',
    backgroundColor: '#dcfce7', padding: '0.04rem 0.22rem',
  },
  pillTagPending: {
    fontWeight: 700, color: '#b45309',
    backgroundColor: '#fef3c7', padding: '0.04rem 0.22rem',
  },
  runAnalysisBtn: {
    width: '100%',
    padding: '0.42rem',
    backgroundColor: 'var(--color-primary)',
    color: '#fff',
    border: 'none',
    fontWeight: 700,
    fontSize: '0.68rem',
    letterSpacing: '0.04em',
    cursor: 'pointer',
  },
  sceneMetaBox: {
    padding: '0.32rem 0.4rem',
    backgroundColor: 'var(--color-surface-subtle)',
    border: '1px solid var(--border-color)',
    display: 'flex',
    flexDirection: 'column',
    gap: '0.18rem',
    fontSize: '0.63rem',
  },
  sceneMetaRow: { display: 'flex', justifyContent: 'space-between' },
  sceneMetaKey: { color: 'var(--color-text-muted)', fontWeight: 600 },
  sceneMetaVal: { fontFamily: 'var(--font-mono)', fontWeight: 600 },

  // ── AOI tab ──────────────────────────────────────────────────────────────────
  aoiModeToggle: { display: 'flex', gap: '0.35rem' },
  aoiModeBtn: {
    flex: 1,
    padding: '0.38rem',
    backgroundColor: 'var(--color-surface-subtle)',
    border: '1px solid var(--border-color)',
    color: 'var(--color-text-secondary)',
    fontWeight: 700,
    fontSize: '0.65rem',
    cursor: 'pointer',
  },
  aoiModeBtnActive: {
    backgroundColor: 'var(--color-primary)',
    color: '#fff',
    borderColor: 'var(--color-primary)',
  },
  paddingSteps: {
    display: 'flex',
    justifyContent: 'space-between',
    fontSize: '0.65rem',
    color: 'var(--color-text-secondary)',
  },
  paddingStep: { cursor: 'pointer', padding: '0.1rem 0.2rem' },
  aoiHelpText: {
    fontSize: '0.7rem',
    color: 'var(--color-text-secondary)',
    lineHeight: 1.45,
    margin: 0,
  },
  aoiInfoCard: {
    padding: '0.42rem',
    backgroundColor: '#fffbeb',
    border: '1px solid #fde68a',
    fontSize: '0.7rem',
    display: 'flex',
    flexDirection: 'column',
    gap: '0.18rem',
  },
  aoiEmptyNotice: {
    fontSize: '0.7rem',
    fontStyle: 'italic',
    color: 'var(--color-text-muted)',
    padding: '0.3rem',
  },
  drawAoiBtn: {
    width: '100%',
    padding: '0.42rem',
    backgroundColor: '#fff',
    border: '2px solid #f59e0b',
    color: '#92400e',
    fontWeight: 700,
    fontSize: '0.68rem',
    cursor: 'pointer',
    letterSpacing: '0.03em',
  },
  drawAoiBtnActive: {
    backgroundColor: '#fef3c7',
    borderStyle: 'dashed',
  },
  clearAoiBtn: {
    width: '100%',
    padding: '0.35rem',
    backgroundColor: '#fff',
    border: '1px solid var(--border-color)',
    color: '#6b7280',
    fontWeight: 600,
    fontSize: '0.65rem',
    cursor: 'pointer',
  },

  // ── Metrics bar ──────────────────────────────────────────────────────────────
  metricsBar: {
    position: 'absolute',
    bottom: '10px',
    left: '338px',
    right: '10px',
    zIndex: 1010,
    backgroundColor: 'rgba(255,255,255,0.97)',
    border: '1px solid var(--border-color)',
    padding: '0.45rem 0.75rem',
    boxShadow: '0 4px 12px rgba(0,0,0,0.1)',
    fontSize: '0.7rem',
  },
  metricsHeaderBar: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    borderBottom: '1px solid var(--border-color)',
    paddingBottom: '0.22rem',
    marginBottom: '0.3rem',
  },
  metricsHeaderTitle: {
    fontSize: '0.66rem',
    fontWeight: 700,
    color: 'var(--color-primary-dark)',
    letterSpacing: '0.04em',
  },
  collapseMetricsBtn: {
    background: 'none',
    border: 'none',
    fontSize: '0.62rem',
    fontWeight: 700,
    color: 'var(--color-text-secondary)',
    cursor: 'pointer',
  },
  metricsGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))',
    gap: '0.4rem',
  },
  metricCell: {
    display: 'flex',
    flexDirection: 'column',
    gap: '0.08rem',
    padding: '0.22rem 0.35rem',
    backgroundColor: 'var(--color-surface-subtle)',
    border: '1px solid var(--border-color)',
  },
  metricKey: {
    fontSize: '0.6rem',
    fontWeight: 700,
    color: 'var(--color-text-muted)',
    textTransform: 'uppercase' as const,
  },
  metricVal: {
    fontSize: '0.72rem',
    fontFamily: 'var(--font-mono)',
    fontWeight: 600,
  },
  metricValPrimary: {
    fontSize: '0.72rem',
    fontFamily: 'var(--font-mono)',
    fontWeight: 700,
    color: 'var(--color-primary)',
  },
  fetchAoiBtn: {
    width: '100%',
    padding: '0.45rem',
    backgroundColor: '#2563eb',
    color: '#ffffff',
    border: 'none',
    fontWeight: 700,
    fontSize: '0.68rem',
    letterSpacing: '0.04em',
    cursor: 'pointer',
    marginTop: '0.35rem',
    textAlign: 'center' as const,
  },
  progressPanel: {
    position: 'absolute',
    top: '55px',
    right: '15px',
    width: '320px',
    backgroundColor: 'rgba(15, 23, 42, 0.95)',
    border: '1px solid #3b82f6',
    borderRadius: '4px',
    padding: '0.65rem 0.85rem',
    boxShadow: '0 8px 24px rgba(0,0,0,0.3)',
    zIndex: 1100,
    color: '#f8fafc',
    fontSize: '0.72rem',
  },
  progressHeader: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: '0.35rem',
  },
  progressTitle: {
    fontWeight: 700,
    fontSize: '0.72rem',
    color: '#60a5fa',
    letterSpacing: '0.04em',
  },
  progressDismissBtn: {
    background: 'none',
    border: 'none',
    color: '#94a3b8',
    cursor: 'pointer',
    fontSize: '0.8rem',
  },
  progressStageRow: {
    fontSize: '0.74rem',
    marginBottom: '0.2rem',
    color: '#f8fafc',
  },
  progressDetail: {
    color: '#cbd5e1',
    fontSize: '0.68rem',
    marginBottom: '0.45rem',
    lineHeight: 1.3,
  },
  progressBarContainer: {
    width: '100%',
    height: '6px',
    backgroundColor: '#334155',
    borderRadius: '3px',
    overflow: 'hidden',
  },
  progressBarFill: {
    height: '100%',
    transition: 'width 0.3s ease-in-out',
  },
  pillTagFailed: {
    fontWeight: 700,
    color: '#b91c1c',
    backgroundColor: '#fee2e2',
    padding: '0.04rem 0.22rem',
  },
  pillTagProcessing: {
    fontWeight: 700,
    color: '#1d4ed8',
    backgroundColor: '#dbeafe',
    padding: '0.04rem 0.22rem',
  },
  subLabel: {
    fontSize: '0.62rem',
    fontWeight: 700,
    letterSpacing: '0.04em',
    color: 'var(--color-text-secondary)',
    textTransform: 'uppercase' as const,
  },
  helpTextSmall: {
    fontSize: '0.68rem',
    color: 'var(--color-text-secondary)',
    lineHeight: 1.35,
  },
  textInput: {
    flex: 1,
    padding: '0.38rem 0.5rem',
    border: '1px solid var(--border-color)',
    backgroundColor: '#fff',
    fontSize: '0.74rem',
    borderRadius: '2px',
  },
  actionBtnSmall: {
    padding: '0.38rem 0.65rem',
    backgroundColor: 'var(--color-primary)',
    color: '#fff',
    border: 'none',
    fontWeight: 700,
    fontSize: '0.66rem',
    cursor: 'pointer',
    letterSpacing: '0.03em',
  },
  radiusPill: {
    fontFamily: 'var(--font-mono)',
    fontWeight: 700,
    fontSize: '0.66rem',
    color: '#0284c7',
  },
  radiusButtonGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(6, 1fr)',
    gap: '0.25rem',
    marginTop: '0.25rem',
  },
  radiusChoiceBtn: {
    padding: '0.3rem 0',
    backgroundColor: 'var(--color-surface-subtle)',
    border: '1px solid var(--border-color)',
    color: 'var(--color-text-secondary)',
    fontSize: '0.64rem',
    fontWeight: 600,
    cursor: 'pointer',
    textAlign: 'center' as const,
  },
  radiusChoiceBtnActive: {
    backgroundColor: '#0284c7',
    borderColor: '#0284c7',
    color: '#ffffff',
    fontWeight: 700,
  },
  searchAreaMainBtn: {
    marginTop: '0.45rem',
    width: '100%',
    padding: '0.52rem',
    backgroundColor: '#0284c7',
    color: '#ffffff',
    border: 'none',
    fontWeight: 700,
    fontSize: '0.7rem',
    letterSpacing: '0.04em',
    cursor: 'pointer',
    textAlign: 'center' as const,
  },
  discoverySuccessNote: {
    marginTop: '0.35rem',
    padding: '0.4rem 0.5rem',
    backgroundColor: '#ecfdf5',
    border: '1px solid #6ee7b7',
    color: '#065f46',
    fontSize: '0.68rem',
    lineHeight: 1.35,
  },
  areaInfoBox: {
    padding: '0.35rem 0.5rem',
    backgroundColor: 'var(--color-surface-subtle)',
    border: '1px solid var(--border-color)',
    fontSize: '0.66rem',
    color: 'var(--color-text-secondary)',
    display: 'flex',
    justifyContent: 'space-between',
  },
  discoveredScrollList: {
    display: 'flex',
    flexDirection: 'column',
    gap: '0.4rem',
    maxHeight: '340px',
    overflowY: 'auto' as const,
    marginTop: '0.2rem',
  },
  emptyResultsText: {
    padding: '0.75rem',
    fontSize: '0.72rem',
    color: 'var(--color-text-muted)',
    textAlign: 'center' as const,
    fontStyle: 'italic',
  },
  discoveredCard: {
    padding: '0.45rem',
    backgroundColor: '#ffffff',
    border: '1px solid var(--border-color)',
    display: 'flex',
    flexDirection: 'column',
    gap: '0.25rem',
    cursor: 'pointer',
    transition: 'border-color 0.15s',
  },
  discoveredCardSelected: {
    borderColor: '#0284c7',
    backgroundColor: '#f0f9ff',
  },
  wbCardTitleRow: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    gap: '0.4rem',
  },
  wbCardTitle: {
    fontSize: '0.72rem',
    fontWeight: 700,
    color: '#0f172a',
    lineHeight: 1.25,
  },
  wbCardTypeBadge: {
    fontSize: '0.58rem',
    fontWeight: 600,
    backgroundColor: '#e0f2fe',
    color: '#0369a1',
    padding: '0.08rem 0.3rem',
    textTransform: 'uppercase' as const,
    whiteSpace: 'nowrap' as const,
    flexShrink: 0,
  },
  wbCardMetaRow: {
    display: 'flex',
    justifyContent: 'space-between',
    fontSize: '0.64rem',
    color: 'var(--color-text-secondary)',
  },
  wbCardActionRow: {
    display: 'flex',
    justifyContent: 'flex-end',
    marginTop: '0.15rem',
  },
  addWbBtn: {
    padding: '0.28rem 0.55rem',
    backgroundColor: '#0284c7',
    color: '#ffffff',
    border: 'none',
    fontWeight: 700,
    fontSize: '0.64rem',
    cursor: 'pointer',
    letterSpacing: '0.02em',
  },
  badgeAlreadyAdded: {
    fontSize: '0.62rem',
    fontWeight: 700,
    color: '#15803d',
    backgroundColor: '#dcfce7',
    padding: '0.12rem 0.4rem',
  },
  clearBtn: {
    background: 'none',
    border: 'none',
    color: '#94a3b8',
    cursor: 'pointer',
    fontSize: '0.64rem',
    textDecoration: 'underline',
  },
  openDiscoveryBtn: {
    marginTop: '0.5rem',
    width: '100%',
    padding: '0.45rem',
    backgroundColor: '#0284c7',
    color: '#ffffff',
    border: 'none',
    fontWeight: 700,
    fontSize: '0.68rem',
    cursor: 'pointer',
    letterSpacing: '0.03em',
  },
  topDiscoveryBtn: {
    background: 'none',
    border: '1px solid #0284c7',
    color: '#0284c7',
    borderRadius: '3px',
    padding: '0.15rem 0.5rem',
    fontSize: '0.65rem',
    fontWeight: 700,
    cursor: 'pointer',
    letterSpacing: '0.03em',
  },
  topDiscoveryBtnActive: {
    backgroundColor: '#0284c7',
    border: '1px solid #0284c7',
    color: '#ffffff',
    borderRadius: '3px',
    padding: '0.15rem 0.5rem',
    fontSize: '0.65rem',
    fontWeight: 700,
    cursor: 'pointer',
    letterSpacing: '0.03em',
  },
  topVisualDataBtn: {
    backgroundColor: '#0284c7',
    border: '1px solid #0284c7',
    color: '#ffffff',
    borderRadius: '3px',
    padding: '0.15rem 0.55rem',
    fontSize: '0.65rem',
    fontWeight: 700,
    cursor: 'pointer',
    letterSpacing: '0.03em',
  },
  topAnalysisBtn: {
    backgroundColor: 'transparent',
    border: '1px solid #059669',
    color: '#059669',
    borderRadius: '3px',
    padding: '0.15rem 0.55rem',
    fontSize: '0.65rem',
    fontWeight: 700,
    cursor: 'pointer',
    letterSpacing: '0.03em',
  },
  wbActionGroup: {
    display: 'flex',
    flexDirection: 'column',
    gap: '0.4rem',
    marginTop: '0.6rem',
  },
  fetchVisualDataBtn: {
    backgroundColor: '#0284c7',
    color: '#ffffff',
    border: 'none',
    borderRadius: '3px',
    padding: '0.55rem 0.75rem',
    fontSize: '0.72rem',
    fontWeight: 700,
    letterSpacing: '0.04em',
    cursor: 'pointer',
    textAlign: 'center',
    transition: 'background-color 0.15s ease',
  },
  openAnalysisBtn: {
    backgroundColor: 'var(--color-surface)',
    color: '#059669',
    border: '1px solid #059669',
    borderRadius: '3px',
    padding: '0.45rem 0.75rem',
    fontSize: '0.7rem',
    fontWeight: 700,
    cursor: 'pointer',
    textAlign: 'center',
    transition: 'all 0.15s ease',
  },
  badgeDiscoveryActive: {
    fontFamily: 'var(--font-mono)',
    fontWeight: 700,
    fontSize: '0.65rem',
    color: '#0891b2',
    backgroundColor: '#cffafe',
    padding: '0.1rem 0.35rem',
    border: '1px solid #a5f3fc',
  },
  selectionSummaryBar: {
    marginTop: '0.35rem',
    padding: '0.45rem 0.5rem',
    backgroundColor: '#eff6ff',
    border: '1px solid #bfdbfe',
    borderRadius: '2px',
    display: 'flex',
    flexDirection: 'column' as const,
    gap: '0.35rem',
  },
  selectionCountLabel: {
    fontSize: '0.68rem',
    color: '#1e40af',
    letterSpacing: '0.02em',
  },
  selectionBarActions: {
    display: 'flex',
    gap: '0.35rem',
  },
  batchImportBtn: {
    flex: 1,
    padding: '0.4rem',
    backgroundColor: '#1d4ed8',
    color: '#ffffff',
    border: 'none',
    fontWeight: 700,
    fontSize: '0.66rem',
    letterSpacing: '0.03em',
    cursor: 'pointer',
    textAlign: 'center' as const,
  },
  clearSelectionBtn: {
    padding: '0.4rem 0.6rem',
    backgroundColor: '#e2e8f0',
    color: '#334155',
    border: 'none',
    fontWeight: 600,
    fontSize: '0.64rem',
    cursor: 'pointer',
  },
  quickActionRow: {
    display: 'flex',
    gap: '0.4rem',
    marginTop: '0.3rem',
    marginBottom: '0.1rem',
  },
  quickActionBtn: {
    padding: '0.2rem 0.45rem',
    backgroundColor: 'var(--color-surface-subtle)',
    border: '1px solid var(--border-color)',
    color: 'var(--color-text-secondary)',
    fontSize: '0.62rem',
    fontWeight: 600,
    cursor: 'pointer',
  },
  selectToggleBtn: {
    padding: '0.24rem 0.5rem',
    backgroundColor: '#f1f5f9',
    color: '#334155',
    border: '1px solid #cbd5e1',
    fontWeight: 600,
    fontSize: '0.62rem',
    cursor: 'pointer',
  },
  selectToggleBtnActive: {
    padding: '0.24rem 0.5rem',
    backgroundColor: '#dbeafe',
    color: '#1d4ed8',
    border: '1px solid #3b82f6',
    fontWeight: 700,
    fontSize: '0.62rem',
    cursor: 'pointer',
  },
  discoveredCardImportSelected: {
    borderColor: '#2563eb',
    backgroundColor: '#eff6ff',
  },
};
