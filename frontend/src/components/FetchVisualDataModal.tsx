import React, { useState, useEffect, useRef } from 'react';
import {
  WaterBody,
  getAvailableVisualObservations,
  fetchSelectedVisualData,
  getVisualDataJobStatus,
  AvailableObservationItem,
  AvailableObservationsResponse,
  VisualAcquisitionJobResponse,
} from '../api/client';

interface FetchVisualDataModalProps {
  waterBody: WaterBody;
  isOpen: boolean;
  onClose: () => void;
  onNavigateToAnalysis?: (waterBodyId: string) => void;
}

type ModalStep = 'search' | 'select' | 'acquiring' | 'finished';

function isValidObservationId(id: unknown): id is string {
  return typeof id === 'string' && id.trim().length > 0;
}

function getObservationId(item: AvailableObservationItem): string {
  const candidate = item.observation_id || item.scene_id || item.id;
  if (isValidObservationId(candidate)) {
    return candidate.trim();
  }
  console.error('[Visual Acquisition] Observation item is missing a valid identifier:', item);
  return '';
}

export const FetchVisualDataModal: React.FC<FetchVisualDataModalProps> = ({
  waterBody,
  isOpen,
  onClose,
  onNavigateToAnalysis,
}) => {
  // Default dates: last 12 months
  const todayStr = new Date().toISOString().split('T')[0];
  const oneYearAgo = new Date(Date.now() - 365 * 24 * 3600 * 1000).toISOString().split('T')[0];

  const [step, setStep] = useState<ModalStep>('search');
  const [fromDate, setFromDate] = useState<string>(oneYearAgo);
  const [toDate, setToDate] = useState<string>(todayStr);
  const [maxCloud, setMaxCloud] = useState<number>(40);
  const [includeHighCloud, setIncludeHighCloud] = useState<boolean>(false);
  const [sortBy, setSortBy] = useState<'newest' | 'oldest' | 'lowest_cloud'>('newest');

  // Search results
  const [isSearching, setIsSearching] = useState<boolean>(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [availableData, setAvailableData] = useState<AvailableObservationsResponse | null>(null);

  // Selection state: strictly contains only non-empty string IDs
  const [selectedObservationIds, setSelectedObservationIds] = useState<string[]>([]);

  // Job progress
  const [jobStatus, setJobStatus] = useState<VisualAcquisitionJobResponse | null>(null);
  const [jobError, setJobError] = useState<string | null>(null);

  const pollIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Reset state when opening/closing
  useEffect(() => {
    if (!isOpen) {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
      }
      setStep('search');
      setSearchError(null);
      setJobError(null);
      setSelectedObservationIds([]);
      setAvailableData(null);
      setJobStatus(null);
    }
  }, [isOpen]);

  // Clean up polling on unmount
  useEffect(() => {
    return () => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
      }
    };
  }, []);

  if (!isOpen) return null;

  // Step 1: Perform metadata search
  const handleSearchAvailable = async () => {
    setIsSearching(true);
    setSearchError(null);
    try {
      const data = await getAvailableVisualObservations(waterBody.id, {
        from_date: fromDate,
        to_date: toDate,
        max_cloud: maxCloud,
        include_high_cloud: includeHighCloud,
        sort: sortBy,
      });
      setAvailableData(data);

      // Pre-select up to 3 clear observations that have valid IDs and are not yet acquired
      const initialIds: string[] = [];
      for (const item of data.items) {
        const id = getObservationId(item);
        if (
          id &&
          !item.is_already_available &&
          !item.already_acquired &&
          !item.is_high_cloud &&
          initialIds.length < 3
        ) {
          initialIds.push(id);
        }
      }
      setSelectedObservationIds(initialIds);
      setStep('select');
    } catch (err: any) {
      setSearchError(err.message || 'Failed to search available observations.');
    } finally {
      setIsSearching(false);
    }
  };

  // Deterministic toggle behavior for an observation ID
  const toggleObservation = (id: string) => {
    if (!isValidObservationId(id)) {
      console.error('[Visual Acquisition] Cannot toggle invalid observation ID:', id);
      return;
    }
    setSelectedObservationIds(prev => {
      if (prev.includes(id)) {
        return prev.filter(existingId => existingId !== id);
      }
      if (prev.length >= 20) {
        alert('Maximum 20 observations can be selected at a time.');
        return prev;
      }
      return [...prev, id];
    });
  };

  // Quick selection helpers
  const handleSelectClear = () => {
    if (!availableData) return;
    const ids: string[] = [];
    for (const it of availableData.items) {
      const id = getObservationId(it);
      if (!id) continue;
      if (it.quality_label === 'VERY CLEAR' || it.quality_label === 'CLEAR') {
        if (!ids.includes(id) && ids.length < 20) {
          ids.push(id);
        }
      }
    }
    setSelectedObservationIds(ids);
  };

  const handleSelectAll = () => {
    if (!availableData) return;
    const ids: string[] = [];
    for (const it of availableData.items) {
      const id = getObservationId(it);
      if (!id) continue;
      if (!ids.includes(id) && ids.length < 20) {
        ids.push(id);
      }
    }
    setSelectedObservationIds(ids);
  };

  const handleClearSelection = () => {
    setSelectedObservationIds([]);
  };

  // Step 2 -> 3: Dispatch fetch for selected observations
  const handleStartFetch = async () => {
    const validIds = selectedObservationIds.filter(isValidObservationId);

    if (validIds.length === 0) {
      alert('Please select at least one observation.');
      return;
    }
    if (validIds.length > 20) {
      alert('Maximum 20 observations can be selected at a time.');
      return;
    }

    const payload = {
      observation_ids: validIds,
    };

    console.log('[Visual Acquisition] selected observation IDs:', validIds);
    console.log('[Visual Acquisition] fetch payload:', payload);

    setJobError(null);
    setStep('acquiring');

    try {
      const job = await fetchSelectedVisualData(waterBody.id, payload);
      setJobStatus(job);

      // Start polling
      if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = setInterval(async () => {
        try {
          const status = await getVisualDataJobStatus(waterBody.id, job.job_id);
          setJobStatus(status);
          if (status.status === 'completed' || status.status === 'failed') {
            if (pollIntervalRef.current) {
              clearInterval(pollIntervalRef.current);
              pollIntervalRef.current = null;
            }
            setStep('finished');
          }
        } catch (pollErr: any) {
          console.error('Job polling error:', pollErr);
        }
      }, 750);
    } catch (err: any) {
      setJobError(err.message || 'Failed to dispatch visual acquisition job.');
      setStep('select');
    }
  };

  const getQualityBadgeStyle = (label: string) => {
    switch (label) {
      case 'VERY CLEAR':
        return { backgroundColor: '#ecfdf5', color: '#065f46', border: '1px solid #a7f3d0' };
      case 'CLEAR':
        return { backgroundColor: '#eff6ff', color: '#1e40af', border: '1px solid #bfdbfe' };
      case 'ACCEPTABLE':
        return { backgroundColor: '#fffbeb', color: '#92400e', border: '1px solid #fde68a' };
      case 'HIGH CLOUD':
      default:
        return { backgroundColor: '#fef2f2', color: '#991b1b', border: '1px solid #fecaca' };
    }
  };

  return (
    <div style={styles.overlay}>
      <div style={{ ...styles.modal, maxWidth: step === 'select' ? '750px' : '600px' }}>
        {/* Header */}
        <div style={styles.header}>
          <div>
            <div style={styles.kicker}>WATER-BODY CENTRIC VISUAL ACQUISITION</div>
            <h3 style={styles.title}>
              {step === 'search' && 'Search Available Satellite Data'}
              {step === 'select' && 'Select Observations to Acquire'}
              {step === 'acquiring' && 'Acquiring Visual Data...'}
              {step === 'finished' && 'Acquisition Summary'}
            </h3>
          </div>
          <button
            style={styles.closeBtn}
            onClick={onClose}
            disabled={step === 'acquiring'}
            title="Close"
          >
            ✕
          </button>
        </div>

        {/* Target Water Body Card */}
        <div style={styles.targetCard}>
          <div style={styles.targetRow}>
            <span style={styles.targetLabel}>TARGET:</span>
            <span style={styles.targetName}>{waterBody.name}</span>
          </div>
          <div style={styles.targetMetaGrid}>
            <div>
              <span style={styles.metaKey}>Location: </span>
              <span>{waterBody.city || waterBody.state_province || waterBody.country || 'Global'}</span>
            </div>
            <div>
              <span style={styles.metaKey}>Area: </span>
              <span>{waterBody.area_sq_km ? `${waterBody.area_sq_km.toFixed(2)} km²` : 'Polygon AOI'}</span>
            </div>
            <div>
              <span style={styles.metaKey}>AOI Crop: </span>
              <span style={{ color: '#0284c7' }}>Focused Boundary (10% padding)</span>
            </div>
            <div>
              <span style={styles.metaKey}>Acquisition Method: </span>
              <span style={{ color: '#059669', fontWeight: 600 }}>Remote COG Windowed Reads (Fast RGB)</span>
            </div>
          </div>
        </div>

        {/* Modal Body: Dynamic Step Content */}
        <div style={styles.body}>
          {/* STEP 1: SEARCH AVAILABLE DATES */}
          {step === 'search' && (
            <>
              <div style={styles.fieldGrid}>
                <div style={styles.fieldGroup}>
                  <label style={styles.label}>FROM DATE</label>
                  <input
                    type="date"
                    style={styles.input}
                    value={fromDate}
                    onChange={e => setFromDate(e.target.value)}
                    disabled={isSearching}
                  />
                </div>
                <div style={styles.fieldGroup}>
                  <label style={styles.label}>TO DATE</label>
                  <input
                    type="date"
                    style={styles.input}
                    value={toDate}
                    onChange={e => setToDate(e.target.value)}
                    disabled={isSearching}
                  />
                </div>
              </div>

              <div style={styles.fieldGrid}>
                <div style={styles.fieldGroup}>
                  <label style={styles.label}>MAX CLOUD COVER</label>
                  <div style={{ display: 'flex', gap: '0.4rem' }}>
                    {[10, 20, 30, 40].map(c => (
                      <button
                        key={c}
                        type="button"
                        style={{
                          ...styles.presetBtn,
                          ...(maxCloud === c ? styles.presetBtnActive : {}),
                        }}
                        onClick={() => setMaxCloud(c)}
                        disabled={isSearching}
                      >
                        ≤ {c}%
                      </button>
                    ))}
                  </div>
                </div>

                <div style={styles.fieldGroup}>
                  <label style={styles.label}>SORT BY</label>
                  <select
                    style={styles.select}
                    value={sortBy}
                    onChange={e => setSortBy(e.target.value as any)}
                    disabled={isSearching}
                  >
                    <option value="newest">Newest first</option>
                    <option value="oldest">Oldest first</option>
                    <option value="lowest_cloud">Lowest cloud cover</option>
                  </select>
                </div>
              </div>

              <div style={styles.checkboxRow}>
                <input
                  type="checkbox"
                  id="includeHighCloud"
                  checked={includeHighCloud}
                  onChange={e => setIncludeHighCloud(e.target.checked)}
                  disabled={isSearching}
                />
                <label htmlFor="includeHighCloud" style={styles.checkboxLabel}>
                  Include observations above {maxCloud}% cloud cover (tagged as HIGH CLOUD)
                </label>
              </div>

              <div style={styles.noteBox}>
                <strong>Fast Metadata Search:</strong> This query inspects the Sentinel-2 archive catalog for satellite passes over {waterBody.name}. No images are downloaded during this step.
              </div>

              {searchError && (
                <div style={styles.errorBox}>
                  <strong>Error:</strong> {searchError}
                </div>
              )}
            </>
          )}

          {/* STEP 2: SELECT OBSERVATIONS */}
          {step === 'select' && availableData && (
            <>
              <div style={styles.selectionTopBar}>
                <div style={styles.selectionSummary}>
                  Found <strong>{availableData.total_found}</strong> observations between {fromDate} and {toDate}
                </div>
                <div style={styles.quickButtonsRow}>
                  <button type="button" style={styles.tinyBtn} onClick={handleSelectClear}>
                    Select Clear (≤20)
                  </button>
                  <button type="button" style={styles.tinyBtn} onClick={handleSelectAll}>
                    Select All (≤20)
                  </button>
                  <button type="button" style={styles.tinyBtn} onClick={handleClearSelection}>
                    Deselect All
                  </button>
                  <button
                    type="button"
                    style={{ ...styles.tinyBtn, color: '#0284c7' }}
                    onClick={() => setStep('search')}
                  >
                    ✎ Adjust Dates
                  </button>
                </div>
              </div>

              {/* Table / List of Available Observations */}
              <div style={styles.tableContainer}>
                {availableData.items.length === 0 ? (
                  <div style={styles.emptyNotice}>
                    No satellite observations found matching your date range and cloud filter.
                  </div>
                ) : (
                  <table style={styles.table}>
                    <thead>
                      <tr style={styles.tableHeaderRow}>
                        <th style={{ width: '40px', textAlign: 'center' }}></th>
                        <th style={{ textAlign: 'left' }}>Date & Satellite</th>
                        <th style={{ textAlign: 'left' }}>Cloud Cover</th>
                        <th style={{ textAlign: 'left' }}>Visual Quality</th>
                        <th style={{ textAlign: 'right' }}>Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {availableData.items.map((item, idx) => {
                        const obsId = getObservationId(item);
                        const isChecked = Boolean(obsId && selectedObservationIds.includes(obsId));
                        const badgeStyle = getQualityBadgeStyle(item.quality_label);

                        return (
                          <tr
                            key={obsId || `row-${idx}`}
                            style={{
                              ...styles.tableRow,
                              backgroundColor: isChecked ? '#f0f9ff' : 'transparent',
                            }}
                            onClick={() => {
                              if (obsId) toggleObservation(obsId);
                            }}
                          >
                            <td style={{ textAlign: 'center' }}>
                              <input
                                type="checkbox"
                                checked={isChecked}
                                disabled={!obsId}
                                onChange={() => {
                                  if (obsId) toggleObservation(obsId);
                                }}
                                onClick={e => e.stopPropagation()}
                              />
                            </td>
                            <td style={styles.dateCell}>
                              <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                                <strong>{item.sensing_date_str}</strong>
                                {item.platform && (
                                  <span style={styles.platformBadge}>{item.platform}</span>
                                )}
                              </div>
                              <span style={styles.sceneIdSubtext}>{obsId}</span>
                            </td>
                            <td>
                              <div style={styles.cloudCell}>
                                <span>{item.cloud_cover_percent.toFixed(1)}%</span>
                                <div style={styles.cloudBarBg}>
                                  <div
                                    style={{
                                      ...styles.cloudBarFill,
                                      width: `${Math.min(100, item.cloud_cover_percent)}%`,
                                      backgroundColor: item.cloud_cover_percent <= 20 ? '#10b981' : item.cloud_cover_percent <= 40 ? '#f59e0b' : '#ef4444',
                                    }}
                                  />
                                </div>
                              </div>
                            </td>
                            <td>
                              <span style={{ ...styles.qualityBadge, ...badgeStyle }}>
                                {item.quality_label}
                              </span>
                            </td>
                            <td style={{ textAlign: 'right' }}>
                              {item.is_already_available || item.already_acquired ? (
                                <span style={styles.availableBadge}>✓ ALREADY AVAILABLE</span>
                              ) : (
                                <span style={styles.notFetchedBadge}>Not yet acquired</span>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                )}
              </div>

              {/* Selection Counter & Limit Alert */}
              <div style={styles.selectionFooterRow}>
                <div>
                  <span style={styles.counterText}>
                    Selected: <strong>{selectedObservationIds.length}</strong> / 20 observations
                  </span>
                  {selectedObservationIds.length > 20 && (
                    <span style={styles.limitWarning}>
                      Maximum 20 observations can be selected.
                    </span>
                  )}
                </div>
                <span style={styles.fastInfoText}>
                  Remote windowed read: ~2–5 sec per observation
                </span>
              </div>

              {jobError && (
                <div style={styles.errorBox}>
                  <strong>Error:</strong> {jobError}
                </div>
              )}
            </>
          )}

          {/* STEP 3: ACQUIRING PROGRESS */}
          {step === 'acquiring' && (
            <div style={styles.progressContainer}>
              {(() => {
                const total = jobStatus?.total || selectedObservationIds.length || 1;
                const completed = (jobStatus?.completed || 0) + (jobStatus?.reused || 0);
                const failed = jobStatus?.failed || 0;
                const processed = completed + failed;
                const currentIdx = jobStatus?.current_index || Math.min(processed + 1, total);
                const computedPct = Math.round((processed / total) * 100);
                const displayPercent = jobStatus?.status === 'completed'
                  ? 100
                  : Math.min(99, Math.max(jobStatus?.percent || 0, computedPct));

                return (
                  <>
                    <div style={styles.progressHeaderRow}>
                      <div style={styles.stagePill}>
                        STAGE: {jobStatus?.current_stage || 'ACQUIRING'}
                      </div>
                      <div style={styles.progressPercentage}>
                        {displayPercent}%
                      </div>
                    </div>

                    {/* Progress Bar */}
                    <div style={styles.progressBarBg}>
                      <div
                        style={{
                          ...styles.progressBarFill,
                          width: `${displayPercent}%`,
                          transition: 'width 0.3s ease-in-out',
                        }}
                      />
                    </div>

                    {/* Live Status Message */}
                    <div style={styles.liveMessage}>
                      {jobStatus?.details || jobStatus?.message || `Processing observation ${currentIdx} of ${total}...`}
                    </div>

                    {/* Counters */}
                    <div style={styles.jobStatsRow}>
                      <div style={styles.jobStatItem}>
                        <span style={styles.jobStatLabel}>TOTAL</span>
                        <span style={styles.jobStatVal}>{total}</span>
                      </div>
                      <div style={styles.jobStatItem}>
                        <span style={styles.jobStatLabel}>COMPLETED</span>
                        <span style={{ ...styles.jobStatVal, color: '#16a34a' }}>{completed}</span>
                      </div>
                      <div style={styles.jobStatItem}>
                        <span style={styles.jobStatLabel}>FAILED / UNUSABLE</span>
                        <span style={{ ...styles.jobStatVal, color: failed > 0 ? '#dc2626' : '#64748b' }}>
                          {failed}
                        </span>
                      </div>
                    </div>
                  </>
                );
              })()}

              <div style={styles.noteBox}>
                Fetching direct cropped AOIs for {waterBody.name} without downloading full 100MB Sentinel-2 scenes. Please do not refresh.
              </div>
            </div>
          )}

          {/* STEP 4: FINISHED / SUMMARY */}
          {step === 'finished' && jobStatus && (
            <div style={styles.finishedContainer}>
              <div style={styles.resultBox}>
                <div style={styles.resultTitle}>
                  {jobStatus.failed === 0
                    ? '✓ Visual Data Acquisition Complete'
                    : jobStatus.completed > 0
                    ? '⚠ Visual Data Acquisition Finished with Warnings'
                    : '✕ Acquisition Failed'}
                </div>
                <div style={styles.resultDetail}>{jobStatus.message}</div>
                <div style={styles.resultStatsRow}>
                  <span>Total Requested: <strong>{jobStatus.total}</strong></span>
                  <span>Successfully Saved: <strong>{jobStatus.completed}</strong></span>
                  <span>Unusable / Failed: <strong>{jobStatus.failed}</strong></span>
                </div>
              </div>

              {/* Unusable / Error List if any */}
              {jobStatus.errors && jobStatus.errors.length > 0 && (
                <div style={styles.unusableListBox}>
                  <div style={styles.unusableTitle}>Rejected / Unusable Observations:</div>
                  {jobStatus.errors.map((err, idx) => (
                    <div key={idx} style={styles.unusableItem}>
                      <span style={styles.unusableScene}>{err.observation_id}: </span>
                      <span style={styles.unusableReason}>{err.error}</span>
                    </div>
                  ))}
                  <div style={styles.unusableAdvice}>
                    Observations failing quality checks (excessive clouds, missing pixels, or sensor saturation) are discarded to maintain clean data.
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer Actions */}
        <div style={styles.footer}>
          {step === 'search' && (
            <>
              <button style={styles.cancelBtn} onClick={onClose} disabled={isSearching}>
                CANCEL
              </button>
              <button
                style={{
                  ...styles.submitBtn,
                  opacity: isSearching ? 0.7 : 1,
                  cursor: isSearching ? 'not-allowed' : 'pointer',
                }}
                onClick={handleSearchAvailable}
                disabled={isSearching}
              >
                {isSearching ? 'SEARCHING ARCHIVE...' : '🔍 SEARCH AVAILABLE DATA'}
              </button>
            </>
          )}

          {step === 'select' && (
            <>
              <button style={styles.cancelBtn} onClick={() => setStep('search')}>
                BACK
              </button>
              <button
                style={{
                  ...styles.submitBtn,
                  opacity: selectedObservationIds.length === 0 || selectedObservationIds.length > 20 ? 0.5 : 1,
                  cursor: selectedObservationIds.length === 0 || selectedObservationIds.length > 20 ? 'not-allowed' : 'pointer',
                }}
                onClick={handleStartFetch}
                disabled={selectedObservationIds.length === 0 || selectedObservationIds.length > 20}
              >
                {selectedObservationIds.length === 0
                  ? 'FETCH SELECTED VISUAL DATA'
                  : `FETCH ${selectedObservationIds.length} SELECTED VISUAL DATA`}
              </button>
            </>
          )}

          {step === 'acquiring' && (
            <div style={{ fontSize: '0.75rem', color: '#64748b', fontStyle: 'italic' }}>
              Acquisition running in background...
            </div>
          )}

          {step === 'finished' && (
            <>
              <button style={styles.cancelBtn} onClick={onClose}>
                CLOSE
              </button>
              {onNavigateToAnalysis && (
                <button
                  style={styles.analysisNavBtn}
                  onClick={() => {
                    onClose();
                    onNavigateToAnalysis(waterBody.id);
                  }}
                >
                  VIEW IN ANALYSIS PAGE →
                </button>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
};

const styles: Record<string, React.CSSProperties> = {
  overlay: {
    position: 'fixed',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: 'rgba(15, 23, 42, 0.65)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    zIndex: 9999,
    padding: '1rem',
  },
  modal: {
    backgroundColor: '#ffffff',
    width: '100%',
    borderRadius: '4px',
    boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.2), 0 10px 10px -5px rgba(0, 0, 0, 0.1)',
    overflow: 'hidden',
    display: 'flex',
    flexDirection: 'column',
    fontFamily: 'Inter, system-ui, sans-serif',
    maxHeight: '90vh',
  },
  header: {
    padding: '0.9rem 1.25rem',
    backgroundColor: '#f8fafc',
    borderBottom: '1px solid #e2e8f0',
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
  },
  kicker: {
    fontSize: '0.65rem',
    fontWeight: 700,
    letterSpacing: '0.06em',
    color: '#0284c7',
    textTransform: 'uppercase',
  },
  title: {
    margin: '0.2rem 0 0',
    fontSize: '1.1rem',
    fontWeight: 700,
    color: '#0f172a',
  },
  closeBtn: {
    background: 'none',
    border: 'none',
    fontSize: '1.1rem',
    color: '#64748b',
    cursor: 'pointer',
    padding: '0.2rem',
  },
  targetCard: {
    margin: '0.75rem 1.25rem 0',
    padding: '0.65rem 0.8rem',
    backgroundColor: '#f0fdf4',
    border: '1px solid #bbf7d0',
    borderRadius: '3px',
  },
  targetRow: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.5rem',
    marginBottom: '0.3rem',
  },
  targetLabel: {
    fontSize: '0.65rem',
    fontWeight: 700,
    color: '#166534',
    letterSpacing: '0.04em',
  },
  targetName: {
    fontSize: '0.95rem',
    fontWeight: 700,
    color: '#14532d',
  },
  targetMetaGrid: {
    display: 'grid',
    gridTemplateColumns: '1fr 1fr',
    gap: '0.25rem 0.75rem',
    fontSize: '0.72rem',
    color: '#334155',
  },
  metaKey: {
    color: '#64748b',
    fontWeight: 600,
  },
  body: {
    padding: '0.9rem 1.25rem',
    display: 'flex',
    flexDirection: 'column',
    gap: '0.8rem',
    overflowY: 'auto',
  },
  fieldGrid: {
    display: 'grid',
    gridTemplateColumns: '1fr 1fr',
    gap: '0.75rem',
  },
  fieldGroup: {
    display: 'flex',
    flexDirection: 'column',
    gap: '0.25rem',
  },
  label: {
    fontSize: '0.7rem',
    fontWeight: 700,
    color: '#334155',
    letterSpacing: '0.03em',
  },
  input: {
    padding: '0.45rem 0.6rem',
    border: '1px solid #cbd5e1',
    borderRadius: '3px',
    fontSize: '0.8rem',
    backgroundColor: '#ffffff',
    color: '#0f172a',
    outline: 'none',
  },
  select: {
    padding: '0.45rem 0.6rem',
    border: '1px solid #cbd5e1',
    borderRadius: '3px',
    fontSize: '0.8rem',
    backgroundColor: '#ffffff',
    color: '#0f172a',
    outline: 'none',
  },
  presetBtn: {
    flex: 1,
    padding: '0.45rem 0',
    backgroundColor: '#f1f5f9',
    border: '1px solid #cbd5e1',
    borderRadius: '3px',
    fontSize: '0.72rem',
    fontWeight: 600,
    color: '#334155',
    cursor: 'pointer',
  },
  presetBtnActive: {
    backgroundColor: '#0284c7',
    borderColor: '#0284c7',
    color: '#ffffff',
    fontWeight: 700,
  },
  checkboxRow: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.5rem',
    fontSize: '0.75rem',
    color: '#334155',
  },
  checkboxLabel: {
    cursor: 'pointer',
  },
  noteBox: {
    padding: '0.5rem 0.65rem',
    backgroundColor: '#f8fafc',
    border: '1px solid #e2e8f0',
    borderRadius: '3px',
    fontSize: '0.68rem',
    color: '#64748b',
    lineHeight: 1.4,
  },
  errorBox: {
    padding: '0.6rem',
    backgroundColor: '#fef2f2',
    border: '1px solid #fecaca',
    borderRadius: '3px',
    color: '#991b1b',
    fontSize: '0.75rem',
  },
  selectionTopBar: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    flexWrap: 'wrap',
    gap: '0.5rem',
    paddingBottom: '0.4rem',
    borderBottom: '1px solid #e2e8f0',
  },
  selectionSummary: {
    fontSize: '0.78rem',
    color: '#1e293b',
  },
  quickButtonsRow: {
    display: 'flex',
    gap: '0.35rem',
  },
  tinyBtn: {
    background: '#f8fafc',
    border: '1px solid #cbd5e1',
    borderRadius: '3px',
    padding: '0.25rem 0.5rem',
    fontSize: '0.68rem',
    fontWeight: 600,
    color: '#475569',
    cursor: 'pointer',
  },
  tableContainer: {
    maxHeight: '260px',
    overflowY: 'auto',
    border: '1px solid #e2e8f0',
    borderRadius: '3px',
  },
  emptyNotice: {
    padding: '2rem',
    textAlign: 'center',
    color: '#64748b',
    fontSize: '0.8rem',
  },
  table: {
    width: '100%',
    borderCollapse: 'collapse',
    fontSize: '0.74rem',
  },
  tableHeaderRow: {
    backgroundColor: '#f8fafc',
    borderBottom: '1px solid #e2e8f0',
    color: '#475569',
    fontSize: '0.68rem',
    fontWeight: 700,
    position: 'sticky',
    top: 0,
    zIndex: 1,
  },
  tableRow: {
    borderBottom: '1px solid #f1f5f9',
    cursor: 'pointer',
  },
  dateCell: {
    display: 'flex',
    flexDirection: 'column',
    padding: '0.4rem 0.2rem',
  },
  platformBadge: {
    fontSize: '0.6rem',
    fontWeight: 700,
    padding: '0.05rem 0.3rem',
    borderRadius: '2px',
    backgroundColor: '#e0f2fe',
    color: '#0369a1',
    border: '1px solid #bae6fd',
  },
  sceneIdSubtext: {
    fontSize: '0.62rem',
    color: '#94a3b8',
    fontFamily: 'monospace',
  },
  cloudCell: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.4rem',
  },
  cloudBarBg: {
    width: '45px',
    height: '6px',
    backgroundColor: '#e2e8f0',
    borderRadius: '3px',
    overflow: 'hidden',
  },
  cloudBarFill: {
    height: '100%',
  },
  qualityBadge: {
    display: 'inline-block',
    padding: '0.15rem 0.45rem',
    borderRadius: '3px',
    fontSize: '0.65rem',
    fontWeight: 700,
    letterSpacing: '0.02em',
  },
  availableBadge: {
    display: 'inline-block',
    padding: '0.15rem 0.45rem',
    backgroundColor: '#f3e8ff',
    color: '#6b21a8',
    border: '1px solid #d8b4fe',
    borderRadius: '3px',
    fontSize: '0.65rem',
    fontWeight: 700,
  },
  notFetchedBadge: {
    fontSize: '0.68rem',
    color: '#94a3b8',
  },
  selectionFooterRow: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: '0.2rem 0',
  },
  counterText: {
    fontSize: '0.78rem',
    color: '#0f172a',
  },
  limitWarning: {
    marginLeft: '0.6rem',
    fontSize: '0.72rem',
    color: '#dc2626',
    fontWeight: 600,
  },
  fastInfoText: {
    fontSize: '0.68rem',
    color: '#059669',
    fontWeight: 600,
  },
  progressContainer: {
    display: 'flex',
    flexDirection: 'column',
    gap: '0.75rem',
    padding: '0.5rem 0',
  },
  progressHeaderRow: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  stagePill: {
    display: 'inline-block',
    padding: '0.2rem 0.6rem',
    backgroundColor: '#eff6ff',
    color: '#1d4ed8',
    border: '1px solid #bfdbfe',
    borderRadius: '3px',
    fontSize: '0.72rem',
    fontWeight: 700,
  },
  progressPercentage: {
    fontSize: '1rem',
    fontWeight: 700,
    color: '#0f172a',
  },
  progressBarBg: {
    width: '100%',
    height: '10px',
    backgroundColor: '#e2e8f0',
    borderRadius: '5px',
    overflow: 'hidden',
  },
  progressBarFill: {
    height: '100%',
    backgroundColor: '#0284c7',
    transition: 'width 0.3s ease',
  },
  liveMessage: {
    fontSize: '0.78rem',
    color: '#334155',
    fontWeight: 500,
  },
  jobStatsRow: {
    display: 'flex',
    gap: '1rem',
    backgroundColor: '#f8fafc',
    padding: '0.6rem 0.8rem',
    borderRadius: '4px',
    border: '1px solid #e2e8f0',
  },
  jobStatItem: {
    display: 'flex',
    flexDirection: 'column',
  },
  jobStatLabel: {
    fontSize: '0.62rem',
    color: '#64748b',
    fontWeight: 700,
  },
  jobStatVal: {
    fontSize: '1rem',
    fontWeight: 700,
    color: '#0f172a',
  },
  finishedContainer: {
    display: 'flex',
    flexDirection: 'column',
    gap: '0.75rem',
  },
  resultBox: {
    padding: '0.75rem',
    backgroundColor: '#ecfdf5',
    border: '1px solid #a7f3d0',
    borderRadius: '3px',
    color: '#065f46',
  },
  resultTitle: {
    fontWeight: 700,
    fontSize: '0.85rem',
    marginBottom: '0.2rem',
  },
  resultDetail: {
    fontSize: '0.75rem',
    lineHeight: 1.35,
    marginBottom: '0.45rem',
  },
  resultStatsRow: {
    display: 'flex',
    gap: '0.8rem',
    fontSize: '0.7rem',
    color: '#047857',
  },
  unusableListBox: {
    padding: '0.65rem',
    backgroundColor: '#fffbeb',
    border: '1px solid #fde68a',
    borderRadius: '3px',
  },
  unusableTitle: {
    fontSize: '0.72rem',
    fontWeight: 700,
    color: '#92400e',
    marginBottom: '0.3rem',
  },
  unusableItem: {
    fontSize: '0.68rem',
    color: '#78350f',
    marginBottom: '0.2rem',
  },
  unusableScene: {
    fontFamily: 'monospace',
    fontWeight: 600,
  },
  unusableReason: {
    color: '#b45309',
  },
  unusableAdvice: {
    fontSize: '0.64rem',
    color: '#92400e',
    marginTop: '0.4rem',
    fontStyle: 'italic',
  },
  footer: {
    padding: '0.75rem 1.25rem',
    backgroundColor: '#f8fafc',
    borderTop: '1px solid #e2e8f0',
    display: 'flex',
    justifyContent: 'flex-end',
    alignItems: 'center',
    gap: '0.5rem',
  },
  cancelBtn: {
    padding: '0.5rem 1rem',
    backgroundColor: '#ffffff',
    border: '1px solid #cbd5e1',
    borderRadius: '3px',
    fontSize: '0.75rem',
    fontWeight: 600,
    color: '#475569',
    cursor: 'pointer',
  },
  submitBtn: {
    padding: '0.5rem 1.15rem',
    backgroundColor: '#0284c7',
    border: 'none',
    borderRadius: '3px',
    fontSize: '0.75rem',
    fontWeight: 700,
    color: '#ffffff',
    cursor: 'pointer',
    letterSpacing: '0.02em',
  },
  analysisNavBtn: {
    padding: '0.5rem 1.15rem',
    backgroundColor: '#15803d',
    border: 'none',
    borderRadius: '3px',
    fontSize: '0.75rem',
    fontWeight: 700,
    color: '#ffffff',
    cursor: 'pointer',
    letterSpacing: '0.02em',
  },
};
