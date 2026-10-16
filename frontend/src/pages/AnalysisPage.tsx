import React, { useEffect, useState, useCallback, useMemo } from 'react';
import {
  getWaterBodiesGeoJson,
  getWaterBodyTemporalAnalysis,
  resolveApiUrl,
  TemporalAnalysisResponse,
  ObservationTimelineItem,
  WaterBody,
  checkBandAvailability,
  analyzeSpectralIndicator,
  getSpectralPreviewImageUrl,
  getSpectralSummary,
  calculateTimeSeriesSpectral,
  SpectralIndicatorId,
  SpectralAnalysisResult,
  BandAvailabilityInfo,
  TimeSeriesSpectralResponse,
  getAIStatus,
  askAIAnalysis,
  AIStatusResponse,
  AIAnalysisResponse,
} from '../api/client';
import { FetchVisualDataModal } from '../components/FetchVisualDataModal';

interface AnalysisPageProps {
  initialWaterBodyId?: string;
  onNavigateToMap?: (waterBodyId?: string) => void;
}

export type VisualFilterType =
  | 'natural'
  | 'water_emphasis'
  | 'contrast'
  | 'false_color'
  | 'nir'
  | 'swir';

// ─── Water Body Boundary SVG Overlay Component ──────────────────────────────
interface BoundaryOverlayProps {
  aoiBoundsStr?: string | null;
  aoiGeoJsonStr?: string | null;
}

const WaterBodyBoundaryOverlay: React.FC<BoundaryOverlayProps> = ({
  aoiBoundsStr,
  aoiGeoJsonStr,
}) => {
  if (!aoiBoundsStr && !aoiGeoJsonStr) return null;

  try {
    let bounds: [number, number, number, number] | null = null;
    if (aoiBoundsStr) {
      bounds = typeof aoiBoundsStr === 'string' ? JSON.parse(aoiBoundsStr) : aoiBoundsStr;
    }

    let polygonsCoords: Array<Array<[number, number]>> = [];
    if (aoiGeoJsonStr) {
      const raw = typeof aoiGeoJsonStr === 'string' ? JSON.parse(aoiGeoJsonStr) : aoiGeoJsonStr;
      const geom = raw?.type === 'Feature' ? raw.geometry : raw;
      if (geom?.type === 'Polygon' && geom.coordinates?.[0]) {
        polygonsCoords.push(geom.coordinates[0]);
      } else if (geom?.type === 'MultiPolygon' && geom.coordinates) {
        geom.coordinates.forEach((poly: any) => {
          if (poly && poly[0]) polygonsCoords.push(poly[0]);
        });
      }
    }

    // Fallback bounding box polygon if GeoJSON coordinates are missing
    if (polygonsCoords.length === 0 && bounds && Array.isArray(bounds) && bounds.length === 4) {
      const [w, s, e, n] = bounds;
      polygonsCoords.push([
        [w, s],
        [e, s],
        [e, n],
        [w, n],
        [w, s],
      ]);
    }

    if (polygonsCoords.length === 0 || !bounds || bounds.length !== 4) return null;

    const [minLon, minLat, maxLon, maxLat] = bounds;
    const lonSpan = maxLon - minLon;
    const latSpan = maxLat - minLat;
    if (lonSpan <= 0 || latSpan <= 0) return null;

    return (
      <>
        <svg
          viewBox="0 0 100 100"
          preserveAspectRatio="none"
          style={{
            position: 'absolute',
            top: 0,
            left: 0,
            width: '100%',
            height: '100%',
            pointerEvents: 'none',
            zIndex: 6,
          }}
        >
          {polygonsCoords.map((ring, idx) => {
            const pointsStr = ring
              .map(([lon, lat]) => {
                const x = Math.min(100, Math.max(0, ((lon - minLon) / lonSpan) * 100));
                const y = Math.min(100, Math.max(0, ((maxLat - lat) / latSpan) * 100));
                return `${x.toFixed(2)},${y.toFixed(2)}`;
              })
              .join(' ');

            return (
              <React.Fragment key={idx}>
                {/* Outer dark stroke for maximum contrast over bright terrain/clouds */}
                <polygon
                  points={pointsStr}
                  fill="none"
                  stroke="#0f172a"
                  strokeWidth="3.2"
                  strokeLinejoin="round"
                  strokeLinecap="round"
                />
                {/* Inner neon cyan dashed stroke with transparent cyan tint */}
                <polygon
                  points={pointsStr}
                  fill="rgba(6, 182, 212, 0.16)"
                  stroke="#00f0ff"
                  strokeWidth="1.6"
                  strokeDasharray="3.5 1.8"
                  strokeLinejoin="round"
                  strokeLinecap="round"
                />
              </React.Fragment>
            );
          })}
        </svg>

        {/* Legend Pill Badge */}
        <div
          style={{
            position: 'absolute',
            bottom: '8px',
            left: '8px',
            backgroundColor: 'rgba(15, 23, 42, 0.88)',
            border: '1px solid #00f0ff',
            borderRadius: '3px',
            padding: '2px 7px',
            fontSize: '0.62rem',
            fontWeight: 800,
            color: '#00f0ff',
            display: 'flex',
            alignItems: 'center',
            gap: '4px',
            pointerEvents: 'none',
            zIndex: 10,
            letterSpacing: '0.04em',
            boxShadow: '0 2px 6px rgba(0,0,0,0.4)',
          }}
        >
          <span style={{ fontSize: '0.75rem', lineHeight: 1 }}>━━</span> Water Body Boundary
        </div>
      </>
    );
  } catch (err) {
    return null;
  }
};

// ─── Spectral Indicator Metadata & Definitions ──────────────────────────────
export interface IndicatorMeta {
  id: SpectralIndicatorId;
  name: string;
  badge: string;
  formula: string;
  requiredBands: string;
  description: string;
  disclaimer: string;
}

export const INDICATORS_METADATA: Record<SpectralIndicatorId, IndicatorMeta> = {
  ndti: {
    id: 'ndti',
    name: 'Turbidity / Suspended Sediment',
    badge: 'NDTI',
    formula: '(B04 - B03) / (B04 + B03)',
    requiredBands: 'Red (B04), Green (B03)',
    description:
      'Normalized Difference Turbidity Index proxy evaluating relative suspended particulate matter and turbidity. Higher values indicate higher sediment scattering.',
    disclaimer:
      'Remote-sensing optical proxy; does not measure in-situ NTU (Nephelometric Turbidity Units) or calibrate depth-integrated sediment concentration.',
  },
  ndci: {
    id: 'ndci',
    name: 'Chlorophyll-a Proxy',
    badge: 'NDCI',
    formula: '(B05 - B04) / (B05 + B04)',
    requiredBands: 'RedEdge 1 (B05), Red (B04)',
    description:
      'Normalized Difference Chlorophyll Index proxy estimating relative photosynthetic pigment absorption using Sentinel-2 red-edge reflectance.',
    disclaimer:
      'Surface optical proxy; does not substitute for laboratory HPLC pigment extraction (mg/m³ or µg/L) or confirm phytoplankton species composition.',
  },
  fai: {
    id: 'fai',
    name: 'Algal Activity Proxy',
    badge: 'FAI',
    formula: 'B05 - [B04 + (B08 - B04) × 0.226]',
    requiredBands: 'RedEdge 1 (B05), Red (B04), NIR (B08)',
    description:
      'Floating Algae Index proxy detecting surface floating vegetation scums, algal mats, and emergent macrophytes.',
    disclaimer:
      'Surface reflectance proxy; does not confirm toxic cyanobacteria or algal blooms and cannot distinguish submerged from surface vegetation.',
  },
  anomaly: {
    id: 'anomaly',
    name: 'Surface Spectral Anomaly',
    badge: 'ANOMALY',
    formula: 'Z = (Current - Baseline_Mean) / Baseline_StdDev',
    requiredBands: 'Requires ≥ 3 historical observations',
    description:
      'Statistical z-score anomaly evaluating current spectral behavior against the historical baseline of this specific water body.',
    disclaimer:
      'Identifies unusual spectral deviation from baseline reflectance. It does not by itself identify pollution source, chemical substance, or ecological hazard.',
  },
};

const getLevelBadgeStyle = (classification: string): React.CSSProperties => {
  const c = (classification || '').toUpperCase();
  if (c.includes('LOW') || c === 'NORMAL') {
    return {
      backgroundColor: '#ecfdf5',
      color: '#047857',
      border: '1px solid #a7f3d0',
      padding: '0.2rem 0.55rem',
      borderRadius: '3px',
      fontSize: '0.68rem',
      fontWeight: 800,
      letterSpacing: '0.04em',
    };
  }
  if (c.includes('MODERATE') || c === 'WATCH') {
    return {
      backgroundColor: '#fffbeb',
      color: '#b45309',
      border: '1px solid #fde68a',
      padding: '0.2rem 0.55rem',
      borderRadius: '3px',
      fontSize: '0.68rem',
      fontWeight: 800,
      letterSpacing: '0.04em',
    };
  }
  if (c.includes('HIGH') || c.includes('ANOMALY')) {
    return {
      backgroundColor: '#fef2f2',
      color: '#b91c1c',
      border: '1px solid #fecaca',
      padding: '0.2rem 0.55rem',
      borderRadius: '3px',
      fontSize: '0.68rem',
      fontWeight: 800,
      letterSpacing: '0.04em',
    };
  }
  return {
    backgroundColor: '#f1f5f9',
    color: '#475569',
    border: '1px solid #cbd5e1',
    padding: '0.2rem 0.55rem',
    borderRadius: '3px',
    fontSize: '0.68rem',
    fontWeight: 700,
  };
};

const getQualityBadgeStyle = (quality: string): React.CSSProperties => {
  const q = (quality || '').toUpperCase();
  if (q === 'GOOD') {
    return {
      backgroundColor: '#ecfdf5',
      color: '#065f46',
      border: '1px solid #6ee7b7',
      padding: '0.15rem 0.45rem',
      borderRadius: '3px',
      fontSize: '0.62rem',
      fontWeight: 700,
    };
  }
  if (q === 'LIMITED') {
    return {
      backgroundColor: '#fffbeb',
      color: '#92400e',
      border: '1px solid #fcd34d',
      padding: '0.15rem 0.45rem',
      borderRadius: '3px',
      fontSize: '0.62rem',
      fontWeight: 700,
    };
  }
  return {
    backgroundColor: '#fef2f2',
    color: '#991b1b',
    border: '1px solid #fca5a5',
    padding: '0.15rem 0.45rem',
    borderRadius: '3px',
    fontSize: '0.62rem',
    fontWeight: 700,
  };
};

