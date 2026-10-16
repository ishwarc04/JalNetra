import React, { useEffect, useState } from 'react';
import {
  HealthStatus,
  StorageStatus,
  WaterBody,
  StorageResetResponse,
  getStorageStatus,
  listWaterBodies,
  createWaterBody,
  clearCache,
  clearProcessedData,
  clearSatelliteData,
  resetProjectData,
} from '../api';

interface DashboardProps {
  status: 'connected' | 'offline' | 'checking';
  healthData: HealthStatus | null;
  error: string | null;
  onRefresh: () => void;
}

export const Dashboard: React.FC<DashboardProps> = ({
  status,
  healthData,
  error,
  onRefresh,
}) => {
  const [storageStatus, setStorageStatus] = useState<StorageStatus | null>(null);
  const [waterBodies, setWaterBodies] = useState<WaterBody[]>([]);
  const [wbCount, setWbCount] = useState<number>(0);
  const [newWbName, setNewWbName] = useState<string>('');
  const [actionMsg, setActionMsg] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [isOperating, setIsOperating] = useState<boolean>(false);

  // Modal / Confirm State
  const [confirmModal, setConfirmModal] = useState<{
    open: boolean;
    title: string;
    message: string;
    action: () => Promise<void>;
    isDestructive: boolean;
  } | null>(null);

  const loadData = async () => {
    if (status !== 'connected') return;
    try {
      const s = await getStorageStatus();
      setStorageStatus(s);
      const wbs = await listWaterBodies(5, 0);
      setWaterBodies(wbs.items);
      setWbCount(wbs.total);
    } catch {
      // Ignored if offline
    }
  };

  useEffect(() => {
    loadData();
  }, [status]);

  const handleCreateTestBody = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newWbName.trim()) return;
    setIsSubmitting(true);
    setActionMsg(null);
    setActionError(null);
    try {
      const created = await createWaterBody({
        name: newWbName.trim(),
        country: 'India',
        source: 'manual',
        source_id: `test-${Date.now()}`,
      });
      setActionMsg(`Created water body: ${created.name} (ID: ${created.id.substring(0, 8)}...)`);
      setNewWbName('');
      await loadData();
    } catch (err: unknown) {
      if (err instanceof Error) {
        setActionError(`Error: ${err.message}`);
      } else {
        setActionError('Failed to create water body');
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  const executeClearCache = async () => {
    setIsOperating(true);
    setActionMsg(null);
    setActionError(null);
    try {
      const res: StorageResetResponse = await clearCache();
      setActionMsg(res.message);
      await loadData();
      onRefresh();
    } catch (err: any) {
      setActionError(err.message || 'Failed to clear cache');
    } finally {
      setIsOperating(false);
      setConfirmModal(null);
    }
  };

  const executeClearProcessed = async () => {
    setIsOperating(true);
    setActionMsg(null);
    setActionError(null);
    try {
      const res: StorageResetResponse = await clearProcessedData();
      setActionMsg(res.message);
      await loadData();
      onRefresh();
    } catch (err: any) {
      setActionError(err.message || 'Failed to clear processed data');
    } finally {
      setIsOperating(false);
      setConfirmModal(null);
    }
  };

  const executeClearSatellite = async () => {
    setIsOperating(true);
    setActionMsg(null);
    setActionError(null);
    try {
      const res: StorageResetResponse = await clearSatelliteData();
      setActionMsg(res.message);
      // Clean selected water body / scene cache from localStorage
      try { localStorage.removeItem('jalnetra_selected_wb_id'); } catch { /* ignore */ }
      await loadData();
      onRefresh();
    } catch (err: any) {
      setActionError(err.message || 'Failed to clear satellite data');
    } finally {
      setIsOperating(false);
      setConfirmModal(null);
    }
  };

  const executeResetAll = async () => {
    setIsOperating(true);
    setActionMsg(null);
    setActionError(null);
    try {
      const res: StorageResetResponse = await resetProjectData();
      setActionMsg(res.message);
      // Clear localStorage selected water body
      try { localStorage.removeItem('jalnetra_selected_wb_id'); } catch { /* ignore */ }
      await loadData();
      onRefresh();
    } catch (err: any) {
      setActionError(err.message || 'Failed to reset project data');
    } finally {
      setIsOperating(false);
      setConfirmModal(null);
    }
  };

  // Helper values
  const dbCounts = storageStatus?.database_counts || {
    water_bodies: storageStatus?.database?.water_bodies ?? wbCount,
    satellite_scenes: storageStatus?.database?.scenes ?? 0,
    satellite_assets: storageStatus?.database?.assets ?? 0,
    analysis_runs: storageStatus?.database?.analysis_runs ?? 0,
    cache_entries: storageStatus?.database?.cache_entries ?? 0,
    size_formatted: storageStatus?.database?.size_formatted ?? '0 B',
  };

  const localSizes = storageStatus?.local_storage || {
    satellite_data_formatted: '0 B',
    processed_data_formatted: '0 B',
    cache_formatted: '0 B',
    total_formatted: '0 B',
  };

  const orphans = storageStatus?.orphans || {
    orphan_scene_directories_count: 0,
    missing_scene_directories_count: 0,
  };

  return (
    <div style={styles.container}>
      {/* Overview Status Banner */}
      <section style={styles.sectionCard}>
        <div style={styles.sectionHeader}>
          <h2 style={styles.sectionTitle}>SYSTEM STATUS &amp; STORAGE PERSISTENCE</h2>
          <button style={styles.refreshBtn} onClick={() => { onRefresh(); loadData(); }}>
            CHECK STATUS
          </button>
        </div>

        <div style={styles.grid}>
          <div style={styles.metricCard}>
            <div style={styles.metricLabel}>BACKEND API SERVICE</div>
            <div
              style={{
                ...styles.metricValue,
                color:
                  status === 'connected'
                    ? 'var(--color-primary)'
                    : status === 'checking'
                    ? 'var(--color-text-secondary)'
                    : 'var(--color-status-offline)',
              }}
            >
              {status === 'connected' ? 'ONLINE / CONNECTED' : status === 'checking' ? 'PROBING...' : 'OFFLINE'}
            </div>
            <div style={styles.metricDetail}>
              {status === 'connected'
                ? `${healthData?.service} (v${healthData?.version})`
                : error || 'Service unreachable on configured endpoint'}
            </div>
          </div>

          <div style={styles.metricCard}>
            <div style={styles.metricLabel}>SQLITE 3 DATABASE (ALEMBIC)</div>
            <div style={styles.metricValue}>
              {storageStatus?.database?.status === 'ok' ? 'HEALTHY (OK)' : 'OFFLINE'}
            </div>
            <div style={styles.metricDetail}>data/database/jalnetra.db ({dbCounts.size_formatted})</div>
          </div>

          <div style={styles.metricCard}>
            <div style={styles.metricLabel}>CATALOG WATER BODIES</div>
            <div style={styles.metricValue}>{dbCounts.water_bodies} RECORD(S)</div>
            <div style={styles.metricDetail}>Phase 1 User-Managed Baseline</div>
          </div>
        </div>
      </section>

      {/* Action Notification Messages */}
      {actionMsg && <div style={styles.actionNotice}>✓ {actionMsg}</div>}
      {actionError && <div style={styles.errorNotice}>✕ {actionError}</div>}

      {/* STORAGE & DATA MANAGEMENT SECTION (PHASE 1) */}
      <section style={styles.sectionCard}>
        <div style={styles.sectionHeader}>
          <h2 style={styles.sectionTitle}>STORAGE &amp; DATA MANAGEMENT (PHASE 1)</h2>
          <span style={styles.badgeSafe}>SAFE ISOLATION</span>
        </div>

        <p style={styles.description}>
          Authoritative database counts and filesystem storage metrics. Clear individual caches or perform a safe, complete project reset to return to an empty baseline.
        </p>

        <div style={styles.storageGrid}>
          {/* DATABASE METRICS */}
          <div style={styles.storagePanel}>
            <div style={styles.storagePanelHeader}>
              <span style={styles.storagePanelTitle}>DATABASE INVENTORY</span>
              <span style={styles.storagePanelBadge}>SQLITE 3</span>
            </div>
            <div style={styles.statRow}>
              <span style={styles.statKey}>Water Bodies:</span>
              <span style={styles.statVal}>{dbCounts.water_bodies}</span>
            </div>
            <div style={styles.statRow}>
              <span style={styles.statKey}>Satellite Scenes:</span>
              <span style={styles.statVal}>{dbCounts.satellite_scenes}</span>
            </div>
            <div style={styles.statRow}>
              <span style={styles.statKey}>Satellite Assets:</span>
              <span style={styles.statVal}>{dbCounts.satellite_assets}</span>
            </div>
            <div style={styles.statRow}>
              <span style={styles.statKey}>Analysis Runs:</span>
              <span style={styles.statVal}>{dbCounts.analysis_runs}</span>
            </div>
            <div style={styles.statRow}>
              <span style={styles.statKey}>Cache Entries:</span>
              <span style={styles.statVal}>{dbCounts.cache_entries}</span>
            </div>
            <div style={{ ...styles.statRow, borderTop: '1px dashed var(--border-color)', paddingTop: '0.4rem', marginTop: '0.4rem' }}>
              <span style={styles.statKey}>Database File Size:</span>
              <span style={{ ...styles.statVal, fontWeight: 700 }}>{dbCounts.size_formatted}</span>
            </div>
          </div>

          {/* LOCAL STORAGE METRICS */}
          <div style={styles.storagePanel}>
            <div style={styles.storagePanelHeader}>
              <span style={styles.storagePanelTitle}>LOCAL STORAGE FOOTPRINT</span>
              <span style={styles.storagePanelBadge}>./data/*</span>
            </div>
            <div style={styles.statRow}>
              <span style={styles.statKey}>Satellite Data:</span>
              <span style={styles.statVal}>{localSizes.satellite_data_formatted}</span>
            </div>
            <div style={styles.statRow}>
              <span style={styles.statKey}>Processed Data:</span>
              <span style={styles.statVal}>{localSizes.processed_data_formatted}</span>
            </div>
            <div style={styles.statRow}>
              <span style={styles.statKey}>Cache Storage:</span>
              <span style={styles.statVal}>{localSizes.cache_formatted}</span>
            </div>
            <div style={styles.statRow}>
              <span style={styles.statKey}>Orphan Scene Dirs:</span>
              <span style={{ ...styles.statVal, color: orphans.orphan_scene_directories_count > 0 ? '#b45309' : 'inherit' }}>
                {orphans.orphan_scene_directories_count} detected
              </span>
            </div>
            <div style={styles.statRow}>
              <span style={styles.statKey}>Missing Scene Dirs:</span>
              <span style={styles.statVal}>{orphans.missing_scene_directories_count}</span>
            </div>
            <div style={{ ...styles.statRow, borderTop: '1px dashed var(--border-color)', paddingTop: '0.4rem', marginTop: '0.4rem' }}>
              <span style={styles.statKey}>Total Local Storage:</span>
              <span style={{ ...styles.statVal, fontWeight: 700, color: 'var(--color-primary)' }}>{localSizes.total_formatted}</span>
            </div>
          </div>
        </div>

        {/* MAINTENANCE ACTION BUTTONS */}
        <div style={styles.actionButtonContainer}>
          <button
            style={styles.actionBtnSecondary}
            onClick={() =>
              setConfirmModal({
                open: true,
                title: 'CLEAR CACHE DATA',
                message: 'This will remove all search and temporary cache entries from the database and delete JSON cache files in data/cache/. This will not affect water bodies or scenes.',
                action: executeClearCache,
                isDestructive: false,
              })
            }
            disabled={isOperating}
          >
            CLEAR CACHE
          </button>

          <button
            style={styles.actionBtnSecondary}
            onClick={() =>
              setConfirmModal({
                open: true,
                title: 'CLEAR PROCESSED DATA',
                message: 'This will remove all cloud/water mask analysis records from the database and delete generated masks in data/processed/. Raw satellite scenes will remain untouched.',
                action: executeClearProcessed,
                isDestructive: false,
              })
            }
            disabled={isOperating}
          >
            CLEAR PROCESSED DATA
          </button>

          <button
            style={styles.actionBtnSecondary}
            onClick={() =>
              setConfirmModal({
                open: true,
                title: 'CLEAR SATELLITE DATA',
                message: 'This will permanently remove all downloaded Sentinel-2 raw band GeoTIFFs, scene records, and assets from data/scenes/. Registered water bodies will be preserved.',
                action: executeClearSatellite,
                isDestructive: true,
              })
            }
            disabled={isOperating}
          >
            CLEAR SATELLITE DATA
          </button>

          <button
            style={styles.actionBtnDanger}
            onClick={() =>
              setConfirmModal({
                open: true,
                title: 'RESET PROJECT DATA',
                message: 'This will permanently remove all stored water bodies, satellite scenes, downloaded imagery, processed results and cache data. Project code and database schema will not be deleted.',
                action: executeResetAll,
                isDestructive: true,
              })
            }
            disabled={isOperating}
          >
            RESET PROJECT DATA
          </button>
        </div>
      </section>

      {/* Confirmation Modal */}
      {confirmModal && (
        <div style={styles.modalOverlay}>
          <div style={styles.modalBox}>
            <div style={styles.modalHeader}>
              <span style={confirmModal.isDestructive ? styles.modalTitleDanger : styles.modalTitle}>
                {confirmModal.title}
              </span>
            </div>
            <div style={styles.modalBody}>
              <p style={styles.modalText}>{confirmModal.message}</p>
            </div>
            <div style={styles.modalFooter}>
              <button
                style={styles.modalCancelBtn}
                onClick={() => setConfirmModal(null)}
                disabled={isOperating}
              >
                CANCEL
              </button>
              <button
                style={confirmModal.isDestructive ? styles.modalConfirmDangerBtn : styles.modalConfirmBtn}
                onClick={confirmModal.action}
                disabled={isOperating}
              >
                {isOperating ? 'EXECUTING...' : 'CONFIRM & EXECUTE'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Phase 1 Developer Persistence Controls */}
      {status === 'connected' && (
        <section style={styles.sectionCard}>
          <div style={styles.sectionHeader}>
            <h2 style={styles.sectionTitle}>MANUAL WATER BODY CREATION (TEST VERIFICATION)</h2>
          </div>
          <p style={styles.description}>
            Add a test water body record into the local SQLite database to verify API routing, Pydantic validation, repository transactions, and persistence.
          </p>

          <form onSubmit={handleCreateTestBody} style={styles.formRow}>
            <input
              type="text"
              placeholder="Water Body Name (e.g. Sambhar Salt Lake)"
              value={newWbName}
              onChange={(e) => setNewWbName(e.target.value)}
              style={styles.input}
              disabled={isSubmitting || isOperating}
            />
            <button type="submit" style={styles.submitBtn} disabled={isSubmitting || isOperating}>
              {isSubmitting ? 'SAVING...' : 'INSERT RECORD'}
            </button>
          </form>

          {waterBodies.length > 0 ? (
            <div style={{ marginTop: '1rem' }}>
              <div style={styles.metricLabel}>RECENT PERSISTED WATER BODIES ({waterBodies.length}):</div>
              <div style={styles.tableWrapper}>
                <table style={styles.table}>
                  <thead>
                    <tr>
                      <th style={styles.th}>ID</th>
                      <th style={styles.th}>NAME</th>
                      <th style={styles.th}>COUNTRY</th>
                      <th style={styles.th}>SOURCE</th>
                      <th style={styles.th}>STATUS</th>
                    </tr>
                  </thead>
                  <tbody>
                    {waterBodies.map((wb) => (
                      <tr key={wb.id}>
                        <td style={styles.tdMono}>{wb.id.substring(0, 8)}...</td>
                        <td style={styles.td}>{wb.name}</td>
                        <td style={styles.td}>{wb.country || '-'}</td>
                        <td style={styles.tdMono}>{wb.source}</td>
                        <td style={styles.td}>
                          <span style={styles.statusPill}>
                            {wb.is_active ? 'Active' : 'Inactive'}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : (
            <div style={styles.emptyNotice}>
              No water bodies stored in database. Use Global Discovery to search and register water bodies.
            </div>
          )}
        </section>
      )}

      {/* Architecture & Pipeline Architecture Details */}
      <section style={styles.sectionCard}>
        <div style={styles.sectionHeader}>
          <h2 style={styles.sectionTitle}>DATA PIPELINE STORAGE SUB-DIRECTORIES</h2>
        </div>

        <div style={styles.tableWrapper}>
          <table style={styles.table}>
            <thead>
              <tr>
                <th style={styles.th}>SUBSYSTEM</th>
                <th style={styles.th}>LOCAL DIRECTORY</th>
                <th style={styles.th}>FILES</th>
                <th style={styles.th}>STATUS</th>
              </tr>
            </thead>
            <tbody>
              {storageStatus?.details &&
                Object.entries(storageStatus.details).map(([key, val]) => (
                  <tr key={key}>
                    <td style={styles.td}>{key.toUpperCase()}</td>
                    <td style={styles.tdMono}>{val.path}</td>
                    <td style={styles.td}>{val.file_count}</td>
                    <td style={styles.td}>
                      <span style={styles.statusPill}>
                        {val.exists ? 'Available' : 'Missing'}
                      </span>
                    </td>
                  </tr>
                ))}
              {!storageStatus?.details && (
                <tr>
                  <td colSpan={4} style={styles.td}>
                    Connect backend to read storage directories status.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
};

const styles: Record<string, React.CSSProperties> = {
  container: {
    display: 'flex',
    flexDirection: 'column',
    gap: '1.25rem',
  },
  sectionCard: {
    backgroundColor: 'var(--color-surface)',
    border: '1px solid var(--border-color)',
    padding: '1.25rem',
  },
  sectionHeader: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: '1rem',
    borderBottom: '1px solid var(--border-color)',
    paddingBottom: '0.5rem',
  },
  sectionTitle: {
    fontSize: '0.85rem',
    fontWeight: 700,
    letterSpacing: '0.05em',
    color: 'var(--color-text-primary)',
    margin: 0,
  },
  refreshBtn: {
    backgroundColor: 'var(--color-surface-subtle)',
    border: '1px solid var(--border-color)',
    color: 'var(--color-text-secondary)',
    padding: '0.35rem 0.75rem',
    fontSize: '0.75rem',
    fontWeight: 600,
    cursor: 'pointer',
  },
  badgeSafe: {
    fontSize: '0.68rem',
    fontWeight: 700,
    padding: '0.2rem 0.5rem',
    backgroundColor: '#ecfdf5',
    color: '#065f46',
    border: '1px solid #6ee7b7',
    borderRadius: '2px',
    letterSpacing: '0.04em',
  },
  description: {
    fontSize: '0.82rem',
    color: 'var(--color-text-secondary)',
    marginBottom: '1rem',
    lineHeight: 1.5,
  },
  grid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
    gap: '1rem',
  },
  metricCard: {
    backgroundColor: 'var(--color-surface-subtle)',
    border: '1px solid var(--border-color)',
    padding: '1rem',
  },
  metricLabel: {
    fontSize: '0.72rem',
    fontWeight: 700,
    color: 'var(--color-text-muted)',
    letterSpacing: '0.04em',
    marginBottom: '0.5rem',
  },
  metricValue: {
    fontSize: '1.1rem',
    fontWeight: 700,
    color: 'var(--color-text-primary)',
    marginBottom: '0.25rem',
  },
  metricDetail: {
    fontSize: '0.75rem',
    color: 'var(--color-text-secondary)',
    fontFamily: 'var(--font-mono)',
  },
  storageGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
    gap: '1rem',
    marginBottom: '1.25rem',
  },
  storagePanel: {
    backgroundColor: 'var(--color-surface-subtle)',
    border: '1px solid var(--border-color)',
    padding: '1rem',
  },
  storagePanelHeader: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: '0.75rem',
    borderBottom: '1px solid var(--border-color)',
    paddingBottom: '0.4rem',
  },
  storagePanelTitle: {
    fontSize: '0.75rem',
    fontWeight: 700,
    letterSpacing: '0.04em',
    color: 'var(--color-text-primary)',
  },
  storagePanelBadge: {
    fontSize: '0.68rem',
    fontFamily: 'var(--font-mono)',
    color: 'var(--color-text-muted)',
  },
  statRow: {
    display: 'flex',
    justifyContent: 'space-between',
    padding: '0.3rem 0',
    fontSize: '0.8rem',
  },
  statKey: {
    color: 'var(--color-text-secondary)',
  },
  statVal: {
    fontFamily: 'var(--font-mono)',
    fontWeight: 600,
    color: 'var(--color-text-primary)',
  },
  actionButtonContainer: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: '0.75rem',
    paddingTop: '0.75rem',
    borderTop: '1px solid var(--border-color)',
  },
  actionBtnSecondary: {
    backgroundColor: 'var(--color-surface-subtle)',
    border: '1px solid var(--border-color-strong)',
    color: 'var(--color-text-primary)',
    padding: '0.5rem 1rem',
    fontWeight: 600,
    fontSize: '0.75rem',
    letterSpacing: '0.04em',
    cursor: 'pointer',
  },
  actionBtnDanger: {
    backgroundColor: '#b91c1c',
    border: '1px solid #991b1b',
    color: '#ffffff',
    padding: '0.5rem 1.25rem',
    fontWeight: 700,
    fontSize: '0.75rem',
    letterSpacing: '0.05em',
    cursor: 'pointer',
    marginLeft: 'auto',
  },
  formRow: {
    display: 'flex',
    gap: '0.5rem',
    marginBottom: '0.75rem',
  },
  input: {
    flex: 1,
    padding: '0.45rem 0.75rem',
    border: '1px solid var(--border-color-strong)',
    fontSize: '0.8rem',
    outline: 'none',
  },
  submitBtn: {
    backgroundColor: 'var(--color-primary)',
    color: '#ffffff',
    border: 'none',
    padding: '0.45rem 1rem',
    fontWeight: 700,
    fontSize: '0.75rem',
    cursor: 'pointer',
    letterSpacing: '0.04em',
  },
  actionNotice: {
    backgroundColor: '#ecfdf5',
    border: '1px solid #10b981',
    color: '#065f46',
    padding: '0.65rem 1rem',
    fontSize: '0.8rem',
    fontFamily: 'var(--font-mono)',
  },
  errorNotice: {
    backgroundColor: '#fef2f2',
    border: '1px solid #ef4444',
    color: '#991b1b',
    padding: '0.65rem 1rem',
    fontSize: '0.8rem',
    fontFamily: 'var(--font-mono)',
  },
  emptyNotice: {
    padding: '1.25rem',
    textAlign: 'center',
    fontSize: '0.8rem',
    color: 'var(--color-text-muted)',
    backgroundColor: 'var(--color-surface-subtle)',
    border: '1px dashed var(--border-color)',
    marginTop: '0.75rem',
  },
  tableWrapper: {
    overflowX: 'auto',
  },
  table: {
    width: '100%',
    borderCollapse: 'collapse',
    fontSize: '0.8rem',
    textAlign: 'left',
  },
  th: {
    backgroundColor: 'var(--color-surface-subtle)',
    border: '1px solid var(--border-color)',
    padding: '0.5rem 0.75rem',
    fontWeight: 700,
    fontSize: '0.72rem',
    letterSpacing: '0.04em',
    color: 'var(--color-text-secondary)',
  },
  td: {
    border: '1px solid var(--border-color)',
    padding: '0.5rem 0.75rem',
    color: 'var(--color-text-primary)',
  },
  tdMono: {
    border: '1px solid var(--border-color)',
    padding: '0.5rem 0.75rem',
    fontFamily: 'var(--font-mono)',
    fontSize: '0.75rem',
    color: 'var(--color-text-secondary)',
  },
  statusPill: {
    display: 'inline-block',
    fontSize: '0.7rem',
    fontWeight: 600,
    color: 'var(--color-primary-dark)',
    backgroundColor: 'var(--color-primary-subtle)',
    padding: '0.15rem 0.4rem',
    border: '1px solid var(--color-primary)',
  },
  modalOverlay: {
    position: 'fixed',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: 'rgba(0, 0, 0, 0.65)',
    display: 'flex',
    justifyContent: 'center',
    alignItems: 'center',
    zIndex: 9999,
  },
  modalBox: {
    backgroundColor: 'var(--color-surface)',
    border: '2px solid var(--border-color-strong)',
    width: '90%',
    maxWidth: '520px',
    boxShadow: '0 10px 25px rgba(0, 0, 0, 0.3)',
  },
  modalHeader: {
    padding: '1rem 1.25rem',
    borderBottom: '1px solid var(--border-color)',
    backgroundColor: 'var(--color-surface-subtle)',
  },
  modalTitle: {
    fontWeight: 700,
    fontSize: '0.9rem',
    letterSpacing: '0.04em',
    color: 'var(--color-text-primary)',
  },
  modalTitleDanger: {
    fontWeight: 700,
    fontSize: '0.9rem',
    letterSpacing: '0.04em',
    color: '#b91c1c',
  },
  modalBody: {
    padding: '1.25rem',
  },
  modalText: {
    fontSize: '0.85rem',
    color: 'var(--color-text-primary)',
    lineHeight: 1.5,
    margin: 0,
  },
  modalFooter: {
    display: 'flex',
    justifyContent: 'flex-end',
    gap: '0.75rem',
    padding: '0.75rem 1.25rem',
    borderTop: '1px solid var(--border-color)',
    backgroundColor: 'var(--color-surface-subtle)',
  },
  modalCancelBtn: {
    padding: '0.45rem 1rem',
    fontSize: '0.75rem',
    fontWeight: 600,
    backgroundColor: 'transparent',
    border: '1px solid var(--border-color-strong)',
    color: 'var(--color-text-secondary)',
    cursor: 'pointer',
  },
  modalConfirmBtn: {
    padding: '0.45rem 1rem',
    fontSize: '0.75rem',
    fontWeight: 700,
    backgroundColor: 'var(--color-primary)',
    border: 'none',
    color: '#ffffff',
    cursor: 'pointer',
  },
  modalConfirmDangerBtn: {
    padding: '0.45rem 1rem',
    fontSize: '0.75rem',
    fontWeight: 700,
    backgroundColor: '#b91c1c',
    border: 'none',
    color: '#ffffff',
    cursor: 'pointer',
  },
};

export default Dashboard;
