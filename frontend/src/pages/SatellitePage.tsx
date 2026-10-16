import React, { useState, useEffect } from 'react';
import {
  listWaterBodies,
  searchSatelliteScenes,
  acquireSceneAssets,
  getWaterBodyObservations,
  resolveApiUrl,
  WaterBody,
  NormalizedScene,
  SceneAcquisitionResponse,
  SatelliteObservation,
} from '../api';
import { FetchVisualDataModal } from '../components/FetchVisualDataModal';

const DEFAULT_TARGET_BANDS = ['B02', 'B03', 'B04', 'B08', 'B11', 'B12', 'SCL'];

export const SatellitePage: React.FC = () => {
  const [waterBodies, setWaterBodies] = useState<WaterBody[]>([]);
  const [selectedWbId, setSelectedWbId] = useState<string>('');

  // Mode: Visual Data Only (default ON) vs Advanced Full-Scene Spectral
  const [acquisitionMode, setAcquisitionMode] = useState<'visual' | 'spectral'>('visual');

  // Visual Data State
  const [isFetchModalOpen, setIsFetchModalOpen] = useState<boolean>(false);
  const [visualObservations, setVisualObservations] = useState<SatelliteObservation[]>([]);
  const [loadingObservations, setLoadingObservations] = useState<boolean>(false);

  // Spectral / Full Scene Search State
  const [startDate, setStartDate] = useState<string>('2024-01-01');
  const [endDate, setEndDate] = useState<string>('2024-04-01');
  const [maxCloud, setMaxCloud] = useState<number>(40);
  const [limit, setLimit] = useState<number>(5);

  const [isSearching, setIsSearching] = useState<boolean>(false);
  const [scenes, setScenes] = useState<NormalizedScene[]>([]);
  const [searchError, setSearchError] = useState<string | null>(null);

  // Spectral Scene Selection & Acquisition State
  const [selectedScene, setSelectedScene] = useState<NormalizedScene | null>(null);
  const [selectedBands, setSelectedBands] = useState<string[]>(DEFAULT_TARGET_BANDS);
  const [isAcquiring, setIsAcquiring] = useState<boolean>(false);
  const [acquisitionResult, setAcquisitionResult] = useState<SceneAcquisitionResponse | null>(null);
  const [acqError, setAcqError] = useState<string | null>(null);

  useEffect(() => {
    listWaterBodies(100, 0)
      .then((res) => {
        setWaterBodies(res.items);
        if (res.items.length > 0) {
          setSelectedWbId(res.items[0].id);
        }
      })
      .catch(() => {});
  }, []);

  // Fetch visual observations whenever active water body changes
  useEffect(() => {
    if (!selectedWbId) return;
    setLoadingObservations(true);
    getWaterBodyObservations(selectedWbId)
      .then((obs) => {
        setVisualObservations(obs);
      })
      .catch((err) => {
        console.error('Failed to load observations:', err);
      })
      .finally(() => {
        setLoadingObservations(false);
      });
  }, [selectedWbId]);

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedWbId) return;

    setIsSearching(true);
    setSearchError(null);
    setScenes([]);
    setSelectedScene(null);
    setAcquisitionResult(null);
    setAcqError(null);

    try {
      const sDate = startDate ? `${startDate}T00:00:00Z` : undefined;
      const eDate = endDate ? `${endDate}T23:59:59Z` : undefined;

      const resp = await searchSatelliteScenes(
        selectedWbId,
        sDate,
        eDate,
        maxCloud,
        limit
      );
      setScenes(resp.results);
      if (resp.results.length === 0) {
        setSearchError('No Sentinel-2 L2A scenes found matching spatial & cloud cover filters.');
      }
    } catch (err: unknown) {
      if (err instanceof Error) {
        setSearchError(err.message);
      } else {
        setSearchError('Error querying satellite STAC provider.');
      }
    } finally {
      setIsSearching(false);
    }
  };

  const toggleBand = (band: string) => {
    setSelectedBands((prev) =>
      prev.includes(band) ? prev.filter((b) => b !== band) : [...prev, band]
    );
  };

  const handleAcquire = async () => {
    if (!selectedScene || selectedBands.length === 0) return;

    setIsAcquiring(true);
    setAcqError(null);
    setAcquisitionResult(null);

    try {
      const resp = await acquireSceneAssets(selectedScene.external_scene_id, selectedBands);
      setAcquisitionResult(resp);
    } catch (err: unknown) {
      if (err instanceof Error) {
        setAcqError(err.message);
      } else {
        setAcqError('Failed to acquire assets.');
      }
    } finally {
      setIsAcquiring(false);
    }
  };

  const activeWaterBody = waterBodies.find((w) => w.id === selectedWbId);

  return (
    <div style={styles.container}>
      {/* ── Mode Selection Header ────────────────────────────────────────── */}
      <section style={styles.modeCard}>
        <div style={styles.modeToggleRow}>
          <button
            type="button"
            style={{
              ...styles.modeTabBtn,
              ...(acquisitionMode === 'visual' ? styles.modeTabBtnActive : {}),
            }}
            onClick={() => setAcquisitionMode('visual')}
          >
            🛰 VISUAL DATA ONLY (DEFAULT / RECOMMENDED)
          </button>
          <button
            type="button"
            style={{
              ...styles.modeTabBtn,
              ...(acquisitionMode === 'spectral' ? styles.modeTabBtnSecondaryActive : {}),
            }}
            onClick={() => setAcquisitionMode('spectral')}
          >
            ⚙ ADVANCED FULL-SCENE SPECTRAL MODE
          </button>
        </div>

        {acquisitionMode === 'visual' ? (
          <div style={styles.visualModeExplainer}>
            <div style={styles.explainerIcon}>✨</div>
            <div>
              <strong>Water-Body Centric Visual Observation Mode</strong>
              <p style={styles.explainerText}>
                Retrieves targeted Sentinel-2 natural color visual observations clipped directly to the water-body boundary.
                Uses high-speed remote windowed reads without downloading 100MB+ full GeoTIFF scenes or heavy unused spectral bands.
              </p>
            </div>
          </div>
        ) : (
          <div style={styles.spectralModeExplainer}>
            <div style={styles.explainerIcon}>⚠</div>
            <div>
              <strong>Advanced Multi-Band Heavy Tile Mode</strong>
              <p style={styles.explainerText}>
                Downloads complete 100km Sentinel-2 tile bands (B02–B12, SCL ~700MB per scene) directly to local disk for experimental spectral index modeling. For monitoring maps and temporal analysis, use <strong>Visual Data Only</strong>.
              </p>
            </div>
          </div>
        )}
      </section>

      {/* ── PRIMARY MODE: VISUAL DATA ONLY ───────────────────────────────── */}
      {acquisitionMode === 'visual' && (
        <section style={styles.card}>
          <div style={styles.header}>
            <h2 style={styles.title}>VISUAL SATELLITE OBSERVATIONS WORKBENCH</h2>
            <div style={styles.providerBadge}>
              SENTINEL-2 RGB • REMOTE COG WINDOWED ACCESS
            </div>
          </div>

          {/* Water body selector & Action */}
          <div style={styles.visualControlGrid}>
            <div style={{ flex: 1 }}>
              <label style={styles.label}>TARGET WATER BODY</label>
              <select
                value={selectedWbId}
                onChange={(e) => setSelectedWbId(e.target.value)}
                style={styles.select}
                disabled={waterBodies.length === 0}
              >
                {waterBodies.map((wb) => (
                  <option key={wb.id} value={wb.id}>
                    {wb.name} ({wb.country || 'Global'} - {wb.source})
                  </option>
                ))}
                {waterBodies.length === 0 && (
                  <option value="">No water bodies in catalog (Import one first)</option>
                )}
              </select>
            </div>

            {activeWaterBody && (
              <div style={{ display: 'flex', alignItems: 'flex-end' }}>
                <button
                  type="button"
                  style={styles.btnFetchVisual}
                  onClick={() => setIsFetchModalOpen(true)}
                >
                  + SEARCH & FETCH VISUAL DATA
                </button>
              </div>
            )}
          </div>

          {activeWaterBody && (
            <div style={styles.wbInfoBanner}>
              <span>
                <strong>Target AOI:</strong> {activeWaterBody.name} ({activeWaterBody.area_sq_km ? `${activeWaterBody.area_sq_km.toFixed(2)} km²` : 'Polygon AOI'})
              </span>
              <span>
                <strong>Coordinates:</strong> {activeWaterBody.centroid_lat?.toFixed(4)}, {activeWaterBody.centroid_lon?.toFixed(4)}
              </span>
              <span>
                <strong>Cloud Filter:</strong> ≤ 40% default (with user override)
              </span>
              <span>
                <strong>Download Size:</strong> &lt; 1 MB / observation
              </span>
            </div>
          )}

          {/* Already Present Observations Gallery */}
          <div style={{ marginTop: '1.25rem' }}>
            <div style={styles.obsListHeader}>
              <h3 style={styles.obsListTitle}>
                Acquired Visual Observations for {activeWaterBody?.name || 'Selected Target'} ({visualObservations.length})
              </h3>
              {visualObservations.length > 0 && (
                <a
                  href="/analysis"
                  style={styles.analysisLink}
                  onClick={(e) => {
                    e.preventDefault();
                    window.location.hash = '#/analysis';
                  }}
                >
                  Open in Temporal Analysis →
                </a>
              )}
            </div>

            {loadingObservations ? (
              <div style={styles.emptyNotice}>Loading acquired observations...</div>
            ) : visualObservations.length === 0 ? (
              <div style={styles.emptyNotice}>
                No visual observations have been fetched for this water body yet.
                Click <strong>&ldquo;+ SEARCH & FETCH VISUAL DATA&rdquo;</strong> to inspect available dates and acquire high-resolution imagery.
              </div>
            ) : (
              <div style={styles.obsGrid}>
                {visualObservations.map((obs) => {
                  const cloud = obs.cloud_cover_percent != null ? obs.cloud_cover_percent : 0;
                  const label = cloud <= 10 ? 'VERY CLEAR' : cloud <= 25 ? 'CLEAR' : cloud <= 40 ? 'ACCEPTABLE' : 'HIGH CLOUD';

                  return (
                    <div key={obs.id} style={styles.obsCard}>
                      <div style={styles.obsThumbWrapper}>
                        <img
                          src={resolveApiUrl(obs.image_url || `/api/v1/water-bodies/${obs.water_body_id}/observations/${obs.id}/image`)}
                          alt={obs.sensing_date}
                          style={styles.obsImg}
                          loading="lazy"
                        />
                        <div style={styles.obsDateBadge}>
                          {new Date(obs.sensing_date).toISOString().split('T')[0]}
                        </div>
                      </div>
                      <div style={styles.obsCardMeta}>
                        <div style={styles.obsMetaRow}>
                          <span>Cloud Cover:</span>
                          <strong>{obs.cloud_cover_percent != null ? `${obs.cloud_cover_percent.toFixed(1)}%` : 'N/A'}</strong>
                        </div>
                        <div style={styles.obsMetaRow}>
                          <span>Quality:</span>
                          <span
                            style={{
                              ...styles.qualityPill,
                              backgroundColor: label === 'VERY CLEAR' ? '#ecfdf5' : label === 'CLEAR' ? '#eff6ff' : label === 'ACCEPTABLE' ? '#fffbeb' : '#fef2f2',
                              color: label === 'VERY CLEAR' ? '#065f46' : label === 'CLEAR' ? '#1e40af' : label === 'ACCEPTABLE' ? '#92400e' : '#991b1b',
                            }}
                          >
                            {label}
                          </span>
                        </div>
                        <div style={styles.obsCardFooter}>
                          <span>Sentinel-2 RGB</span>
                          <span style={{ color: '#059669', fontWeight: 600 }}>✓ Ready</span>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </section>
      )}

      {/* ── SECONDARY MODE: ADVANCED FULL-SCENE SPECTRAL ─────────────────── */}
      {acquisitionMode === 'spectral' && (
        <>
          <section style={styles.card}>
            <div style={styles.header}>
              <h2 style={styles.title}>SENTINEL-2 FULL-SCENE DISCOVERY (ADVANCED)</h2>
              <div style={styles.providerBadge}>
                PROVIDER: EARTH SEARCH / AWS (FULL BANDS)
              </div>
            </div>

            <p style={styles.desc}>
              Search full Sentinel-2 L2A surface reflectance tiles (100km × 100km). This advanced workflow downloads raw GeoTIFF tiles to local disk for spectral index computation.
            </p>

            <form onSubmit={handleSearch} style={styles.formGrid}>
              <div>
                <label style={styles.label}>TARGET WATER BODY</label>
                <select
                  value={selectedWbId}
                  onChange={(e) => setSelectedWbId(e.target.value)}
                  style={styles.select}
                  disabled={isSearching || waterBodies.length === 0}
                >
                  {waterBodies.map((wb) => (
                    <option key={wb.id} value={wb.id}>
                      {wb.name} ({wb.country || 'Global'} - {wb.source})
                    </option>
                  ))}
                  {waterBodies.length === 0 && (
                    <option value="">No water bodies in catalog (Import one first)</option>
                  )}
                </select>
              </div>

              <div>
                <label style={styles.label}>START DATE</label>
                <input
                  type="date"
                  value={startDate}
                  onChange={(e) => setStartDate(e.target.value)}
                  style={styles.input}
                  disabled={isSearching}
                />
              </div>

              <div>
                <label style={styles.label}>END DATE</label>
                <input
                  type="date"
                  value={endDate}
                  onChange={(e) => setEndDate(e.target.value)}
                  style={styles.input}
                  disabled={isSearching}
                />
              </div>

              <div>
                <label style={styles.label}>MAX CLOUD COVER (%)</label>
                <input
                  type="number"
                  min={0}
                  max={100}
                  value={maxCloud}
                  onChange={(e) => setMaxCloud(Number(e.target.value))}
                  style={styles.input}
                  disabled={isSearching}
                />
              </div>

              <div>
                <label style={styles.label}>LIMIT</label>
                <select
                  value={limit}
                  onChange={(e) => setLimit(Number(e.target.value))}
                  style={styles.select}
                  disabled={isSearching}
                >
                  <option value={5}>Top 5</option>
                  <option value={10}>Top 10</option>
                  <option value={20}>Top 20</option>
                </select>
              </div>

              <div style={{ display: 'flex', alignItems: 'flex-end' }}>
                <button
                  type="submit"
                  style={styles.btnPrimary}
                  disabled={isSearching || !selectedWbId}
                >
                  {isSearching ? 'SEARCHING STAC...' : 'SEARCH SCENES'}
                </button>
              </div>
            </form>

            {searchError && <div style={styles.errorBanner}>{searchError}</div>}
          </section>

          {/* STAC Results Table */}
          {scenes.length > 0 && (
            <section style={styles.card}>
              <div style={styles.header}>
                <h3 style={styles.title}>
                  DISCOVERED SENTINEL-2 SCENES ({scenes.length} CANDIDATES - RANKED)
                </h3>
              </div>

              <div style={styles.tableWrapper}>
                <table style={styles.table}>
                  <thead>
                    <tr>
                      <th style={styles.th}>RANK SCORE</th>
                      <th style={styles.th}>SENSING DATE</th>
                      <th style={styles.th}>CLOUD COVER</th>
                      <th style={styles.th}>PROCESSING</th>
                      <th style={styles.th}>SCENE IDENTIFIER</th>
                      <th style={styles.th}>AVAILABLE ASSETS</th>
                      <th style={styles.th}>ACTION</th>
                    </tr>
                  </thead>
                  <tbody>
                    {scenes.map((scene) => {
                      const isSelected = selectedScene?.external_scene_id === scene.external_scene_id;
                      const assetKeys = Object.keys(scene.assets);

                      return (
                        <tr
                          key={scene.external_scene_id}
                          style={{
                            backgroundColor: isSelected ? 'var(--color-primary-subtle)' : 'transparent',
                          }}
                        >
                          <td style={styles.tdBold}>
                            <span style={styles.scorePill}>{scene.score ?? '-'}</span>
                          </td>
                          <td style={styles.tdMono}>
                            {new Date(scene.sensing_start).toLocaleDateString()} {new Date(scene.sensing_start).toLocaleTimeString()}
                          </td>
                          <td style={styles.td}>
                            <span
                              style={{
                                ...styles.cloudPill,
                                color: (scene.cloud_cover_percent || 0) < 15 ? 'var(--color-primary-dark)' : 'var(--color-accent)',
                              }}
                            >
                              {scene.cloud_cover_percent != null ? `${scene.cloud_cover_percent.toFixed(1)}%` : '-'}
                            </span>
                          </td>
                          <td style={styles.tdMono}>{scene.processing_level || 'L2A'}</td>
                          <td style={styles.tdMono}>{scene.external_scene_id}</td>
                          <td style={styles.td}>
                            <span style={styles.assetCountPill}>
                              {assetKeys.filter((k) => DEFAULT_TARGET_BANDS.includes(k)).length} Core Bands / {assetKeys.length} Total
                            </span>
                          </td>
                          <td style={styles.td}>
                            <button
                              type="button"
                              style={{
                                ...styles.btnSelect,
                                backgroundColor: isSelected ? 'var(--color-primary)' : 'var(--color-surface-subtle)',
                                color: isSelected ? '#ffffff' : 'var(--color-text-primary)',
                              }}
                              onClick={() => {
                                setSelectedScene(scene);
                                setAcquisitionResult(null);
                                setAcqError(null);
                              }}
                            >
                              {isSelected ? 'SELECTED' : 'INSPECT & ACQUIRE'}
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {/* Asset Selection & Acquisition Action Panel */}
          {selectedScene && (
            <section style={styles.acqPanel}>
              <div style={styles.header}>
                <h3 style={styles.title}>
                  ACQUISITION INSPECTOR: {selectedScene.external_scene_id}
                </h3>
                <button style={styles.closeBtn} onClick={() => setSelectedScene(null)}>
                  CLOSE
                </button>
              </div>

              <div style={styles.sceneMetaRow}>
                <div>
                  <strong>Collection:</strong> {selectedScene.collection}
                </div>
                <div>
                  <strong>Cloud Cover:</strong> {selectedScene.cloud_cover_percent?.toFixed(1)}%
                </div>
                <div>
                  <strong>Date:</strong> {new Date(selectedScene.sensing_start).toISOString()}
                </div>
              </div>

              <div style={{ marginTop: '0.75rem' }}>
                <label style={styles.label}>SELECT SPECTRAL ASSETS TO ACQUIRE LOCALLY:</label>
                <div style={styles.bandCheckboxGroup}>
                  {['B02', 'B03', 'B04', 'B08', 'B11', 'B12', 'SCL', 'thumbnail'].map((bKey) => {
                    const isAvailable = Boolean(selectedScene.assets[bKey]);
                    const isChecked = selectedBands.includes(bKey);

                    return (
                      <label
                        key={bKey}
                        style={{
                          ...styles.bandLabel,
                          opacity: isAvailable ? 1 : 0.4,
                          borderColor: isChecked ? 'var(--color-primary)' : 'var(--border-color)',
                          backgroundColor: isChecked ? 'var(--color-primary-subtle)' : 'var(--color-surface)',
                        }}
                      >
                        <input
                          type="checkbox"
                          checked={isChecked}
                          disabled={!isAvailable || isAcquiring}
                          onChange={() => toggleBand(bKey)}
                        />
                        <span>{bKey}</span>
                        <span style={styles.bandHint}>
                          {bKey === 'B02' && '(Blue 10m)'}
                          {bKey === 'B03' && '(Green 10m)'}
                          {bKey === 'B04' && '(Red 10m)'}
                          {bKey === 'B08' && '(NIR 10m)'}
                          {bKey === 'B11' && '(SWIR1 20m)'}
                          {bKey === 'B12' && '(SWIR2 20m)'}
                          {bKey === 'SCL' && '(Scene Class)'}
                          {bKey === 'thumbnail' && '(RGB Jpeg)'}
                        </span>
                      </label>
                    );
                  })}
                </div>
              </div>

              <div style={{ marginTop: '1rem', display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
                <button
                  type="button"
                  style={styles.btnAcquire}
                  disabled={isAcquiring || selectedBands.length === 0}
                  onClick={handleAcquire}
                >
                  {isAcquiring ? 'STREAMING ASSETS (ATOMIC)...' : `ACQUIRE ${selectedBands.length} ASSETS`}
                </button>
                <span style={{ fontSize: '0.75rem', color: 'var(--color-text-secondary)' }}>
                  Target storage path: <code style={styles.code}>data/scenes/{selectedScene.external_scene_id.substring(0, 16)}.../assets/</code>
                </span>
              </div>

              {acqError && <div style={styles.errorBanner}>{acqError}</div>}

              {acquisitionResult && (
                <div style={styles.acqResultCard}>
                  <div style={styles.acqResultHeader}>
                    <strong>ACQUISITION STATUS:</strong>{' '}
                    <span style={styles.statusSuccess}>
                      {acquisitionResult.status.toUpperCase()} ({acquisitionResult.downloaded_assets} Downloaded, {acquisitionResult.already_present_assets} Cached, {acquisitionResult.failed_assets} Failed)
                    </span>
                  </div>

                  <div style={styles.tableWrapper}>
                    <table style={styles.table}>
                      <thead>
                        <tr>
                          <th style={styles.th}>ASSET</th>
                          <th style={styles.th}>STATUS</th>
                          <th style={styles.th}>SIZE</th>
                          <th style={styles.th}>SHA256 CHECKSUM</th>
                          <th style={styles.th}>LOCAL PATH</th>
                        </tr>
                      </thead>
                      <tbody>
                        {acquisitionResult.assets.map((a) => (
                          <tr key={a.asset_key}>
                            <td style={styles.tdBold}>{a.asset_key}</td>
                            <td style={styles.td}>
                              <span
                                style={{
                                  ...styles.assetStatusPill,
                                  backgroundColor: a.status === 'downloaded' ? 'var(--color-primary-subtle)' : a.status === 'already_present' ? '#f0fdf4' : '#fef2f2',
                                  color: a.status === 'failed' ? 'var(--color-status-offline)' : 'var(--color-primary-dark)',
                                }}
                              >
                                {a.status.toUpperCase()}
                              </span>
                            </td>
                            <td style={styles.tdMono}>
                              {a.size_bytes != null ? `${(a.size_bytes / (1024 * 1024)).toFixed(2)} MB` : '-'}
                            </td>
                            <td style={styles.tdMono}>
                              {a.sha256 ? `${a.sha256.substring(0, 16)}...` : '-'}
                            </td>
                            <td style={styles.tdMono}>{a.local_path || '-'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </section>
          )}
        </>
      )}

      {/* Fetch Visual Data Modal */}
      {activeWaterBody && (
        <FetchVisualDataModal
          waterBody={activeWaterBody}
          isOpen={isFetchModalOpen}
          onClose={() => {
            setIsFetchModalOpen(false);
            // Refresh visual observations list
            getWaterBodyObservations(activeWaterBody.id).then(setVisualObservations).catch(() => {});
          }}
          onNavigateToAnalysis={(wbId) => {
            localStorage.setItem('jalnetra_selected_wb_id', wbId);
            window.location.hash = '#/analysis';
          }}
        />
      )}
    </div>
  );
};

const styles: Record<string, React.CSSProperties> = {
  container: {
    display: 'flex',
    flexDirection: 'column',
    gap: '1.25rem',
  },
  modeCard: {
    backgroundColor: '#ffffff',
    border: '1px solid var(--border-color)',
    borderRadius: '4px',
    padding: '0.9rem 1.25rem',
    display: 'flex',
    flexDirection: 'column',
    gap: '0.75rem',
  },
  modeToggleRow: {
    display: 'flex',
    gap: '0.75rem',
  },
  modeTabBtn: {
    flex: 1,
    padding: '0.65rem 1rem',
    border: '1px solid #cbd5e1',
    backgroundColor: '#f8fafc',
    borderRadius: '4px',
    fontSize: '0.78rem',
    fontWeight: 700,
    color: '#475569',
    cursor: 'pointer',
    letterSpacing: '0.03em',
    textAlign: 'center',
    transition: 'all 0.2s ease',
  },
  modeTabBtnActive: {
    backgroundColor: '#0284c7',
    borderColor: '#0284c7',
    color: '#ffffff',
    boxShadow: '0 2px 4px rgba(2, 132, 199, 0.2)',
  },
  modeTabBtnSecondaryActive: {
    backgroundColor: '#334155',
    borderColor: '#334155',
    color: '#ffffff',
    boxShadow: '0 2px 4px rgba(51, 65, 85, 0.2)',
  },
  visualModeExplainer: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.75rem',
    backgroundColor: '#f0fdf4',
    border: '1px solid #bbf7d0',
    padding: '0.65rem 0.85rem',
    borderRadius: '3px',
    color: '#166534',
    fontSize: '0.75rem',
  },
  spectralModeExplainer: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.75rem',
    backgroundColor: '#fffbeb',
    border: '1px solid #fde68a',
    padding: '0.65rem 0.85rem',
    borderRadius: '3px',
    color: '#92400e',
    fontSize: '0.75rem',
  },
  explainerIcon: {
    fontSize: '1.25rem',
  },
  explainerText: {
    margin: '0.2rem 0 0',
    lineHeight: 1.35,
    fontSize: '0.72rem',
  },
  card: {
    backgroundColor: 'var(--color-surface)',
    border: '1px solid var(--border-color)',
    borderRadius: '4px',
    padding: '1.25rem',
  },
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: '0.75rem',
  },
  title: {
    fontSize: '0.875rem',
    fontWeight: 700,
    letterSpacing: '0.05em',
    color: 'var(--color-text-primary)',
    margin: 0,
  },
  providerBadge: {
    fontSize: '0.6875rem',
    fontWeight: 600,
    backgroundColor: 'var(--color-surface-subtle)',
    border: '1px solid var(--border-color)',
    padding: '0.2rem 0.5rem',
    borderRadius: '2px',
    color: 'var(--color-text-secondary)',
  },
  desc: {
    fontSize: '0.8125rem',
    color: 'var(--color-text-secondary)',
    lineHeight: 1.4,
    marginBottom: '1rem',
  },
  visualControlGrid: {
    display: 'flex',
    gap: '1rem',
    alignItems: 'flex-end',
    marginBottom: '0.75rem',
  },
  btnFetchVisual: {
    backgroundColor: '#0284c7',
    color: '#ffffff',
    border: 'none',
    padding: '0.55rem 1.15rem',
    borderRadius: '3px',
    fontSize: '0.78rem',
    fontWeight: 700,
    cursor: 'pointer',
    letterSpacing: '0.02em',
  },
  wbInfoBanner: {
    display: 'flex',
    gap: '1.25rem',
    flexWrap: 'wrap',
    fontSize: '0.72rem',
    backgroundColor: '#f8fafc',
    border: '1px solid #e2e8f0',
    padding: '0.5rem 0.75rem',
    borderRadius: '3px',
    color: '#334155',
  },
  obsListHeader: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: '0.75rem',
  },
  obsListTitle: {
    margin: 0,
    fontSize: '0.82rem',
    fontWeight: 700,
    color: '#1e293b',
  },
  analysisLink: {
    fontSize: '0.75rem',
    fontWeight: 700,
    color: '#0284c7',
    textDecoration: 'none',
  },
  obsGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))',
    gap: '0.75rem',
  },
  obsCard: {
    backgroundColor: '#ffffff',
    border: '1px solid #e2e8f0',
    borderRadius: '4px',
    overflow: 'hidden',
    display: 'flex',
    flexDirection: 'column',
  },
  obsThumbWrapper: {
    position: 'relative',
    height: '140px',
    backgroundColor: '#0f172a',
  },
  obsImg: {
    width: '100%',
    height: '100%',
    objectFit: 'cover',
    display: 'block',
  },
  obsDateBadge: {
    position: 'absolute',
    bottom: '6px',
    left: '6px',
    backgroundColor: 'rgba(15, 23, 42, 0.85)',
    color: '#ffffff',
    fontSize: '0.65rem',
    fontWeight: 700,
    padding: '0.15rem 0.4rem',
    borderRadius: '2px',
  },
  obsCardMeta: {
    padding: '0.6rem 0.75rem',
    display: 'flex',
    flexDirection: 'column',
    gap: '0.35rem',
    fontSize: '0.72rem',
  },
  obsMetaRow: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    color: '#475569',
  },
  qualityPill: {
    fontSize: '0.62rem',
    fontWeight: 700,
    padding: '0.1rem 0.35rem',
    borderRadius: '2px',
  },
  obsCardFooter: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    fontSize: '0.68rem',
    color: '#94a3b8',
    borderTop: '1px solid #f1f5f9',
    paddingTop: '0.35rem',
    marginTop: '0.2rem',
  },
  emptyNotice: {
    padding: '2.5rem 1rem',
    textAlign: 'center',
    color: '#64748b',
    fontSize: '0.8rem',
    backgroundColor: '#f8fafc',
    borderRadius: '4px',
    border: '1px dashed #cbd5e1',
  },
  formGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
    gap: '1rem',
  },
  label: {
    display: 'block',
    fontSize: '0.6875rem',
    fontWeight: 700,
    letterSpacing: '0.05em',
    marginBottom: '0.375rem',
    color: 'var(--color-text-secondary)',
  },
  select: {
    width: '100%',
    padding: '0.5rem',
    fontSize: '0.8125rem',
    border: '1px solid var(--border-color)',
    borderRadius: '2px',
    backgroundColor: 'var(--color-surface)',
    color: 'var(--color-text-primary)',
    outline: 'none',
  },
  input: {
    width: '100%',
    padding: '0.5rem',
    fontSize: '0.8125rem',
    border: '1px solid var(--border-color)',
    borderRadius: '2px',
    backgroundColor: 'var(--color-surface)',
    color: 'var(--color-text-primary)',
    outline: 'none',
  },
  btnPrimary: {
    width: '100%',
    padding: '0.55rem',
    backgroundColor: 'var(--color-primary)',
    color: '#ffffff',
    border: 'none',
    borderRadius: '2px',
    fontSize: '0.75rem',
    fontWeight: 700,
    letterSpacing: '0.05em',
    cursor: 'pointer',
  },
  tableWrapper: {
    overflowX: 'auto',
  },
  table: {
    width: '100%',
    borderCollapse: 'collapse',
    fontSize: '0.75rem',
  },
  th: {
    textAlign: 'left',
    padding: '0.5rem',
    borderBottom: '2px solid var(--border-color)',
    color: 'var(--color-text-secondary)',
    fontWeight: 700,
    letterSpacing: '0.05em',
  },
  td: {
    padding: '0.5rem',
    borderBottom: '1px solid var(--border-color)',
    color: 'var(--color-text-primary)',
  },
  tdBold: {
    padding: '0.5rem',
    borderBottom: '1px solid var(--border-color)',
    color: 'var(--color-text-primary)',
    fontWeight: 700,
  },
  tdMono: {
    padding: '0.5rem',
    borderBottom: '1px solid var(--border-color)',
    fontFamily: 'monospace',
    color: 'var(--color-text-primary)',
  },
  scorePill: {
    padding: '0.15rem 0.35rem',
    borderRadius: '2px',
    backgroundColor: 'var(--color-surface-subtle)',
    color: 'var(--color-text-primary)',
  },
  cloudPill: {
    fontWeight: 700,
  },
  assetCountPill: {
    fontSize: '0.6875rem',
    color: 'var(--color-text-secondary)',
  },
  btnSelect: {
    padding: '0.25rem 0.5rem',
    fontSize: '0.6875rem',
    fontWeight: 700,
    border: '1px solid var(--border-color)',
    borderRadius: '2px',
    cursor: 'pointer',
  },
  acqPanel: {
    backgroundColor: 'var(--color-surface)',
    border: '1px solid var(--border-color)',
    borderRadius: '4px',
    padding: '1.25rem',
  },
  closeBtn: {
    background: 'none',
    border: 'none',
    color: 'var(--color-text-secondary)',
    cursor: 'pointer',
    fontSize: '0.6875rem',
    fontWeight: 700,
  },
  sceneMetaRow: {
    display: 'flex',
    gap: '2rem',
    fontSize: '0.8125rem',
    color: 'var(--color-text-primary)',
    paddingBottom: '0.75rem',
    borderBottom: '1px solid var(--border-color)',
  },
  bandCheckboxGroup: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: '0.5rem',
    marginTop: '0.375rem',
  },
  bandLabel: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.375rem',
    padding: '0.35rem 0.6rem',
    border: '1px solid var(--border-color)',
    borderRadius: '2px',
    fontSize: '0.75rem',
    fontWeight: 600,
    cursor: 'pointer',
  },
  bandHint: {
    fontSize: '0.6875rem',
    color: 'var(--color-text-secondary)',
    fontWeight: 400,
  },
  btnAcquire: {
    padding: '0.5rem 1rem',
    backgroundColor: 'var(--color-primary)',
    color: '#ffffff',
    border: 'none',
    borderRadius: '2px',
    fontSize: '0.75rem',
    fontWeight: 700,
    cursor: 'pointer',
  },
  code: {
    fontFamily: 'monospace',
    backgroundColor: 'var(--color-surface-subtle)',
    padding: '0.1rem 0.3rem',
    borderRadius: '2px',
  },
  acqResultCard: {
    marginTop: '1.25rem',
    borderTop: '1px solid var(--border-color)',
    paddingTop: '1rem',
  },
  acqResultHeader: {
    fontSize: '0.8125rem',
    marginBottom: '0.5rem',
  },
  statusSuccess: {
    color: 'var(--color-status-online)',
    fontWeight: 700,
  },
  assetStatusPill: {
    padding: '0.15rem 0.35rem',
    borderRadius: '2px',
    fontSize: '0.6875rem',
    fontWeight: 700,
  },
  errorBanner: {
    marginTop: '0.75rem',
    padding: '0.5rem 0.75rem',
    backgroundColor: '#fef2f2',
    border: '1px solid #fecaca',
    borderRadius: '2px',
    color: 'var(--color-status-offline)',
    fontSize: '0.75rem',
  },
};