export const AnalysisPage: React.FC<AnalysisPageProps> = ({
  initialWaterBodyId,
  onNavigateToMap,
}) => {
  const [waterBodies, setWaterBodies] = useState<WaterBody[]>([]);
  const [selectedWaterBodyId, setSelectedWaterBodyId] = useState<string>(
    initialWaterBodyId || localStorage.getItem('jalnetra_selected_wb_id') || ''
  );
  const [analysisData, setAnalysisData] = useState<TemporalAnalysisResponse | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  // Visual Analysis Filters
  const [visualFilter, setVisualFilter] = useState<VisualFilterType>('natural');

  // Boundary Overlay
  const [showBoundary, setShowBoundary] = useState<boolean>(false);

  // Slideshow State
  const [slideshowIdx, setSlideshowIdx] = useState<number>(0);
  const [isPlaying, setIsPlaying] = useState<boolean>(false);
  const [isLooping, setIsLooping] = useState<boolean>(true);

  // Comparison State
  const [compareId1, setCompareId1] = useState<string>('');
  const [compareId2, setCompareId2] = useState<string>('');
  const [comparisonMode, setComparisonMode] = useState<'side-by-side' | 'slider'>('side-by-side');
  const [sliderPos, setSliderPos] = useState<number>(50); // percentage 0-100

  // Expanded Image Modal
  const [expandedImage, setExpandedImage] = useState<ObservationTimelineItem | null>(null);

  // Fetch Visual Data Modal
  const [isFetchModalOpen, setIsFetchModalOpen] = useState<boolean>(false);

  // Spectral Analysis State
  const [spectralObsId, setSpectralObsId] = useState<string>('');
  const [spectralResults, setSpectralResults] = useState<Record<string, SpectralAnalysisResult | null>>({});
  const [isAnalyzing, setIsAnalyzing] = useState<Record<string, boolean>>({});
  const [spectralError, setSpectralError] = useState<Record<string, string | null>>({});
  const [bandAvailability, setBandAvailability] = useState<Record<string, BandAvailabilityInfo | null>>({});
  const [isCheckingBands, setIsCheckingBands] = useState<boolean>(false);
  const [previewModalResult, setPreviewModalResult] = useState<SpectralAnalysisResult | null>(null);
  const [infoModalIndicator, setInfoModalIndicator] = useState<string | null>(null);
  const [timeSeriesIndicator, setTimeSeriesIndicator] = useState<SpectralIndicatorId>('ndti');
  const [isComputingTimeSeries, setIsComputingTimeSeries] = useState<boolean>(false);
  const [timeSeriesResult, setTimeSeriesResult] = useState<TimeSeriesSpectralResponse | null>(null);
  const [timeSeriesProgress, setTimeSeriesProgress] = useState<number>(0);

  // AI Assistant State
  const [aiStatus, setAiStatus] = useState<AIStatusResponse | null>(null);
  const [aiQuestion, setAiQuestion] = useState<string>('');
  const [aiResponse, setAiResponse] = useState<AIAnalysisResponse | null>(null);
  const [isAiLoading, setIsAiLoading] = useState<boolean>(false);
  const [aiError, setAiError] = useState<string | null>(null);

  // Fetch AI status on mount
  useEffect(() => {
    let active = true;
    getAIStatus()
      .then(st => {
        if (active) setAiStatus(st);
      })
      .catch(() => {
        if (active) setAiStatus({ enabled: false, configured: false, model: 'gpt-4o-mini', provider: 'openai' });
      });
    return () => {
      active = false;
    };
  }, []);

  // Isolate AI response per water body (Section 37)
  useEffect(() => {
    setAiResponse(null);
    setAiError(null);
    setAiQuestion('');
  }, [selectedWaterBodyId]);

  const handleAskAi = async (questionText: string) => {
    if (!questionText.trim() || !selectedWaterBodyId) return;
    setIsAiLoading(true);
    setAiError(null);
    try {
      const res = await askAIAnalysis({
        water_body_id: selectedWaterBodyId,
        observation_id: spectralObsId || undefined,
        question: questionText.trim(),
      });
      setAiResponse(res);
    } catch (err: unknown) {
      const msg =
        err instanceof Error
          ? err.message
          : 'AI service is currently unavailable. Your satellite analysis data is still available.';
      setAiError(msg);
    } finally {
      setIsAiLoading(false);
    }
  };

  // Load registered water bodies
  useEffect(() => {
    let active = true;
    getWaterBodiesGeoJson()
      .then(geoJson => {
        if (!active) return;
        const wbs: WaterBody[] = (geoJson.features || []).map((f: any) => ({
          id: f.properties.id,
          name: f.properties.name,
          normalized_name: f.properties.normalized_name || f.properties.name.toLowerCase(),
          country: f.properties.country,
          source: f.properties.source,
          water_body_type: f.properties.water_body_type,
          area_sq_km: f.properties.area_sq_km,
          centroid_lat: f.properties.centroid_lat,
          centroid_lon: f.properties.centroid_lon,
          min_lat: f.properties.min_lat,
          min_lon: f.properties.min_lon,
          max_lat: f.properties.max_lat,
          max_lon: f.properties.max_lon,
        }));
        setWaterBodies(wbs);
        if (!selectedWaterBodyId && wbs.length > 0) {
          setSelectedWaterBodyId(wbs[0].id);
        }
      })
      .catch(err => {
        console.error('Failed to load water bodies:', err);
      });
    return () => {
      active = false;
    };
  }, []);

  // Load temporal analysis data when water body changes
  const loadAnalysis = useCallback(async (wbId: string) => {
    if (!wbId) return;
    setIsLoading(true);
    setError(null);
    try {
      const data = await getWaterBodyTemporalAnalysis(wbId);
      setAnalysisData(data);
      if (data.timeline.length > 0) {
        setCompareId1(data.timeline[0].id);
        setCompareId2(data.timeline[data.timeline.length - 1].id);
      } else {
        setCompareId1('');
        setCompareId2('');
      }
    } catch (err: any) {
      console.error('Failed to load temporal analysis:', err);
      setError(err.message || 'Failed to load analysis for water body');
      setAnalysisData(null);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (selectedWaterBodyId) {
      localStorage.setItem('jalnetra_selected_wb_id', selectedWaterBodyId);
      loadAnalysis(selectedWaterBodyId);
      setSlideshowIdx(0);
      setIsPlaying(false);
    }
  }, [selectedWaterBodyId, loadAnalysis]);

  const selectedWaterBody = useMemo(() => {
    return waterBodies.find(wb => wb.id === selectedWaterBodyId);
  }, [waterBodies, selectedWaterBodyId]);

  const obs1 = useMemo(() => {
    return analysisData?.timeline.find(t => t.id === compareId1);
  }, [analysisData, compareId1]);

  const obs2 = useMemo(() => {
    return analysisData?.timeline.find(t => t.id === compareId2);
  }, [analysisData, compareId2]);

  // Overall net change
  const netChange = useMemo(() => {
    if (!analysisData?.timeline || analysisData.timeline.length < 2) return null;
    const first = analysisData.timeline[0].water_extent_sq_km;
    const last = analysisData.timeline[analysisData.timeline.length - 1].water_extent_sq_km;
    if (first == null || last == null) return null;
    return last - first;
  }, [analysisData]);

  // Image filter URL resolver
  const getFilteredUrl = useCallback(
    (baseUrl: string) => {
      if (!baseUrl) return '';
      const resolved = resolveApiUrl(baseUrl);
      if (visualFilter === 'natural') return resolved;
      const sep = resolved.includes('?') ? '&' : '?';
      return `${resolved}${sep}filter=${visualFilter}`;
    },
    [visualFilter]
  );

  // Slideshow auto-advance effect (1.8s)
  useEffect(() => {
    if (!isPlaying || !analysisData?.timeline || analysisData.timeline.length === 0) return;
    const timer = setInterval(() => {
      setSlideshowIdx(prev => {
        if (prev < analysisData.timeline.length - 1) {
          return prev + 1;
        }
        if (isLooping) return 0;
        setIsPlaying(false);
        return prev;
      });
    }, 1800);
    return () => clearInterval(timer);
  }, [isPlaying, isLooping, analysisData]);

  // Set default spectral observation to latest when timeline loads
  useEffect(() => {
    if (analysisData?.timeline && analysisData.timeline.length > 0) {
      const latestObs = analysisData.timeline[analysisData.timeline.length - 1];
      setSpectralObsId(prev => {
        if (!prev || !analysisData.timeline.some(t => t.id === prev)) {
          return latestObs.id;
        }
        return prev;
      });
    } else {
      setSpectralObsId('');
      setSpectralResults({});
      setBandAvailability({});
    }
  }, [analysisData]);

  // Load spectral indicators summary and check bands when spectral observation changes
  useEffect(() => {
    if (!selectedWaterBodyId || !spectralObsId) {
      setSpectralResults({});
      setBandAvailability({});
      return;
    }

    let active = true;

    // Load cached summary
    getSpectralSummary(selectedWaterBodyId, spectralObsId)
      .then(summary => {
        if (!active) return;
        if (summary && summary.indicators) {
          setSpectralResults(summary.indicators);
        }
      })
      .catch(() => {
        if (active) setSpectralResults({});
      });

    // Check band availability
    setIsCheckingBands(true);
    const indicators: SpectralIndicatorId[] = ['ndti', 'ndci', 'fai', 'anomaly'];
    Promise.all(
      indicators.map(ind =>
        checkBandAvailability(selectedWaterBodyId, spectralObsId, ind)
          .then(info => ({ ind, info }))
          .catch(() => ({ ind, info: null }))
      )
    ).then(results => {
      if (!active) return;
      const merged: Record<string, BandAvailabilityInfo | null> = {};
      results.forEach(r => {
        merged[r.ind] = r.info;
      });
      setBandAvailability(merged);
      setIsCheckingBands(false);
    });

    return () => {
      active = false;
    };
  }, [selectedWaterBodyId, spectralObsId]);

  const selectedSpectralObs = useMemo(() => {
    return analysisData?.timeline.find(t => t.id === spectralObsId);
  }, [analysisData, spectralObsId]);

  const handleCalculateIndicator = useCallback(
    async (indicator: SpectralIndicatorId, forceRecompute: boolean = false) => {
      if (!selectedWaterBodyId || !spectralObsId) return;

      setIsAnalyzing(prev => ({ ...prev, [indicator]: true }));
      setSpectralError(prev => ({ ...prev, [indicator]: null }));

      try {
        const res = await analyzeSpectralIndicator(selectedWaterBodyId, {
          observation_id: spectralObsId,
          indicator,
          force_recompute: forceRecompute,
        });
        setSpectralResults(prev => ({ ...prev, [indicator]: res }));
      } catch (err: any) {
        console.error(`Failed to analyze ${indicator}:`, err);
        setSpectralError(prev => ({
          ...prev,
          [indicator]: err?.message || `Failed to calculate ${indicator.toUpperCase()}`,
        }));
      } finally {
        setIsAnalyzing(prev => ({ ...prev, [indicator]: false }));
      }
    },
    [selectedWaterBodyId, spectralObsId]
  );

  const handleCalculateAllForObs = useCallback(async () => {
    if (!selectedWaterBodyId || !spectralObsId) return;
    const indicators: SpectralIndicatorId[] = ['ndti', 'ndci', 'fai', 'anomaly'];
    await Promise.all(indicators.map(ind => handleCalculateIndicator(ind, false)));
  }, [selectedWaterBodyId, spectralObsId, handleCalculateIndicator]);

  const handleRunTimeSeries = useCallback(async () => {
    if (!selectedWaterBodyId || !analysisData?.timeline || analysisData.timeline.length === 0) return;

    setIsComputingTimeSeries(true);
    setTimeSeriesProgress(15);
    setTimeSeriesResult(null);

    const obsIds = analysisData.timeline.map(t => t.id);

    try {
      setTimeSeriesProgress(45);
      const res = await calculateTimeSeriesSpectral(selectedWaterBodyId, {
        observation_ids: obsIds,
        indicator: timeSeriesIndicator,
        force_recompute: false,
      });
      setTimeSeriesProgress(100);
      setTimeSeriesResult(res);
    } catch (err: any) {
      console.error('Time series spectral calculation failed:', err);
      alert(`Time series calculation failed: ${err.message || 'Unknown error'}`);
    } finally {
      setIsComputingTimeSeries(false);
    }
  }, [selectedWaterBodyId, analysisData, timeSeriesIndicator]);

  return (
    <div style={styles.container}>
      {/* ── Top Header Bar ──────────────────────────────────────────────── */}
      <div style={styles.topBar}>
        <div style={styles.topBarLeft}>
          <div style={styles.kicker}>WATER BODY TIME-SERIES MONITORING</div>
          <h2 style={styles.pageTitle}>Temporal Analysis Workstation</h2>
        </div>

        <div style={styles.topBarRight}>
          <div style={styles.selectorGroup}>
            <label style={styles.selectorLabel}>TARGET WATER BODY:</label>
            <select
              style={styles.wbSelect}
              value={selectedWaterBodyId}
              onChange={e => setSelectedWaterBodyId(e.target.value)}
              disabled={isLoading || waterBodies.length === 0}
            >
              {waterBodies.map(wb => (
                <option key={wb.id} value={wb.id}>
                  {wb.name} {wb.country ? `(${wb.country})` : ''}
                </option>
              ))}
            </select>
          </div>

          {selectedWaterBody && (
            <button
              style={styles.fetchBtn}
              onClick={() => setIsFetchModalOpen(true)}
            >
              + FETCH VISUAL DATA
            </button>
          )}

          {onNavigateToMap && (
            <button
              style={styles.mapNavBtn}
              onClick={() => onNavigateToMap(selectedWaterBodyId)}
            >
              🗺 OPEN MAP
            </button>
          )}
        </div>
      </div>

      {/* ── Main Content Area ───────────────────────────────────────────── */}
      <div style={styles.contentScroll}>
        {error && (
          <div style={styles.errorBanner}>
            <strong>Error:</strong> {error}
          </div>
        )}

        {/* Target Meta / Stats Banner */}
        {selectedWaterBody && (
          <div style={styles.metaBanner}>
            <div style={styles.statCell}>
              <span style={styles.statLabel}>WATER BODY</span>
              <span style={styles.statValuePrimary}>{selectedWaterBody.name}</span>
              <span style={styles.statSub}>
                {selectedWaterBody.water_body_type || 'lake'} • {selectedWaterBody.country || 'India'}
              </span>
            </div>
            <div style={styles.statCell}>
              <span style={styles.statLabel}>REGISTERED BASIN AREA</span>
              <span style={styles.statValue}>
                {selectedWaterBody.area_sq_km ? `${selectedWaterBody.area_sq_km.toFixed(2)} km²` : 'N/A'}
              </span>
              <span style={styles.statSub}>Official boundary benchmark</span>
            </div>
            <div style={styles.statCell}>
              <span style={styles.statLabel}>OBSERVATIONS</span>
              <span style={styles.statValue}>
                {analysisData ? analysisData.total_observations : 0}
              </span>
              <span style={styles.statSub}>Acquired satellite dates</span>
            </div>
            <div style={styles.statCell}>
              <span style={styles.statLabel}>MONITORING PERIOD</span>
              <span style={styles.statValue}>
                {analysisData?.from_date && analysisData?.to_date
                  ? `${analysisData.from_date} → ${analysisData.to_date}`
                  : 'No observations'}
              </span>
              <span style={styles.statSub}>
                {netChange !== null
                  ? `Net extent change: ${netChange >= 0 ? '+' : ''}${netChange.toFixed(2)} km²`
                  : 'Temporal coverage'}
              </span>
            </div>
          </div>
        )}

        {/* If no observations yet */}
        {!isLoading && analysisData && analysisData.total_observations === 0 && (
          <div style={styles.emptyCard}>
            <div style={styles.emptyIcon}>🛰</div>
            <h3 style={styles.emptyTitle}>No Satellite Observations Acquired Yet</h3>
            <p style={styles.emptyDesc}>
              No visual satellite observations have been downloaded for &ldquo;{selectedWaterBody?.name}&rdquo;.
              Click <strong>&ldquo;Fetch Visual Data&rdquo;</strong> to discover and retrieve cloud-tolerant Sentinel-2 imagery distributed across any date range.
            </p>
            {selectedWaterBody && (
              <button
                style={styles.emptyActionBtn}
                onClick={() => setIsFetchModalOpen(true)}
              >
                + FETCH VISUAL DATA FOR {selectedWaterBody.name.toUpperCase()}
              </button>
            )}
          </div>
        )}

        {/* ── Analysis Controls Toolbar: Filters & Boundary Marking ──────── */}
        {analysisData && analysisData.timeline.length > 0 && (
          <div style={styles.toolbarBanner}>
            <div style={styles.toolbarLeft}>
              <div style={styles.toolbarItem}>
                <label style={styles.toolbarLabel}>VISUAL ANALYSIS FILTER:</label>
                <select
                  style={styles.toolbarSelect}
                  value={visualFilter}
                  onChange={e => setVisualFilter(e.target.value as VisualFilterType)}
                >
                  <option value="natural">Natural Color (True RGB: B04, B03, B02)</option>
                  <option value="water_emphasis">Water Emphasis (Enhanced Reflectance)</option>
                  <option value="contrast">Vegetation / Water Contrast</option>
                  <option value="false_color">False Color Vegetation (NIR/Red/Green)</option>
                  <option value="nir">NIR View (Near-Infrared B08)</option>
                  <option value="swir">SWIR View (Short-wave Infrared B11/B12)</option>
                </select>
              </div>

              <label style={styles.boundaryToggleLabel}>
                <input
                  type="checkbox"
                  checked={showBoundary}
                  onChange={e => setShowBoundary(e.target.checked)}
                  style={{ cursor: 'pointer', accentColor: '#0284c7' }}
                />
                <span style={{ fontWeight: 700, color: showBoundary ? '#0284c7' : '#475569' }}>
                  SHOW WATER-BODY BOUNDARY
                </span>
                {showBoundary && (
                  <span style={styles.boundaryPill}>ACTIVE</span>
                )}
              </label>
            </div>

            <div style={styles.toolbarRight}>
              <span style={{ fontSize: '0.68rem', color: '#64748b' }}>
                Active filter applied to Slideshow, Gallery, and Temporal Comparison
              </span>
            </div>
          </div>
        )}

        {/* ── Section 1: Temporal Change Slideshow (Oldest → Newest) ──────── */}
        {analysisData && analysisData.timeline.length > 0 && (
          <div style={styles.sectionCard}>
            <div style={styles.sectionHeader}>
              <div>
                <h3 style={styles.sectionTitle}>1. Temporal Change Slideshow</h3>
                <span style={styles.sectionSubtitle}>
                  Progressive sequence through observations ordered chronologically from oldest to newest
                </span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <span
                  style={{
                    fontSize: '0.68rem',
                    fontWeight: 800,
                    padding: '0.2rem 0.55rem',
                    borderRadius: '3px',
                    backgroundColor:
                      slideshowIdx === 0
                        ? '#ecfdf5'
                        : slideshowIdx === analysisData.timeline.length - 1
                        ? '#f5f3ff'
                        : '#eff6ff',
                    color:
                      slideshowIdx === 0
                        ? '#065f46'
                        : slideshowIdx === analysisData.timeline.length - 1
                        ? '#6b21a8'
                        : '#1e40af',
                    border: `1px solid ${
                      slideshowIdx === 0
                        ? '#a7f3d0'
                        : slideshowIdx === analysisData.timeline.length - 1
                        ? '#ddd6fe'
                        : '#bfdbfe'
                    }`,
                  }}
                >
                  {slideshowIdx === 0
                    ? 'EARLIEST OBSERVATION'
                    : slideshowIdx === analysisData.timeline.length - 1
                    ? 'LATEST OBSERVATION'
                    : 'INTERMEDIATE OBSERVATION'}
                </span>
              </div>
            </div>

            {(() => {
              const currentSlide = analysisData.timeline[slideshowIdx] || analysisData.timeline[0];
              return (
                <div style={styles.slideshowContainer}>
                  {/* Viewport */}
                  <div style={styles.slideshowViewport}>
                    <div style={{ position: 'relative', display: 'inline-block', maxWidth: '100%', maxHeight: '420px', lineHeight: 0 }}>
                      <img
                        src={getFilteredUrl(currentSlide.image_url)}
                        alt={currentSlide.sensing_date_str}
                        style={{
                          maxHeight: '420px',
                          maxWidth: '100%',
                          width: 'auto',
                          height: 'auto',
                          display: 'block',
                          objectFit: 'contain',
                        }}
                      />

                      {/* Vector Boundary Overlay */}
                      {showBoundary && (
                        <WaterBodyBoundaryOverlay
                          aoiBoundsStr={currentSlide.aoi_bounds}
                          aoiGeoJsonStr={currentSlide.aoi_geojson}
                        />
                      )}
                    </div>

                    {/* Top Left Overlay Badge */}
                    <div style={styles.slideshowBadgeTopLeft}>
                      <span>{currentSlide.sensing_date_str}</span>
                      <span style={{ opacity: 0.8 }}>
                        • #{slideshowIdx + 1} of {analysisData.timeline.length}
                      </span>
                    </div>

                    {/* Top Right Overlay Badge */}
                    <div style={styles.slideshowBadgeTopRight}>
                      {currentSlide.water_extent_sq_km != null && (
                        <span>Extent: {currentSlide.water_extent_sq_km.toFixed(2)} km²</span>
                      )}
                      <span>
                        Cloud: {currentSlide.cloud_cover_percent != null ? `${currentSlide.cloud_cover_percent.toFixed(1)}%` : '0%'}
                      </span>
                    </div>

                    {showBoundary && selectedWaterBody?.area_sq_km && (
                      <div style={styles.slideshowBoundaryPill}>
                        Basin Area: {selectedWaterBody.area_sq_km.toFixed(2)} km²
                      </div>
                    )}
                  </div>

                  {/* Scrubber & Controls */}
                  <div style={styles.slideshowControlsRow}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                      <button
                        style={styles.slideBtn}
                        onClick={() =>
                          setSlideshowIdx(prev =>
                            prev > 0 ? prev - 1 : isLooping ? analysisData.timeline.length - 1 : 0
                          )
                        }
                      >
                        ◀ PREVIOUS
                      </button>

                      <button
                        style={{
                          ...styles.slideBtn,
                          backgroundColor: isPlaying ? '#dc2626' : '#0284c7',
                          color: '#ffffff',
                          minWidth: '90px',
                        }}
                        onClick={() => setIsPlaying(!isPlaying)}
                      >
                        {isPlaying ? '⏸ PAUSE' : '▶ PLAY'}
                      </button>

                      <button
                        style={styles.slideBtn}
                        onClick={() =>
                          setSlideshowIdx(prev =>
                            prev < analysisData.timeline.length - 1 ? prev + 1 : isLooping ? 0 : prev
                          )
                        }
                      >
                        NEXT ▶
                      </button>
                    </div>

                    {/* Timeline Scrubber Slider */}
                    <div
                      style={{
                        flex: 1,
                        display: 'flex',
                        alignItems: 'center',
                        gap: '0.75rem',
                        minWidth: '180px',
                      }}
                    >
                      <input
                        type="range"
                        min="0"
                        max={analysisData.timeline.length - 1}
                        value={slideshowIdx}
                        onChange={e => setSlideshowIdx(Number(e.target.value))}
                        style={{ flex: 1, cursor: 'pointer' }}
                      />
                      <span
                        style={{
                          fontSize: '0.72rem',
                          fontWeight: 700,
                          color: '#475569',
                          minWidth: '55px',
                          textAlign: 'right',
                        }}
                      >
                        {slideshowIdx + 1} / {analysisData.timeline.length}
                      </span>
                    </div>

                    <label
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '0.35rem',
                        fontSize: '0.72rem',
                        color: '#475569',
                        cursor: 'pointer',
                      }}
                    >
                      <input
                        type="checkbox"
                        checked={isLooping}
                        onChange={e => setIsLooping(e.target.checked)}
                      />
                      <span>Loop</span>
                    </label>
                  </div>
                </div>
              );
            })()}
          </div>
        )}

        {/* ── Section 2: Chronological Observation History (Gallery) ──────── */}
        {analysisData && analysisData.timeline.length > 0 && (
          <div style={styles.sectionCard}>
            <div style={styles.sectionHeader}>
              <div>
                <h3 style={styles.sectionTitle}>2. Chronological Observation History</h3>
                <span style={styles.sectionSubtitle}>
                  {analysisData.total_observations} Sentinel-2 observations clipped to the target water-body AOI
                </span>
              </div>
            </div>

            <div style={styles.galleryGrid}>
              {analysisData.timeline.map((item, idx) => (
                <div
                  key={item.id}
                  style={styles.galleryCard}
                  onClick={() => setExpandedImage(item)}
                >
                  <div style={styles.thumbWrapper}>
                    <img
                      src={getFilteredUrl(item.image_url)}
                      alt={`${item.sensing_date_str}`}
                      style={styles.thumbImg}
                      loading="lazy"
                    />

                    {/* Vector Boundary Overlay */}
                    {showBoundary && (
                      <WaterBodyBoundaryOverlay
                        aoiBoundsStr={item.aoi_bounds}
                        aoiGeoJsonStr={item.aoi_geojson}
                      />
                    )}

                    <div style={styles.thumbDateBadge}>{item.sensing_date_str}</div>
                  </div>

                  <div style={styles.cardDetails}>
                    <div style={styles.cardDetailRow}>
                      <span>Quality:</span>
                      <span
                        style={{
                          fontSize: '0.62rem',
                          fontWeight: 700,
                          padding: '0.1rem 0.35rem',
                          borderRadius: '2px',
                          backgroundColor:
                            item.quality_label === 'VERY CLEAR'
                              ? '#ecfdf5'
                              : item.quality_label === 'CLEAR'
                              ? '#eff6ff'
                              : item.quality_label === 'ACCEPTABLE'
                              ? '#fffbeb'
                              : '#fef2f2',
                          color:
                            item.quality_label === 'VERY CLEAR'
                              ? '#065f46'
                              : item.quality_label === 'CLEAR'
                              ? '#1e40af'
                              : item.quality_label === 'ACCEPTABLE'
                              ? '#92400e'
                              : '#991b1b',
                        }}
                      >
                        {item.quality_label || 'CLEAR'}
                      </span>
                    </div>
                    <div style={styles.cardDetailRow}>
                      <span>Cloud Cover:</span>
                      <strong
                        style={{
                          color:
                            item.cloud_cover_percent != null && item.cloud_cover_percent > 30
                              ? '#d97706'
                              : '#059669',
                        }}
                      >
                        {item.cloud_cover_percent != null ? `${item.cloud_cover_percent.toFixed(1)}%` : '0%'}
                      </strong>
                    </div>
                    <div style={styles.cardDetailRow}>
                      <span>Surface Extent:</span>
                      {item.water_extent_sq_km != null ? (
                        <strong>
                          {item.water_extent_sq_km.toFixed(2)} km²
                          {item.is_demo_extent && (
                            <span style={{ fontSize: '0.62rem', color: '#64748b', fontWeight: 'normal', marginLeft: '3px' }}>
                              (est)
                            </span>
                          )}
                        </strong>
                      ) : (
                        <span style={{ color: '#64748b', fontSize: '0.68rem', fontStyle: 'italic' }}>
                          Visual
                        </span>
                      )}
                    </div>
                    {item.change_from_previous_sq_km != null && idx > 0 && (
                      <div style={styles.cardDetailRow}>
                        <span>Change:</span>
                        <strong
                          style={{
                            color: item.change_from_previous_sq_km >= 0 ? '#16a34a' : '#dc2626',
                          }}
                        >
                          {item.change_from_previous_sq_km >= 0 ? '↑ +' : '↓ '}
                          {item.change_from_previous_sq_km.toFixed(2)} km²
                        </strong>
                      </div>
                    )}
                    <div style={styles.cardFooter}>
                      <span>10m Sentinel-2</span>
                      <span style={{ color: '#0284c7', cursor: 'pointer' }}>Zoom 🔍</span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ── Section 3: Temporal Comparison Tool ────────────────────────── */}
        {analysisData && analysisData.timeline.length >= 2 && (
          <div style={styles.sectionCard}>
            <div style={styles.sectionHeader}>
              <div>
                <h3 style={styles.sectionTitle}>3. Temporal Comparison</h3>
                <span style={styles.sectionSubtitle}>
                  Compare two observation dates to observe water spread, shoreline changes, and visual variations
                </span>
              </div>
              <div style={styles.compareModeToggle}>
                <button
                  style={{
                    ...styles.modeToggleBtn,
                    ...(comparisonMode === 'side-by-side' ? styles.modeToggleBtnActive : {}),
                  }}
                  onClick={() => setComparisonMode('side-by-side')}
                >
                  Side-by-Side
                </button>
                <button
                  style={{
                    ...styles.modeToggleBtn,
                    ...(comparisonMode === 'slider' ? styles.modeToggleBtnActive : {}),
                  }}
                  onClick={() => setComparisonMode('slider')}
                >
                  Slider Overlay
                </button>
              </div>
            </div>

            {/* Date Selection Dropdowns */}
            <div style={styles.comparePickersRow}>
              <div style={styles.comparePickerBox}>
                <label style={styles.pickerLabel}>OBSERVATION A (BEFORE):</label>
                <select
                  style={styles.pickerSelect}
                  value={compareId1}
                  onChange={e => setCompareId1(e.target.value)}
                >
                  {analysisData.timeline.map(t => (
                    <option key={t.id} value={t.id}>
                      {t.sensing_date_str} {t.water_extent_sq_km ? `(${t.water_extent_sq_km.toFixed(2)} km²)` : ''}
                    </option>
                  ))}
                </select>
              </div>

              <div style={styles.vsBadge}>VS</div>

              <div style={styles.comparePickerBox}>
                <label style={styles.pickerLabel}>OBSERVATION B (AFTER):</label>
                <select
                  style={styles.pickerSelect}
                  value={compareId2}
                  onChange={e => setCompareId2(e.target.value)}
                >
                  {analysisData.timeline.map(t => (
                    <option key={t.id} value={t.id}>
                      {t.sensing_date_str} {t.water_extent_sq_km ? `(${t.water_extent_sq_km.toFixed(2)} km²)` : ''}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            {/* Comparison Views */}
            {obs1 && obs2 && (
              <>
                {comparisonMode === 'side-by-side' ? (
                  <div style={styles.sideBySideGrid}>
                    <div style={styles.compareViewport}>
                      <div style={styles.viewportHeader}>
                        <span>Date A: {obs1.sensing_date_str}</span>
                        {obs1.water_extent_sq_km != null ? (
                          <span>Extent: {obs1.water_extent_sq_km.toFixed(2)} km²</span>
                        ) : (
                          <span style={{ fontSize: '0.68rem', color: '#94a3b8' }}>Visual observation</span>
                        )}
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'center', backgroundColor: '#090d16' }}>
                        <div style={{ position: 'relative', display: 'inline-block', maxWidth: '100%', maxHeight: '380px', lineHeight: 0 }}>
                          <img
                            src={getFilteredUrl(obs1.image_url)}
                            alt={obs1.sensing_date_str}
                            style={{
                              maxHeight: '380px',
                              maxWidth: '100%',
                              width: 'auto',
                              height: 'auto',
                              display: 'block',
                              objectFit: 'contain',
                            }}
                          />
                          {showBoundary && (
                            <WaterBodyBoundaryOverlay
                              aoiBoundsStr={obs1.aoi_bounds}
                              aoiGeoJsonStr={obs1.aoi_geojson}
                            />
                          )}
                        </div>
                      </div>
                    </div>

                    <div style={styles.compareViewport}>
                      <div style={styles.viewportHeader}>
                        <span>Date B: {obs2.sensing_date_str}</span>
                        {obs2.water_extent_sq_km != null ? (
                          <span>Extent: {obs2.water_extent_sq_km.toFixed(2)} km²</span>
                        ) : (
                          <span style={{ fontSize: '0.68rem', color: '#94a3b8' }}>Visual observation</span>
                        )}
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'center', backgroundColor: '#090d16' }}>
                        <div style={{ position: 'relative', display: 'inline-block', maxWidth: '100%', maxHeight: '380px', lineHeight: 0 }}>
                          <img
                            src={getFilteredUrl(obs2.image_url)}
                            alt={obs2.sensing_date_str}
                            style={{
                              maxHeight: '380px',
                              maxWidth: '100%',
                              width: 'auto',
                              height: 'auto',
                              display: 'block',
                              objectFit: 'contain',
                            }}
                          />
                          {showBoundary && (
                            <WaterBodyBoundaryOverlay
                              aoiBoundsStr={obs2.aoi_bounds}
                              aoiGeoJsonStr={obs2.aoi_geojson}
                            />
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                ) : (
                  <div style={styles.sliderContainer}>
                    <div style={styles.sliderViewport}>
                      {/* Base Image (Date B) */}
                      <img
                        src={getFilteredUrl(obs2.image_url)}
                        alt={obs2.sensing_date_str}
                        style={styles.sliderImgBase}
                      />
                      {showBoundary && (
                        <WaterBodyBoundaryOverlay
                          aoiBoundsStr={obs2.aoi_bounds}
                          aoiGeoJsonStr={obs2.aoi_geojson}
                        />
                      )}

                      {/* Clipped Top Image (Date A) */}
                      <div
                        style={{
                          ...styles.sliderClippedWrapper,
                          width: `${sliderPos}%`,
                        }}
                      >
                        <img
                          src={getFilteredUrl(obs1.image_url)}
                          alt={obs1.sensing_date_str}
                          style={styles.sliderImgTop}
                        />
                        {showBoundary && (
                          <WaterBodyBoundaryOverlay
                            aoiBoundsStr={obs1.aoi_bounds}
                            aoiGeoJsonStr={obs1.aoi_geojson}
                          />
                        )}
                      </div>

                      {/* Divider line */}
                      <div
                        style={{
                          ...styles.sliderDivider,
                          left: `${sliderPos}%`,
                        }}
                      />
                    </div>

                    <div style={styles.sliderControlRow}>
                      <span style={styles.sliderLabelLeft}>◀ {obs1.sensing_date_str}</span>
                      <input
                        type="range"
                        min="0"
                        max="100"
                        value={sliderPos}
                        onChange={e => setSliderPos(Number(e.target.value))}
                        style={styles.rangeInput}
                      />
                      <span style={styles.sliderLabelRight}>{obs2.sensing_date_str} ▶</span>
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        )}

        {/* ── Section 4: Water Extent Time-Series Chart ──────────────────── */}
        {analysisData && analysisData.timeline.length > 0 && (
          <div style={styles.sectionCard}>
            <div style={styles.sectionHeader}>
              <div>
                <h3 style={styles.sectionTitle}>4. Apparent Water Extent Over Time</h3>
                <span style={styles.sectionSubtitle}>
                  Surface water spread calibrated against registered basin boundary area
                </span>
              </div>
            </div>

            <div style={styles.chartWrapper}>
              <SimpleExtentChart
                timeline={analysisData.timeline}
                registeredAreaSqKm={selectedWaterBody?.area_sq_km}
              />
            </div>
          </div>
        )}

        {/* ── Section 5: Remote-Sensing Water Quality Indicators ────── */}
        <div style={styles.sectionCard}>
          <div style={styles.sectionHeader}>
            <div>
              <div style={styles.kicker}>SPECTRAL ANALYSIS WORKSTATION</div>
              <h3 style={styles.sectionTitle}>5. Remote-Sensing Water Quality Indicators</h3>
              <span style={styles.sectionSubtitle}>
                Lazy on-demand spectral proxies (turbidity, chlorophyll-a, algae, anomaly) calculated strictly on the water-body AOI
              </span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <button
                style={{
                  ...styles.slideBtn,
                  backgroundColor: '#0284c7',
                  color: '#ffffff',
                  fontWeight: 700,
                  fontSize: '0.72rem',
                  padding: '0.45rem 0.85rem',
                }}
                disabled={!selectedWaterBodyId || !spectralObsId || Object.values(isAnalyzing).some(Boolean)}
                onClick={handleCalculateAllForObs}
              >
                {Object.values(isAnalyzing).some(Boolean) ? 'CALCULATING...' : '⚡ CALCULATE ALL 4 INDICATORS'}
              </button>
            </div>
          </div>

          {/* Observation Selector Bar */}
          <div style={styles.spectralToolbar}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap', flex: 1 }}>
              <span style={{ fontSize: '0.72rem', fontWeight: 800, color: '#1e293b', letterSpacing: '0.04em' }}>
                ANALYSIS OBSERVATION:
              </span>
              <select
                style={styles.spectralSelect}
                value={spectralObsId}
                onChange={e => setSpectralObsId(e.target.value)}
              >
                {analysisData?.timeline.map((obs, idx) => (
                  <option key={obs.id} value={obs.id}>
                    {obs.sensing_date_str} {idx === 0 ? '(Earliest)' : idx === analysisData.timeline.length - 1 ? '(Latest)' : ''} — Cloud: {obs.cloud_cover_percent != null ? `${obs.cloud_cover_percent.toFixed(1)}%` : '0%'}
                  </option>
                ))}
              </select>

              <div style={{ display: 'flex', gap: '0.35rem' }}>
                <button
                  style={{
                    ...styles.quickNavBtn,
                    backgroundColor: spectralObsId === analysisData?.timeline[0]?.id ? '#e0f2fe' : '#ffffff',
                    color: spectralObsId === analysisData?.timeline[0]?.id ? '#0369a1' : '#475569',
                    borderColor: spectralObsId === analysisData?.timeline[0]?.id ? '#38bdf8' : '#cbd5e1',
                  }}
                  onClick={() => {
                    if (analysisData?.timeline[0]) setSpectralObsId(analysisData.timeline[0].id);
                  }}
                >
                  ⏮ EARLIEST
                </button>
                <button
                  style={{
                    ...styles.quickNavBtn,
                    backgroundColor:
                      spectralObsId === analysisData?.timeline[analysisData.timeline.length - 1]?.id
                        ? '#e0f2fe'
                        : '#ffffff',
                    color:
                      spectralObsId === analysisData?.timeline[analysisData.timeline.length - 1]?.id
                        ? '#0369a1'
                        : '#475569',
                    borderColor:
                      spectralObsId === analysisData?.timeline[analysisData.timeline.length - 1]?.id
                        ? '#38bdf8'
                        : '#cbd5e1',
                  }}
                  onClick={() => {
                    if (analysisData?.timeline && analysisData.timeline.length > 0) {
                      setSpectralObsId(analysisData.timeline[analysisData.timeline.length - 1].id);
                    }
                  }}
                >
                  LATEST ⏭
                </button>
              </div>
            </div>

            {/* Band Availability Status Chip */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              {isCheckingBands ? (
                <span style={{ fontSize: '0.68rem', color: '#64748b' }}>Checking AOI bands...</span>
              ) : bandAvailability['ndti'] && !bandAvailability['ndti']?.is_ready ? (
                <div
                  style={{
                    ...styles.bandStatusPill,
                    backgroundColor: '#fffbeb',
                    borderColor: '#fde68a',
                    color: '#b45309',
                  }}
                >
                  <span style={{ width: '8px', height: '8px', borderRadius: '50%', backgroundColor: '#f59e0b' }} />
                  <span>
                    Missing bands: {bandAvailability['ndti']?.missing_bands.join(', ')} (RGB fallback active)
                  </span>
                </div>
              ) : (
                <div style={styles.bandStatusPill}>
                  <span style={{ width: '8px', height: '8px', borderRadius: '50%', backgroundColor: '#10b981' }} />
                  <span>Sentinel-2 AOI Bands Ready</span>
                </div>
              )}
            </div>
          </div>

          {/* 4 Spectral Indicator Cards */}
          <div style={styles.spectralGrid}>
            {(['ndti', 'ndci', 'fai', 'anomaly'] as SpectralIndicatorId[]).map(indKey => {
              const meta = INDICATORS_METADATA[indKey];
              const result = spectralResults[indKey];
              const loading = isAnalyzing[indKey] || false;
              const err = spectralError[indKey];

              return (
                <div key={indKey} style={styles.spectralCard}>
                  {/* Card Header */}
                  <div style={styles.spectralCardHeader}>
                    <div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                        <span style={styles.spectralCardBadge}>{meta.badge}</span>
                        <h4 style={styles.spectralCardTitle}>{meta.name}</h4>
                      </div>
                      <span style={styles.spectralCardFormula}>{meta.formula}</span>
                    </div>

                    <button
                      style={styles.infoBtn}
                      title="View Scientific Details & Formula"
                      onClick={() => setInfoModalIndicator(indKey)}
                    >
                      ⓘ
                    </button>
                  </div>

                  {/* Body Content */}
                  <div style={styles.spectralCardBody}>
                    {loading ? (
                      <div style={styles.spectralLoadingBox}>
                        <div style={styles.spinner} />
                        <span style={{ fontSize: '0.72rem', color: '#0284c7', fontWeight: 600 }}>
                          Computing on AOI window...
                        </span>
                      </div>
                    ) : err ? (
                      <div style={styles.spectralErrorBox}>
                        <span style={{ fontSize: '0.72rem', color: '#dc2626', fontWeight: 600 }}>
                          {err}
                        </span>
                        <button
                          style={styles.retryBtn}
                          onClick={() => handleCalculateIndicator(indKey, true)}
                        >
                          Retry
                        </button>
                      </div>
                    ) : result ? (
                      <div>
                        {/* Value and Level Badges */}
                        <div style={styles.spectralValueRow}>
                          <div>
                            <div style={styles.spectralValueLarge}>
                              {result.value != null ? result.value.toFixed(3) : '—'}
                            </div>
                            <div style={{ fontSize: '0.62rem', color: '#64748b', marginTop: '-2px' }}>
                              Index Value (Mean)
                            </div>
                          </div>

                          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '0.25rem' }}>
                            <span style={getLevelBadgeStyle(result.classification)}>
                              {result.classification}
                            </span>
                            <span style={getQualityBadgeStyle(result.quality)}>
                              {result.quality} QUALITY
                            </span>
                          </div>
                        </div>

                        {/* Pixel metrics */}
                        <div style={styles.spectralMetricsBox}>
                          <div style={styles.spectralMetricItem}>
                            <span style={styles.metricLabel}>Water Mask Coverage:</span>
                            <span style={styles.metricVal}>
                              {result.valid_pixel_count.toLocaleString()} px ({result.valid_pixel_percent}%)
                            </span>
                          </div>
                          <div style={styles.spectralMetricItem}>
                            <span style={styles.metricLabel}>Cloud/Shadow Masked:</span>
                            <span style={styles.metricVal}>{result.cloud_pixel_percent}%</span>
                          </div>
                          {result.baseline_mean != null && (
                            <div style={styles.spectralMetricItem}>
                              <span style={styles.metricLabel}>Historical Baseline:</span>
                              <span style={styles.metricVal}>
                                μ = {result.baseline_mean.toFixed(3)}, σ = {result.baseline_std?.toFixed(3)}
                              </span>
                            </div>
                          )}
                        </div>

                        {/* Description & Scientific Disclaimer */}
                        <p style={styles.spectralClassificationDesc}>
                          {result.classification_desc || meta.description}
                        </p>
                      </div>
                    ) : (
                      <div style={styles.spectralUncalculatedBox}>
                        <div style={{ fontSize: '0.72rem', color: '#64748b', lineHeight: 1.4 }}>
                          {meta.description}
                        </div>
                        <div style={{ fontSize: '0.65rem', color: '#94a3b8', fontStyle: 'italic', marginTop: '0.35rem' }}>
                          Bands required: {meta.requiredBands}
                        </div>
                      </div>
                    )}
                  </div>

                  {/* Card Actions Footer */}
                  <div style={styles.spectralCardFooter}>
                    {result ? (
                      <>
                        <button
                          style={styles.previewBtn}
                          onClick={() => setPreviewModalResult(result)}
                        >
                          🔍 VIEW PREVIEW
                        </button>
                        <button
                          style={styles.recalcBtn}
                          disabled={loading}
                          onClick={() => handleCalculateIndicator(indKey, true)}
                        >
                          🔄 RECALCULATE
                        </button>
                      </>
                    ) : (
                      <button
                        style={styles.calculateBtn}
                        disabled={loading || !spectralObsId}
                        onClick={() => handleCalculateIndicator(indKey, false)}
                      >
                        ⚡ CALCULATE {meta.badge}
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>

          {/* Multi-Indicator Summary Table (shown when 2+ indicators calculated) */}
          {Object.values(spectralResults).filter(Boolean).length >= 2 && (
            <div style={styles.multiIndicatorCard}>
              <div style={styles.multiIndicatorHeader}>
                <div>
                  <h4 style={{ margin: 0, fontSize: '0.82rem', color: '#0f172a' }}>
                    Multi-Indicator Comparison Summary ({selectedSpectralObs?.sensing_date_str})
                  </h4>
                  <span style={{ fontSize: '0.68rem', color: '#64748b' }}>
                    Independent remote-sensing optical proxies presented without synthetic aggregated score to preserve scientific validity.
                  </span>
                </div>
              </div>

              <div style={{ overflowX: 'auto' }}>
                <table style={styles.summaryTable}>
                  <thead>
                    <tr>
                      <th style={styles.th}>INDICATOR</th>
                      <th style={styles.th}>INDEX VALUE</th>
                      <th style={styles.th}>CLASSIFICATION</th>
                      <th style={styles.th}>CLEAR WATER COVERAGE</th>
                      <th style={styles.th}>QUALITY</th>
                      <th style={styles.th}>PREVIEW</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(['ndti', 'ndci', 'fai', 'anomaly'] as SpectralIndicatorId[]).map(indKey => {
                      const res = spectralResults[indKey];
                      if (!res) return null;
                      return (
                        <tr key={indKey} style={styles.tr}>
                          <td style={styles.td}>
                            <strong>{res.indicator_label}</strong> ({res.indicator.toUpperCase()})
                          </td>
                          <td style={styles.td}>
                            <strong>{res.value != null ? res.value.toFixed(3) : '—'}</strong>
                          </td>
                          <td style={styles.td}>
                            <span style={getLevelBadgeStyle(res.classification)}>{res.classification}</span>
                          </td>
                          <td style={styles.td}>
                            {res.valid_pixel_count.toLocaleString()} px ({res.valid_pixel_percent}%)
                          </td>
                          <td style={styles.td}>
                            <span style={getQualityBadgeStyle(res.quality)}>{res.quality}</span>
                          </td>
                          <td style={styles.td}>
                            <button
                              style={{ ...styles.quickNavBtn, padding: '0.15rem 0.45rem', fontSize: '0.62rem' }}
                              onClick={() => setPreviewModalResult(res)}
                            >
                              View Map
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Time-Series Spectral Indicator Batch Calculation */}
          <div style={styles.timeSeriesCard}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.75rem' }}>
              <div>
                <h4 style={{ margin: 0, fontSize: '0.82rem', color: '#0f172a' }}>
                  Time-Series Indicator Analysis Across All Observations
                </h4>
                <span style={{ fontSize: '0.68rem', color: '#64748b' }}>
                  Calculate a selected indicator across every acquired observation date to monitor temporal trends.
                </span>
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <select
                  style={styles.spectralSelect}
                  value={timeSeriesIndicator}
                  onChange={e => setTimeSeriesIndicator(e.target.value as SpectralIndicatorId)}
                  disabled={isComputingTimeSeries}
                >
                  <option value="ndti">NDTI — Turbidity / Sediment</option>
                  <option value="ndci">NDCI — Chlorophyll-a</option>
                  <option value="fai">FAI — Algal Activity</option>
                  <option value="anomaly">Anomaly — Spectral Z-Score</option>
                </select>

                <button
                  style={{
                    ...styles.slideBtn,
                    backgroundColor: '#0284c7',
                    color: '#ffffff',
                    fontWeight: 700,
                    fontSize: '0.72rem',
                    padding: '0.45rem 0.85rem',
                  }}
                  disabled={isComputingTimeSeries || !analysisData?.timeline.length}
                  onClick={handleRunTimeSeries}
                >
                  {isComputingTimeSeries ? 'CALCULATING TIME-SERIES...' : 'CALCULATE ACROSS ALL OBSERVATIONS'}
                </button>
              </div>
            </div>

            {/* Time-Series Progress Bar */}
            {isComputingTimeSeries && (
              <div style={{ marginTop: '0.75rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.68rem', color: '#0284c7', marginBottom: '0.25rem' }}>
                  <span>Processing AOI spectral indicators for all dates...</span>
                  <span>{timeSeriesProgress}%</span>
                </div>
                <div style={styles.progressBarTrack}>
                  <div style={{ ...styles.progressBarFill, width: `${timeSeriesProgress}%` }} />
                </div>
              </div>
            )}

            {/* Time-Series Results Table */}
            {timeSeriesResult && (
              <div style={{ marginTop: '1rem', overflowX: 'auto' }}>
                <table style={styles.summaryTable}>
                  <thead>
                    <tr>
                      <th style={styles.th}>DATE</th>
                      <th style={styles.th}>INDICATOR</th>
                      <th style={styles.th}>VALUE</th>
                      <th style={styles.th}>LEVEL</th>
                      <th style={styles.th}>VALID PIXELS</th>
                      <th style={styles.th}>QUALITY</th>
                      <th style={styles.th}>STATUS</th>
                    </tr>
                  </thead>
                  <tbody>
                    {timeSeriesResult.results.map(r => (
                      <tr key={r.id} style={styles.tr}>
                        <td style={styles.td}>
                          <strong>{r.sensing_date_str}</strong>
                        </td>
                        <td style={styles.td}>{r.indicator_label}</td>
                        <td style={styles.td}>
                          <strong>{r.value != null ? r.value.toFixed(3) : '—'}</strong>
                        </td>
                        <td style={styles.td}>
                          <span style={getLevelBadgeStyle(r.classification)}>{r.classification}</span>
                        </td>
                        <td style={styles.td}>
                          {r.valid_pixel_count.toLocaleString()} px ({r.valid_pixel_percent}%)
                        </td>
                        <td style={styles.td}>
                          <span style={getQualityBadgeStyle(r.quality)}>{r.quality}</span>
                        </td>
                        <td style={styles.td}>
                          <span style={{ fontSize: '0.65rem', color: '#64748b' }}>
                            {r.is_cached ? 'Cached' : 'Computed'}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ── 6. AI Water Analysis Assistant ────────────────────────────── */}
      <div style={styles.sectionCard}>
        <div style={styles.sectionHeader}>
          <div>
            <h3 style={styles.sectionTitle}>6. AI Water Analysis Assistant</h3>
            <span style={styles.sectionSubtitle}>
              Ask AI to explain the current satellite observations and analysis results.
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            {aiStatus && (
              <span
                style={{
                  fontSize: '0.68rem',
                  fontWeight: 700,
                  padding: '0.2rem 0.55rem',
                  borderRadius: '3px',
                  backgroundColor: aiStatus.configured ? '#ecfdf5' : '#fef2f2',
                  color: aiStatus.configured ? '#059669' : '#dc2626',
                  border: `1px solid ${aiStatus.configured ? '#a7f3d0' : '#fecaca'}`,
                }}
              >
                {aiStatus.configured ? `AI READY (${aiStatus.model})` : 'AI NOT CONFIGURED'}
              </span>
            )}
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.85rem' }}>
          {/* Target info & Telegram link */}
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              flexWrap: 'wrap',
              gap: '0.5rem',
              padding: '0.55rem 0.85rem',
              backgroundColor: '#f8fafc',
              border: '1px solid #e2e8f0',
              borderRadius: '3px',
            }}
          >
            <div style={{ fontSize: '0.75rem', color: '#334155' }}>
              <strong>Selected:</strong> {selectedWaterBody?.name || 'No water body selected'}
              {selectedSpectralObs && (
                <span style={{ color: '#0284c7', marginLeft: '0.4rem' }}>
                  • Observation: {selectedSpectralObs.sensing_date_str}
                </span>
              )}
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.72rem', color: '#64748b' }}>
              <span>Need alerts or remote monitoring later?</span>
              <a
                href="https://t.me/jalNetra_Helperbot"
                target="_blank"
                rel="noopener noreferrer"
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '0.3rem',
                  color: '#0284c7',
                  fontWeight: 700,
                  textDecoration: 'none',
                  backgroundColor: '#e0f2fe',
                  padding: '0.2rem 0.55rem',
                  borderRadius: '3px',
                  border: '1px solid #bae6fd',
                }}
              >
                💬 OPEN TELEGRAM →
              </a>
            </div>
          </div>

          {/* Quick Actions */}
          <div>
            <div style={{ fontSize: '0.68rem', fontWeight: 700, color: '#475569', marginBottom: '0.4rem', letterSpacing: '0.04em' }}>
              QUICK ACTIONS
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem' }}>
              <button
                style={{
                  ...styles.quickNavBtn,
                  backgroundColor: '#f0fdf4',
                  borderColor: '#86efac',
                  color: '#166534',
                  fontWeight: 700,
                  padding: '0.35rem 0.65rem',
                  fontSize: '0.72rem',
                  cursor: (isAiLoading || !selectedWaterBodyId) ? 'not-allowed' : 'pointer',
                }}
                disabled={isAiLoading || !selectedWaterBodyId}
                onClick={() => handleAskAi('Explain current water condition')}
              >
                [ Explain current water condition ]
              </button>
              <button
                style={{
                  ...styles.quickNavBtn,
                  backgroundColor: '#f0f9ff',
                  borderColor: '#7dd3fc',
                  color: '#0369a1',
                  fontWeight: 700,
                  padding: '0.35rem 0.65rem',
                  fontSize: '0.72rem',
                  cursor: (isAiLoading || !selectedWaterBodyId) ? 'not-allowed' : 'pointer',
                }}
                disabled={isAiLoading || !selectedWaterBodyId}
                onClick={() => handleAskAi('Summarize changes over time')}
              >
                [ Summarize changes over time ]
              </button>
              <button
                style={{
                  ...styles.quickNavBtn,
                  backgroundColor: '#faf5ff',
                  borderColor: '#d8b4fe',
                  color: '#6b21a8',
                  fontWeight: 700,
                  padding: '0.35rem 0.65rem',
                  fontSize: '0.72rem',
                  cursor: (isAiLoading || !selectedWaterBodyId) ? 'not-allowed' : 'pointer',
                }}
                disabled={isAiLoading || !selectedWaterBodyId}
                onClick={() => handleAskAi('Explain spectral indicators')}
              >
                [ Explain spectral indicators ]
              </button>
            </div>
          </div>

          {/* Custom Question Bar */}
          <div>
            <div style={{ fontSize: '0.68rem', fontWeight: 700, color: '#475569', marginBottom: '0.4rem', letterSpacing: '0.04em' }}>
              Ask a question:
            </div>
            <div style={{ display: 'flex', gap: '0.5rem' }}>
              <input
                type="text"
                value={aiQuestion}
                onChange={e => setAiQuestion(e.target.value)}
                onKeyDown={e => {
                  if (e.key === 'Enter' && aiQuestion.trim() && !isAiLoading && selectedWaterBodyId) {
                    handleAskAi(aiQuestion.trim());
                  }
                }}
                placeholder="e.g. What changed between the earliest and latest observation?"
                disabled={isAiLoading || !selectedWaterBodyId}
                style={{
                  flex: 1,
                  padding: '0.45rem 0.75rem',
                  fontSize: '0.75rem',
                  border: '1px solid #cbd5e1',
                  borderRadius: '3px',
                  outline: 'none',
                  backgroundColor: '#ffffff',
                }}
              />
              <button
                style={{
                  ...styles.slideBtn,
                  backgroundColor: '#0f172a',
                  color: '#ffffff',
                  fontWeight: 700,
                  fontSize: '0.72rem',
                  padding: '0.45rem 1rem',
                  cursor: (isAiLoading || !aiQuestion.trim() || !selectedWaterBodyId) ? 'not-allowed' : 'pointer',
                  opacity: (isAiLoading || !aiQuestion.trim() || !selectedWaterBodyId) ? 0.6 : 1,
                }}
                disabled={isAiLoading || !aiQuestion.trim() || !selectedWaterBodyId}
                onClick={() => handleAskAi(aiQuestion.trim())}
              >
                {isAiLoading ? 'THINKING...' : 'ASK AI'}
              </button>
            </div>
          </div>

          {/* AI Response Box */}
          {(aiResponse || isAiLoading || aiError) && (
            <div
              style={{
                marginTop: '0.5rem',
                padding: '0.85rem 1rem',
                backgroundColor: '#f8fafc',
                border: '1px solid #cbd5e1',
                borderRadius: '3px',
              }}
            >
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  borderBottom: '1px solid #e2e8f0',
                  paddingBottom: '0.4rem',
                  marginBottom: '0.6rem',
                }}
              >
                <span style={{ fontSize: '0.72rem', fontWeight: 800, color: '#0f172a', letterSpacing: '0.05em' }}>
                  AI RESPONSE
                </span>
                {aiResponse && (
                  <span style={{ fontSize: '0.65rem', color: '#64748b' }}>
                    Model: {aiResponse.model}
                  </span>
                )}
              </div>

              {isAiLoading && (
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: '#0284c7', fontSize: '0.75rem', padding: '0.5rem 0' }}>
                  <div style={styles.spinner} />
                  <span>JalNetra AI is evaluating observation data and spectral indices...</span>
                </div>
              )}

              {aiError && !isAiLoading && (
                <div style={{ color: '#b91c1c', fontSize: '0.75rem', lineHeight: 1.5 }}>
                  ⚠️ {aiError}
                </div>
              )}

              {aiResponse && !isAiLoading && (
                <div>
                  <div
                    style={{
                      fontSize: '0.78rem',
                      lineHeight: 1.6,
                      color: '#1e293b',
                      whiteSpace: 'pre-wrap',
                    }}
                  >
                    {aiResponse.answer}
                  </div>
                  <div
                    style={{
                      marginTop: '0.75rem',
                      paddingTop: '0.4rem',
                      borderTop: '1px dashed #cbd5e1',
                      fontSize: '0.65rem',
                      color: '#64748b',
                      fontStyle: 'italic',
                    }}
                  >
                    ℹ️ {aiResponse.disclaimer}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* ── Image Expansion Modal ────────────────────────────────────────── */}
      {expandedImage && (
        <div style={styles.expandedOverlay} onClick={() => setExpandedImage(null)}>
          <div style={styles.expandedBox} onClick={e => e.stopPropagation()}>
            <div style={styles.expandedHeader}>
              <div>
                <div style={styles.kicker}>HIGH-RESOLUTION VISUAL OBSERVATION</div>
                <h3 style={{ margin: 0, fontSize: '1rem', color: '#0f172a' }}>
                  {selectedWaterBody?.name} • {expandedImage.sensing_date_str}
                </h3>
              </div>
              <button
                style={styles.closeBtn}
                onClick={() => setExpandedImage(null)}
              >
                ✕
              </button>
            </div>
            <div style={{ display: 'flex', justifyContent: 'center', backgroundColor: '#090d16', padding: '0.5rem 0' }}>
              <div style={{ position: 'relative', display: 'inline-block', maxWidth: '100%', maxHeight: '72vh', lineHeight: 0 }}>
                <img
                  src={getFilteredUrl(expandedImage.image_url)}
                  alt={expandedImage.sensing_date_str}
                  style={{
                    maxHeight: '72vh',
                    maxWidth: '100%',
                    width: 'auto',
                    height: 'auto',
                    display: 'block',
                    objectFit: 'contain',
                  }}
                />
                {showBoundary && (
                  <WaterBodyBoundaryOverlay
                    aoiBoundsStr={expandedImage.aoi_bounds}
                    aoiGeoJsonStr={expandedImage.aoi_geojson}
                  />
                )}
              </div>
            </div>
            <div style={styles.expandedFooter}>
              <span>
                Quality: <strong>{expandedImage.quality_label || 'VISUAL'}</strong>
              </span>
              <span>
                Cloud cover: {expandedImage.cloud_cover_percent != null ? `${expandedImage.cloud_cover_percent.toFixed(1)}%` : 'N/A'}
              </span>
              <span>
                Surface extent: {expandedImage.water_extent_sq_km != null
                  ? `${expandedImage.water_extent_sq_km.toFixed(2)} km²`
                  : 'Visual Observation'}
              </span>
              <span>Sensor: Sentinel-2 L2A</span>
            </div>
          </div>
        </div>
      )}

      {/* ── Fetch Visual Data Modal ──────────────────────────────────────── */}
      {selectedWaterBody && (
        <FetchVisualDataModal
          waterBody={selectedWaterBody}
          isOpen={isFetchModalOpen}
          onClose={() => setIsFetchModalOpen(false)}
          onNavigateToAnalysis={wbId => loadAnalysis(wbId)}
        />
      )}

      {/* ── Spectral Colormapped Preview Modal ─────────────────────────────── */}
      {previewModalResult && (
        <div style={styles.expandedOverlay} onClick={() => setPreviewModalResult(null)}>
          <div style={{ ...styles.expandedBox, maxWidth: '640px' }} onClick={e => e.stopPropagation()}>
            <div style={styles.expandedHeader}>
              <div>
                <div style={styles.kicker}>SPECTRAL INDICATOR RASTER MAP</div>
                <h3 style={{ margin: 0, fontSize: '0.95rem', color: '#0f172a' }}>
                  {previewModalResult.indicator_label} ({previewModalResult.indicator.toUpperCase()}) • {previewModalResult.sensing_date_str}
                </h3>
              </div>
              <button style={styles.closeBtn} onClick={() => setPreviewModalResult(null)}>
                ✕
              </button>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', backgroundColor: '#090d16', padding: '1rem 0' }}>
              <img
                src={getSpectralPreviewImageUrl(selectedWaterBodyId, previewModalResult.id)}
                alt={`${previewModalResult.indicator} preview`}
                style={{
                  maxHeight: '380px',
                  maxWidth: '90%',
                  borderRadius: '3px',
                  boxShadow: '0 4px 12px rgba(0,0,0,0.5)',
                }}
              />

              {/* Colormap Scale Legend */}
              <div style={styles.previewLegendContainer}>
                <span style={{ fontSize: '0.65rem', color: '#94a3b8' }}>
                  Low ({previewModalResult.minimum != null ? previewModalResult.minimum.toFixed(2) : '-1.0'})
                </span>
                <div style={styles.previewLegendBar} />
                <span style={{ fontSize: '0.65rem', color: '#94a3b8' }}>
                  High ({previewModalResult.maximum != null ? previewModalResult.maximum.toFixed(2) : '+1.0'})
                </span>
              </div>
            </div>

            <div style={styles.expandedFooter}>
              <span>Classification: <strong>{previewModalResult.classification}</strong></span>
              <span>Valid water pixels: {previewModalResult.valid_pixel_percent}%</span>
              <span>Quality: <strong>{previewModalResult.quality}</strong></span>
            </div>
          </div>
        </div>
      )}

      {/* ── Scientific Indicator Info Modal ───────────────────────────────── */}
      {infoModalIndicator && INDICATORS_METADATA[infoModalIndicator as SpectralIndicatorId] && (
        <div style={styles.expandedOverlay} onClick={() => setInfoModalIndicator(null)}>
          <div style={{ ...styles.expandedBox, maxWidth: '560px' }} onClick={e => e.stopPropagation()}>
            <div style={styles.expandedHeader}>
              <div>
                <div style={styles.kicker}>SCIENTIFIC SPECIFICATION & DISCLAIMER</div>
                <h3 style={{ margin: 0, fontSize: '0.95rem', color: '#0f172a' }}>
                  {INDICATORS_METADATA[infoModalIndicator as SpectralIndicatorId].name}
                </h3>
              </div>
              <button style={styles.closeBtn} onClick={() => setInfoModalIndicator(null)}>
                ✕
              </button>
            </div>

            <div style={{ padding: '1.25rem', display: 'flex', flexDirection: 'column', gap: '0.85rem' }}>
              <div>
                <div style={{ fontSize: '0.68rem', fontWeight: 800, color: '#475569', letterSpacing: '0.04em' }}>
                  MATHEMATICAL FORMULA:
                </div>
                <div style={styles.formulaCodeBox}>
                  {INDICATORS_METADATA[infoModalIndicator as SpectralIndicatorId].formula}
                </div>
              </div>

              <div>
                <div style={{ fontSize: '0.68rem', fontWeight: 800, color: '#475569', letterSpacing: '0.04em' }}>
                  SENTINEL-2 BANDS USED:
                </div>
                <div style={{ fontSize: '0.75rem', color: '#1e293b', marginTop: '0.2rem' }}>
                  {INDICATORS_METADATA[infoModalIndicator as SpectralIndicatorId].requiredBands}
                </div>
              </div>

              <div>
                <div style={{ fontSize: '0.68rem', fontWeight: 800, color: '#475569', letterSpacing: '0.04em' }}>
                  PHYSICAL PRINCIPLE & SENSITIVITY:
                </div>
                <p style={{ fontSize: '0.74rem', color: '#334155', lineHeight: 1.5, margin: '0.25rem 0 0 0' }}>
                  {INDICATORS_METADATA[infoModalIndicator as SpectralIndicatorId].description}
                </p>
              </div>

              <div style={styles.disclaimerCallout}>
                <div style={{ fontSize: '0.68rem', fontWeight: 800, color: '#b45309', marginBottom: '0.25rem' }}>
                  ⚠ IMPORTANT REMOTE-SENSING LIMITATION:
                </div>
                <div style={{ fontSize: '0.72rem', color: '#78350f', lineHeight: 1.45 }}>
                  {INDICATORS_METADATA[infoModalIndicator as SpectralIndicatorId].disclaimer}
                </div>
              </div>
            </div>

            <div style={{ padding: '0.75rem 1.25rem', backgroundColor: '#f8fafc', borderTop: '1px solid #e2e8f0', display: 'flex', justifyContent: 'flex-end' }}>
              <button style={styles.slideBtn} onClick={() => setInfoModalIndicator(null)}>
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

// ─── Simple SVG Line Chart Component With Benchmark & Tooltip ───────────────
interface ChartProps {
  timeline: ObservationTimelineItem[];
  registeredAreaSqKm?: number | null;
}

const SimpleExtentChart: React.FC<ChartProps> = ({ timeline, registeredAreaSqKm }) => {
  const [hoveredPoint, setHoveredPoint] = useState<{
    x: number;
    y: number;
    item: ObservationTimelineItem;
  } | null>(null);
  const [showInfo, setShowInfo] = useState<boolean>(false);

  const pointsWithValues = timeline.filter(t => t.water_extent_sq_km != null);
  if (pointsWithValues.length === 0) {
    return (
      <div style={{ padding: '2rem', textAlign: 'center', color: '#64748b' }}>
        No numeric extent values available to plot.
      </div>
    );
  }

  const values = pointsWithValues.map(p => p.water_extent_sq_km as number);
  if (registeredAreaSqKm) values.push(registeredAreaSqKm);

  const minVal = Math.min(...values);
  const maxVal = Math.max(...values);
  const range = Math.max(maxVal - minVal, 0.2);

  const paddingY = range * 0.2;
  const yMin = Math.max(0, minVal - paddingY);
  const yMax = maxVal + paddingY;
  const ySpan = Math.max(yMax - yMin, 0.1);

  const width = 800;
  const height = 240;
  const padLeft = 65;
  const padRight = 40;
  const padTop = 30;
  const padBottom = 45;

  const chartW = width - padLeft - padRight;
  const chartH = height - padTop - padBottom;

  const coords = pointsWithValues.map((p, idx) => {
    const x =
      padLeft +
      (pointsWithValues.length > 1
        ? (idx / (pointsWithValues.length - 1)) * chartW
        : chartW / 2);
    const y =
      padTop +
      chartH -
      (((p.water_extent_sq_km as number) - yMin) / ySpan) * chartH;
    return { x, y, item: p };
  });

  const pathD = coords.reduce((acc, pt, idx) => {
    return idx === 0 ? `M ${pt.x} ${pt.y}` : `${acc} L ${pt.x} ${pt.y}`;
  }, '');

  // Registered area line Y coordinate
  const regY =
    registeredAreaSqKm != null
      ? padTop + chartH - ((registeredAreaSqKm - yMin) / ySpan) * chartH
      : null;

  return (
    <div style={{ position: 'relative' }}>
      {/* Chart Header with Info Button */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: '0.5rem',
          padding: '0 0.5rem',
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '1.25rem',
            fontSize: '0.74rem',
          }}
        >
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.4rem' }}>
            <span
              style={{
                width: '10px',
                height: '10px',
                borderRadius: '50%',
                backgroundColor: '#0284c7',
                display: 'inline-block',
              }}
            />
            Apparent Water Extent
          </span>
          {registeredAreaSqKm && (
            <span
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '0.4rem',
                color: '#b45309',
                fontWeight: 600,
              }}
            >
              <span
                style={{
                  width: '14px',
                  height: '2px',
                  backgroundColor: '#f59e0b',
                  borderTop: '2px dashed #f59e0b',
                  display: 'inline-block',
                }}
              />
              Registered Basin Reference ({registeredAreaSqKm.toFixed(2)} km²)
            </span>
          )}
        </div>

        <div style={{ position: 'relative' }}>
          <button
            style={{
              width: '24px',
              height: '24px',
              borderRadius: '50%',
              backgroundColor: showInfo ? '#0284c7' : '#e2e8f0',
              color: showInfo ? '#ffffff' : '#334155',
              border: 'none',
              cursor: 'pointer',
              fontSize: '12px',
              fontWeight: 'bold',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
            onClick={() => setShowInfo(!showInfo)}
            title="Apparent Extent Information"
          >
            ⓘ
          </button>

          {showInfo && (
            <div
              style={{
                position: 'absolute',
                top: '30px',
                right: '0',
                width: '320px',
                backgroundColor: '#ffffff',
                border: '1px solid #cbd5e1',
                borderRadius: '6px',
                boxShadow: '0 4px 14px rgba(0,0,0,0.12)',
                padding: '0.85rem',
                zIndex: 100,
                fontSize: '0.72rem',
                color: '#334155',
                lineHeight: 1.45,
              }}
            >
              <div
                style={{
                  fontWeight: 700,
                  color: '#0f172a',
                  marginBottom: '0.35rem',
                  fontSize: '0.78rem',
                }}
              >
                About Apparent Water Extent
              </div>
              <p style={{ margin: '0 0 0.5rem' }}>
                Displays surface water spread across Sentinel-2 observations calibrated against the registered basin reference area.
              </p>
              <p style={{ margin: 0, color: '#64748b' }}>
                Variations capture seasonal monsoon expansion and dry-season evaporation. Full pixel-level spectral segmentation is enabled in Level 2 processing.
              </p>
            </div>
          )}
        </div>
      </div>

      <svg
        viewBox={`0 0 ${width} ${height}`}
        style={{ width: '100%', height: 'auto', display: 'block' }}
      >
        {/* Grid Lines */}
        <line
          x1={padLeft}
          y1={padTop}
          x2={width - padRight}
          y2={padTop}
          stroke="#f1f5f9"
          strokeDasharray="3 3"
        />
        <line
          x1={padLeft}
          y1={padTop + chartH / 2}
          x2={width - padRight}
          y2={padTop + chartH / 2}
          stroke="#f1f5f9"
          strokeDasharray="3 3"
        />
        <line
          x1={padLeft}
          y1={padTop + chartH}
          x2={width - padRight}
          y2={padTop + chartH}
          stroke="#cbd5e1"
        />

        {/* Y Axis Labels */}
        <text
          x={padLeft - 8}
          y={padTop + 4}
          textAnchor="end"
          fontSize="10"
          fill="#64748b"
          fontFamily="sans-serif"
        >
          {yMax.toFixed(2)} km²
        </text>
        <text
          x={padLeft - 8}
          y={padTop + chartH / 2 + 3}
          textAnchor="end"
          fontSize="10"
          fill="#64748b"
          fontFamily="sans-serif"
        >
          {((yMax + yMin) / 2).toFixed(2)} km²
        </text>
        <text
          x={padLeft - 8}
          y={padTop + chartH + 3}
          textAnchor="end"
          fontSize="10"
          fill="#64748b"
          fontFamily="sans-serif"
        >
          {yMin.toFixed(2)} km²
        </text>

        {/* Registered Benchmark Line */}
        {regY !== null && regY >= padTop && regY <= padTop + chartH && (
          <g>
            <line
              x1={padLeft}
              y1={regY}
              x2={width - padRight}
              y2={regY}
              stroke="#f59e0b"
              strokeDasharray="5 3"
              strokeWidth="1.5"
            />
            <text
              x={width - padRight}
              y={regY - 5}
              textAnchor="end"
              fontSize="9"
              fill="#b45309"
              fontWeight="600"
              fontFamily="sans-serif"
            >
              Basin: {registeredAreaSqKm?.toFixed(2)} km²
            </text>
          </g>
        )}

        {/* Area fill under curve */}
        {coords.length > 1 && (
          <path
            d={`${pathD} L ${coords[coords.length - 1].x} ${padTop + chartH} L ${coords[0].x} ${
              padTop + chartH
            } Z`}
            fill="rgba(2, 132, 199, 0.08)"
          />
        )}

        {/* Line Path */}
        {coords.length > 1 && (
          <path
            d={pathD}
            fill="none"
            stroke="#0284c7"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        )}

        {/* Points */}
        {coords.map(pt => {
          const isSelected = hoveredPoint?.item.id === pt.item.id;
          return (
            <g
              key={pt.item.id}
              style={{ cursor: 'pointer' }}
              onMouseEnter={() => setHoveredPoint(pt)}
              onMouseLeave={() => setHoveredPoint(null)}
            >
              <circle
                cx={pt.x}
                cy={pt.y}
                r={isSelected ? '7' : '5'}
                fill={isSelected ? '#0ea5e9' : '#0284c7'}
                stroke="#ffffff"
                strokeWidth="2"
              />
              <text
                x={pt.x}
                y={height - 12}
                textAnchor="middle"
                fontSize="9"
                fill="#475569"
                fontFamily="sans-serif"
              >
                {pt.item.sensing_date_str.slice(5)}
              </text>
              <text
                x={pt.x}
                y={pt.y - 9}
                textAnchor="middle"
                fontSize="9"
                fontWeight="bold"
                fill="#0f172a"
                fontFamily="sans-serif"
              >
                {pt.item.water_extent_sq_km?.toFixed(2)}
              </text>
            </g>
          );
        })}
      </svg>

      {/* Floating Hover Tooltip */}
      {hoveredPoint && (
        <div
          style={{
            position: 'absolute',
            left: `${(hoveredPoint.x / width) * 100}%`,
            top: `${(hoveredPoint.y / height) * 100}%`,
            transform: 'translate(-50%, -125%)',
            backgroundColor: '#0f172a',
            color: '#ffffff',
            padding: '0.45rem 0.75rem',
            borderRadius: '4px',
            fontSize: '0.72rem',
            whiteSpace: 'nowrap',
            boxShadow: '0 4px 12px rgba(0,0,0,0.25)',
            pointerEvents: 'none',
            zIndex: 50,
          }}
        >
          <div style={{ fontWeight: 700, color: '#38bdf8' }}>
            {hoveredPoint.item.sensing_date_str}
          </div>
          <div>
            Extent: <strong>{hoveredPoint.item.water_extent_sq_km?.toFixed(2)} km²</strong>
          </div>
          <div style={{ fontSize: '0.62rem', color: '#94a3b8', marginTop: '2px' }}>
            {hoveredPoint.item.is_demo_extent
              ? 'Seasonal estimated baseline'
              : 'Segmented observation'}
          </div>
        </div>
      )}
    </div>
  );
};

// ─── Styles ───────────────────────────────────────────────────────────────────
const styles: Record<string, React.CSSProperties> = {
  container: {
    display: 'flex',
    flexDirection: 'column',
    height: '100%',
    width: '100%',
    backgroundColor: '#f8fafc',
    fontFamily: 'Inter, system-ui, sans-serif',
  },
  topBar: {
    padding: '0.85rem 1.5rem',
    backgroundColor: '#ffffff',
    borderBottom: '1px solid #e2e8f0',
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    flexWrap: 'wrap',
    gap: '0.75rem',
  },
  topBarLeft: {
    display: 'flex',
    flexDirection: 'column',
    gap: '0.1rem',
  },
  kicker: {
    fontSize: '0.65rem',
    fontWeight: 700,
    color: '#0284c7',
    letterSpacing: '0.06em',
    textTransform: 'uppercase',
  },
  pageTitle: {
    margin: 0,
    fontSize: '1.25rem',
    fontWeight: 800,
    color: '#0f172a',
    letterSpacing: '-0.01em',
  },
  topBarRight: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.75rem',
  },
  selectorGroup: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.4rem',
  },
  selectorLabel: {
    fontSize: '0.68rem',
    fontWeight: 700,
    color: '#475569',
  },
  wbSelect: {
    padding: '0.4rem 0.65rem',
    border: '1px solid #cbd5e1',
    borderRadius: '3px',
    fontSize: '0.78rem',
    fontWeight: 600,
    color: '#0f172a',
    backgroundColor: '#ffffff',
    outline: 'none',
  },
  fetchBtn: {
    padding: '0.45rem 0.85rem',
    backgroundColor: '#0284c7',
    color: '#ffffff',
    border: 'none',
    borderRadius: '3px',
    fontSize: '0.72rem',
    fontWeight: 700,
    cursor: 'pointer',
    letterSpacing: '0.02em',
  },
  mapNavBtn: {
    padding: '0.45rem 0.85rem',
    backgroundColor: '#f1f5f9',
    color: '#334155',
    border: '1px solid #cbd5e1',
    borderRadius: '3px',
    fontSize: '0.72rem',
    fontWeight: 700,
    cursor: 'pointer',
  },
  contentScroll: {
    flex: 1,
    overflowY: 'auto',
    padding: '1.25rem 1.5rem',
    display: 'flex',
    flexDirection: 'column',
    gap: '1.25rem',
  },
  errorBanner: {
    padding: '0.75rem 1rem',
    backgroundColor: '#fef2f2',
    border: '1px solid #fecaca',
    borderRadius: '3px',
    color: '#991b1b',
    fontSize: '0.8rem',
  },
  metaBanner: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
    gap: '0.75rem',
    backgroundColor: '#ffffff',
    padding: '1rem',
    borderRadius: '4px',
    border: '1px solid #e2e8f0',
  },
  statCell: {
    display: 'flex',
    flexDirection: 'column',
    gap: '0.15rem',
  },
  statLabel: {
    fontSize: '0.65rem',
    fontWeight: 700,
    color: '#64748b',
    letterSpacing: '0.04em',
  },
  statValuePrimary: {
    fontSize: '1.1rem',
    fontWeight: 800,
    color: '#0f172a',
  },
  statValue: {
    fontSize: '1.05rem',
    fontWeight: 700,
    color: '#0284c7',
  },
  statSub: {
    fontSize: '0.68rem',
    color: '#64748b',
  },
  toolbarBanner: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    flexWrap: 'wrap',
    gap: '1rem',
    backgroundColor: '#ffffff',
    padding: '0.75rem 1rem',
    borderRadius: '4px',
    border: '1px solid #e2e8f0',
  },
  toolbarLeft: {
    display: 'flex',
    alignItems: 'center',
    gap: '1.5rem',
    flexWrap: 'wrap',
  },
  toolbarRight: {
    display: 'flex',
    alignItems: 'center',
  },
  toolbarItem: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.45rem',
  },
  toolbarLabel: {
    fontSize: '0.68rem',
    fontWeight: 700,
    color: '#475569',
  },
  toolbarSelect: {
    padding: '0.35rem 0.6rem',
    border: '1px solid #cbd5e1',
    borderRadius: '3px',
    fontSize: '0.75rem',
    fontWeight: 600,
    color: '#0f172a',
    backgroundColor: '#f8fafc',
    outline: 'none',
  },
  boundaryToggleLabel: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.4rem',
    fontSize: '0.72rem',
    cursor: 'pointer',
  },
  boundaryPill: {
    fontSize: '0.6rem',
    fontWeight: 800,
    padding: '0.1rem 0.35rem',
    backgroundColor: '#06b6d4',
    color: '#ffffff',
    borderRadius: '2px',
    letterSpacing: '0.04em',
  },
  slideshowContainer: {
    display: 'flex',
    flexDirection: 'column',
    gap: '0.85rem',
    backgroundColor: '#f8fafc',
    border: '1px solid #e2e8f0',
    borderRadius: '4px',
    padding: '0.85rem',
  },
  slideshowViewport: {
    position: 'relative',
    width: '100%',
    maxHeight: '440px',
    minHeight: '260px',
    height: '420px',
    backgroundColor: '#090d16',
    borderRadius: '4px',
    overflow: 'hidden',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
  },
  slideshowImg: {
    width: '100%',
    height: '100%',
    objectFit: 'contain',
    display: 'block',
  },
  slideshowBadgeTopLeft: {
    position: 'absolute',
    top: '10px',
    left: '10px',
    backgroundColor: 'rgba(15, 23, 42, 0.85)',
    color: '#ffffff',
    fontSize: '0.72rem',
    fontWeight: 700,
    padding: '0.25rem 0.6rem',
    borderRadius: '3px',
    display: 'flex',
    alignItems: 'center',
    gap: '0.4rem',
    zIndex: 10,
    fontFamily: 'monospace',
  },
  slideshowBadgeTopRight: {
    position: 'absolute',
    top: '10px',
    right: '10px',
    backgroundColor: 'rgba(15, 23, 42, 0.85)',
    color: '#38bdf8',
    fontSize: '0.72rem',
    fontWeight: 700,
    padding: '0.25rem 0.6rem',
    borderRadius: '3px',
    display: 'flex',
    alignItems: 'center',
    gap: '0.6rem',
    zIndex: 10,
  },
  slideshowBoundaryPill: {
    position: 'absolute',
    bottom: '10px',
    right: '10px',
    backgroundColor: 'rgba(6, 182, 212, 0.9)',
    color: '#ffffff',
    fontSize: '0.68rem',
    fontWeight: 700,
    padding: '0.2rem 0.5rem',
    borderRadius: '3px',
    zIndex: 10,
  },
  slideshowControlsRow: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    flexWrap: 'wrap',
    gap: '1rem',
    padding: '0.35rem 0.5rem',
  },
  slideBtn: {
    padding: '0.4rem 0.75rem',
    backgroundColor: '#ffffff',
    color: '#1e293b',
    border: '1px solid #cbd5e1',
    borderRadius: '3px',
    fontSize: '0.72rem',
    fontWeight: 700,
    cursor: 'pointer',
  },
  emptyCard: {
    padding: '3rem 2rem',
    backgroundColor: '#ffffff',
    border: '1px dashed #cbd5e1',
    borderRadius: '4px',
    textAlign: 'center',
    maxWidth: '560px',
    margin: '2rem auto',
  },
  emptyIcon: {
    fontSize: '2.5rem',
    marginBottom: '0.5rem',
  },
  emptyTitle: {
    margin: '0 0 0.5rem',
    fontSize: '1.1rem',
    fontWeight: 700,
    color: '#0f172a',
  },
  emptyDesc: {
    fontSize: '0.8rem',
    color: '#64748b',
    lineHeight: 1.5,
    margin: '0 0 1.25rem',
  },
  emptyActionBtn: {
    padding: '0.6rem 1.25rem',
    backgroundColor: '#0284c7',
    color: '#ffffff',
    border: 'none',
    borderRadius: '3px',
    fontSize: '0.75rem',
    fontWeight: 700,
    cursor: 'pointer',
  },
  sectionCard: {
    backgroundColor: '#ffffff',
    borderRadius: '4px',
    border: '1px solid #e2e8f0',
    padding: '1.25rem',
    display: 'flex',
    flexDirection: 'column',
    gap: '1rem',
  },
  sectionHeader: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    flexWrap: 'wrap',
    gap: '0.5rem',
    borderBottom: '1px solid #f1f5f9',
    paddingBottom: '0.75rem',
  },
  sectionTitle: {
    margin: 0,
    fontSize: '0.95rem',
    fontWeight: 800,
    color: '#0f172a',
    letterSpacing: '-0.01em',
  },
  sectionSubtitle: {
    fontSize: '0.72rem',
    color: '#64748b',
  },
  galleryGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))',
    gap: '1rem',
  },
  galleryCard: {
    border: '1px solid #e2e8f0',
    borderRadius: '4px',
    overflow: 'hidden',
    backgroundColor: '#ffffff',
    cursor: 'pointer',
    transition: 'transform 0.15s, box-shadow 0.15s',
  },
  thumbWrapper: {
    position: 'relative',
    width: '100%',
    paddingTop: '75%',
    backgroundColor: '#0f172a',
  },
  thumbImg: {
    position: 'absolute',
    top: 0,
    left: 0,
    width: '100%',
    height: '100%',
    objectFit: 'cover',
  },
  thumbDateBadge: {
    position: 'absolute',
    bottom: '6px',
    left: '6px',
    backgroundColor: 'rgba(15, 23, 42, 0.8)',
    color: '#ffffff',
    fontSize: '0.65rem',
    fontWeight: 700,
    padding: '2px 6px',
    borderRadius: '2px',
    fontFamily: 'monospace',
    zIndex: 10,
  },
  cardDetails: {
    padding: '0.65rem',
    display: 'flex',
    flexDirection: 'column',
    gap: '0.3rem',
    fontSize: '0.7rem',
  },
  cardDetailRow: {
    display: 'flex',
    justifyContent: 'space-between',
    color: '#475569',
  },
  cardFooter: {
    borderTop: '1px solid #f1f5f9',
    paddingTop: '0.4rem',
    marginTop: '0.2rem',
    display: 'flex',
    justifyContent: 'space-between',
    fontSize: '0.65rem',
    color: '#94a3b8',
  },
  compareModeToggle: {
    display: 'flex',
    border: '1px solid #cbd5e1',
    borderRadius: '3px',
    overflow: 'hidden',
  },
  modeToggleBtn: {
    padding: '0.35rem 0.75rem',
    backgroundColor: '#f8fafc',
    border: 'none',
    fontSize: '0.72rem',
    fontWeight: 600,
    color: '#475569',
    cursor: 'pointer',
  },
  modeToggleBtnActive: {
    backgroundColor: '#0284c7',
    color: '#ffffff',
    fontWeight: 700,
  },
  comparePickersRow: {
    display: 'flex',
    alignItems: 'center',
    gap: '1rem',
    flexWrap: 'wrap',
    padding: '0.5rem 0.75rem',
    backgroundColor: '#f8fafc',
    border: '1px solid #e2e8f0',
    borderRadius: '3px',
  },
  comparePickerBox: {
    flex: 1,
    minWidth: '200px',
    display: 'flex',
    flexDirection: 'column',
    gap: '0.2rem',
  },
  pickerLabel: {
    fontSize: '0.65rem',
    fontWeight: 700,
    color: '#475569',
  },
  pickerSelect: {
    padding: '0.4rem 0.6rem',
    border: '1px solid #cbd5e1',
    borderRadius: '3px',
    fontSize: '0.75rem',
    color: '#0f172a',
    backgroundColor: '#ffffff',
    outline: 'none',
  },
  vsBadge: {
    fontSize: '0.75rem',
    fontWeight: 800,
    color: '#0284c7',
    padding: '0.2rem 0.5rem',
  },
  sideBySideGrid: {
    display: 'grid',
    gridTemplateColumns: '1fr 1fr',
    gap: '1rem',
  },
  compareViewport: {
    border: '1px solid #cbd5e1',
    borderRadius: '3px',
    overflow: 'hidden',
    backgroundColor: '#0f172a',
  },
  viewportHeader: {
    padding: '0.4rem 0.75rem',
    backgroundColor: 'rgba(15, 23, 42, 0.9)',
    color: '#ffffff',
    fontSize: '0.7rem',
    fontWeight: 600,
    display: 'flex',
    justifyContent: 'space-between',
  },
  compareImg: {
    width: '100%',
    height: 'auto',
    maxHeight: '380px',
    objectFit: 'contain',
    display: 'block',
  },
  sliderContainer: {
    display: 'flex',
    flexDirection: 'column',
    gap: '0.75rem',
    alignItems: 'center',
  },
  sliderViewport: {
    position: 'relative',
    width: '100%',
    maxWidth: '680px',
    height: '400px',
    overflow: 'hidden',
    backgroundColor: '#0f172a',
    borderRadius: '3px',
    border: '1px solid #cbd5e1',
  },
  sliderImgBase: {
    position: 'absolute',
    top: 0,
    left: 0,
    width: '100%',
    height: '100%',
    objectFit: 'contain',
  },
  sliderClippedWrapper: {
    position: 'absolute',
    top: 0,
    left: 0,
    height: '100%',
    overflow: 'hidden',
  },
  sliderImgTop: {
    position: 'absolute',
    top: 0,
    left: 0,
    width: '680px',
    height: '100%',
    objectFit: 'contain',
  },
  sliderDivider: {
    position: 'absolute',
    top: 0,
    bottom: 0,
    width: '3px',
    backgroundColor: '#ffffff',
    boxShadow: '0 0 5px rgba(0,0,0,0.5)',
    transform: 'translateX(-50%)',
    pointerEvents: 'none',
  },
  sliderControlRow: {
    display: 'flex',
    alignItems: 'center',
    gap: '1rem',
    width: '100%',
    maxWidth: '680px',
  },
  sliderLabelLeft: {
    fontSize: '0.72rem',
    fontWeight: 700,
    color: '#0284c7',
  },
  sliderLabelRight: {
    fontSize: '0.72rem',
    fontWeight: 700,
    color: '#0284c7',
  },
  rangeInput: {
    flex: 1,
    cursor: 'pointer',
  },
  chartWrapper: {
    padding: '0.5rem',
    backgroundColor: '#ffffff',
    border: '1px solid #f1f5f9',
    borderRadius: '3px',
  },
  indicatorsGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
    gap: '0.75rem',
  },
  indicatorCard: {
    padding: '0.85rem',
    border: '1px dashed #cbd5e1',
    borderRadius: '4px',
    backgroundColor: '#f8fafc',
    display: 'flex',
    flexDirection: 'column',
    gap: '0.4rem',
  },
  indHeader: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    gap: '0.4rem',
  },
  indLabel: {
    fontSize: '0.75rem',
    fontWeight: 700,
    color: '#1e293b',
  },
  indStatusBadge: {
    fontSize: '0.58rem',
    fontWeight: 700,
    color: '#475569',
    backgroundColor: '#e2e8f0',
    padding: '0.12rem 0.4rem',
    borderRadius: '2px',
  },
  indDesc: {
    fontSize: '0.68rem',
    color: '#64748b',
    lineHeight: 1.35,
    margin: 0,
  },
  indFooter: {
    borderTop: '1px solid #e2e8f0',
    paddingTop: '0.35rem',
    marginTop: 'auto',
    display: 'flex',
    justifyContent: 'space-between',
    fontSize: '0.62rem',
    color: '#94a3b8',
  },
  indDisabledText: {
    fontStyle: 'italic',
  },
  expandedOverlay: {
    position: 'fixed',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: 'rgba(15, 23, 42, 0.85)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    zIndex: 99999,
    padding: '1.5rem',
  },
  expandedBox: {
    backgroundColor: '#ffffff',
    borderRadius: '4px',
    overflow: 'hidden',
    maxWidth: '800px',
    width: '100%',
    display: 'flex',
    flexDirection: 'column',
  },
  expandedHeader: {
    padding: '0.85rem 1.25rem',
    borderBottom: '1px solid #e2e8f0',
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  expandedImg: {
    width: '100%',
    maxHeight: '70vh',
    objectFit: 'contain',
    backgroundColor: '#0f172a',
    display: 'block',
  },
  expandedFooter: {
    padding: '0.65rem 1.25rem',
    backgroundColor: '#f8fafc',
    borderTop: '1px solid #e2e8f0',
    display: 'flex',
    justifyContent: 'space-between',
    fontSize: '0.72rem',
    color: '#475569',
  },
  closeBtn: {
    background: 'none',
    border: 'none',
    fontSize: '1.1rem',
    color: '#64748b',
    cursor: 'pointer',
  },
  spectralToolbar: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    flexWrap: 'wrap',
    gap: '0.75rem',
    padding: '0.65rem 0.85rem',
    backgroundColor: '#f8fafc',
    border: '1px solid #e2e8f0',
    borderRadius: '4px',
  },
  spectralSelect: {
    padding: '0.35rem 0.6rem',
    border: '1px solid #cbd5e1',
    borderRadius: '3px',
    fontSize: '0.75rem',
    color: '#0f172a',
    backgroundColor: '#ffffff',
    outline: 'none',
    fontWeight: 600,
  },
  quickNavBtn: {
    padding: '0.3rem 0.6rem',
    border: '1px solid #cbd5e1',
    borderRadius: '3px',
    fontSize: '0.68rem',
    fontWeight: 700,
    cursor: 'pointer',
    transition: 'all 0.15s ease',
  },
  bandStatusPill: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.45rem',
    padding: '0.25rem 0.6rem',
    backgroundColor: '#ecfdf5',
    border: '1px solid #a7f3d0',
    borderRadius: '3px',
    fontSize: '0.68rem',
    fontWeight: 700,
    color: '#065f46',
  },
  spectralGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
    gap: '1rem',
  },
  spectralCard: {
    backgroundColor: '#ffffff',
    border: '1px solid #e2e8f0',
    borderRadius: '4px',
    display: 'flex',
    flexDirection: 'column',
    overflow: 'hidden',
    boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
  },
  spectralCardHeader: {
    padding: '0.75rem 0.95rem',
    borderBottom: '1px solid #f1f5f9',
    backgroundColor: '#f8fafc',
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    gap: '0.5rem',
  },
  spectralCardBadge: {
    backgroundColor: '#0284c7',
    color: '#ffffff',
    fontSize: '0.62rem',
    fontWeight: 800,
    padding: '0.15rem 0.4rem',
    borderRadius: '2px',
    letterSpacing: '0.04em',
  },
  spectralCardTitle: {
    margin: 0,
    fontSize: '0.82rem',
    fontWeight: 700,
    color: '#0f172a',
  },
  spectralCardFormula: {
    fontSize: '0.65rem',
    fontFamily: 'monospace',
    color: '#64748b',
    display: 'block',
    marginTop: '0.15rem',
  },
  infoBtn: {
    background: 'none',
    border: '1px solid #cbd5e1',
    borderRadius: '50%',
    width: '20px',
    height: '20px',
    fontSize: '0.7rem',
    fontWeight: 700,
    color: '#64748b',
    cursor: 'pointer',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    flexShrink: 0,
  },
  spectralCardBody: {
    padding: '0.95rem',
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
    justifyContent: 'center',
  },
  spectralLoadingBox: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    padding: '1.5rem',
    gap: '0.5rem',
  },
  spinner: {
    width: '24px',
    height: '24px',
    border: '3px solid #e2e8f0',
    borderTopColor: '#0284c7',
    borderRadius: '50%',
    animation: 'spin 1s linear infinite',
  },
  spectralErrorBox: {
    padding: '0.75rem',
    backgroundColor: '#fef2f2',
    border: '1px solid #fecaca',
    borderRadius: '3px',
    display: 'flex',
    flexDirection: 'column',
    gap: '0.4rem',
    alignItems: 'flex-start',
  },
  retryBtn: {
    padding: '0.25rem 0.55rem',
    backgroundColor: '#dc2626',
    color: '#ffffff',
    border: 'none',
    borderRadius: '2px',
    fontSize: '0.68rem',
    fontWeight: 700,
    cursor: 'pointer',
  },
  spectralValueRow: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    marginBottom: '0.75rem',
  },
  spectralValueLarge: {
    fontSize: '1.5rem',
    fontWeight: 800,
    color: '#0f172a',
    fontFamily: 'monospace',
    lineHeight: 1.1,
  },
  spectralMetricsBox: {
    display: 'flex',
    flexDirection: 'column',
    gap: '0.25rem',
    padding: '0.5rem 0.65rem',
    backgroundColor: '#f8fafc',
    border: '1px solid #f1f5f9',
    borderRadius: '3px',
    marginBottom: '0.65rem',
  },
  spectralMetricItem: {
    display: 'flex',
    justifyContent: 'space-between',
    fontSize: '0.65rem',
  },
  metricLabel: {
    color: '#64748b',
    fontWeight: 600,
  },
  metricVal: {
    color: '#0f172a',
    fontWeight: 700,
  },
  spectralClassificationDesc: {
    margin: 0,
    fontSize: '0.68rem',
    color: '#475569',
    lineHeight: 1.4,
  },
  spectralUncalculatedBox: {
    padding: '0.5rem 0',
  },
  spectralCardFooter: {
    padding: '0.65rem 0.95rem',
    backgroundColor: '#f8fafc',
    borderTop: '1px solid #f1f5f9',
    display: 'flex',
    gap: '0.5rem',
  },
  calculateBtn: {
    flex: 1,
    padding: '0.45rem',
    backgroundColor: '#0284c7',
    color: '#ffffff',
    border: 'none',
    borderRadius: '3px',
    fontSize: '0.72rem',
    fontWeight: 700,
    cursor: 'pointer',
    textAlign: 'center',
  },
  previewBtn: {
    flex: 1,
    padding: '0.4rem',
    backgroundColor: '#ffffff',
    color: '#0f172a',
    border: '1px solid #cbd5e1',
    borderRadius: '3px',
    fontSize: '0.68rem',
    fontWeight: 700,
    cursor: 'pointer',
  },
  recalcBtn: {
    padding: '0.4rem 0.6rem',
    backgroundColor: '#ffffff',
    color: '#64748b',
    border: '1px solid #cbd5e1',
    borderRadius: '3px',
    fontSize: '0.68rem',
    fontWeight: 700,
    cursor: 'pointer',
  },
  multiIndicatorCard: {
    marginTop: '0.5rem',
    padding: '1rem',
    backgroundColor: '#ffffff',
    border: '1px solid #e2e8f0',
    borderRadius: '4px',
    display: 'flex',
    flexDirection: 'column',
    gap: '0.75rem',
  },
  multiIndicatorHeader: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    flexWrap: 'wrap',
    gap: '0.5rem',
  },
  summaryTable: {
    width: '100%',
    borderCollapse: 'collapse',
    fontSize: '0.72rem',
  },
  th: {
    textAlign: 'left',
    padding: '0.45rem 0.65rem',
    backgroundColor: '#f1f5f9',
    color: '#475569',
    fontSize: '0.65rem',
    fontWeight: 700,
    letterSpacing: '0.04em',
    borderBottom: '1px solid #cbd5e1',
  },
  tr: {
    borderBottom: '1px solid #f1f5f9',
  },
  td: {
    padding: '0.5rem 0.65rem',
    color: '#1e293b',
    fontSize: '0.72rem',
  },
  timeSeriesCard: {
    marginTop: '0.5rem',
    padding: '1rem',
    backgroundColor: '#ffffff',
    border: '1px solid #e2e8f0',
    borderRadius: '4px',
  },
  progressBarTrack: {
    width: '100%',
    height: '6px',
    backgroundColor: '#e2e8f0',
    borderRadius: '3px',
    overflow: 'hidden',
  },
  progressBarFill: {
    height: '100%',
    backgroundColor: '#0284c7',
    transition: 'width 0.3s ease',
  },
  previewLegendContainer: {
    marginTop: '0.75rem',
    display: 'flex',
    alignItems: 'center',
    gap: '0.6rem',
  },
  previewLegendBar: {
    width: '160px',
    height: '10px',
    borderRadius: '2px',
    background: 'linear-gradient(to right, #0284c7, #10b981, #facc15, #dc2626)',
    border: '1px solid rgba(255,255,255,0.2)',
  },
  formulaCodeBox: {
    fontFamily: 'monospace',
    backgroundColor: '#0f172a',
    color: '#38bdf8',
    padding: '0.5rem 0.75rem',
    borderRadius: '4px',
    fontSize: '0.78rem',
    marginTop: '0.2rem',
  },
  disclaimerCallout: {
    backgroundColor: '#fffbeb',
    border: '1px solid #fde68a',
    borderRadius: '4px',
    padding: '0.65rem 0.85rem',
  },
};
