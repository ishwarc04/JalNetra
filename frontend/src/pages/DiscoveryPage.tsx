import React, { useState, useEffect } from 'react';
import {
  searchDiscoveredWaterBodies,
  importDiscoveredWaterBody,
  getDiscoveryProviders,
  WaterBodyDiscoveryResult,
  ProviderStatus,
} from '../api';

export const DiscoveryPage: React.FC = () => {
  const [query, setQuery] = useState<string>('');
  const [limit, setLimit] = useState<number>(10);
  const [providers, setProviders] = useState<ProviderStatus[]>([]);
  const [selectedProvider, setSelectedProvider] = useState<string>('osm');
  const [isSearching, setIsSearching] = useState<boolean>(false);
  const [results, setResults] = useState<WaterBodyDiscoveryResult[]>([]);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [importStatus, setImportStatus] = useState<Record<string, string>>({});
  const [selectedResult, setSelectedResult] = useState<WaterBodyDiscoveryResult | null>(null);

  useEffect(() => {
    getDiscoveryProviders()
      .then((data) => {
        setProviders(data.providers);
        if (data.providers.length > 0) {
          setSelectedProvider(data.providers[0].name);
        }
      })
      .catch(() => {});
  }, []);

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;

    setIsSearching(true);
    setSearchError(null);
    setResults([]);
    setSelectedResult(null);

    try {
      const resp = await searchDiscoveredWaterBodies(query.trim(), limit, selectedProvider);
      setResults(resp.results);
      if (resp.results.length === 0) {
        setSearchError('No matching water bodies found for this query.');
      }
    } catch (err: unknown) {
      if (err instanceof Error) {
        setSearchError(err.message);
      } else {
        setSearchError('An error occurred during water body search.');
      }
    } finally {
      setIsSearching(false);
    }
  };

  const handleImport = async (result: WaterBodyDiscoveryResult) => {
    const key = `${result.provider}:${result.source_id}`;
    setImportStatus((prev) => ({ ...prev, [key]: 'Importing...' }));

    try {
      const saved = await importDiscoveredWaterBody(result);
      setImportStatus((prev) => ({
        ...prev,
        [key]: `Imported (${saved.id.substring(0, 8)}...)`,
      }));
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Import failed';
      setImportStatus((prev) => ({ ...prev, [key]: `Error: ${msg}` }));
    }
  };

  return (
    <div style={styles.container}>
      {/* Header and Search Controls */}
      <section style={styles.card}>
        <div style={styles.header}>
          <h2 style={styles.title}>GLOBAL WATER-BODY DISCOVERY</h2>
          <div style={styles.providerBadge}>
            PROVIDER: {selectedProvider.toUpperCase()} ({providers.find(p => p.name === selectedProvider)?.status || 'ACTIVE'})
          </div>
        </div>

        <p style={styles.desc}>
          Search global geospatial water bodies (lakes, reservoirs, rivers, lagoons) from OpenStreetMap
          and import verified geometries and bounding boxes into the local JalNetra catalog.
        </p>

        <form onSubmit={handleSearch} style={styles.searchForm}>
          <input
            type="text"
            placeholder="Search water body (e.g., Chilika Lake, Lake Victoria, Great Salt Lake, Nile)..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            style={styles.input}
            disabled={isSearching}
          />

          <select
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value))}
            style={styles.select}
            disabled={isSearching}
          >
            <option value={5}>Limit: 5</option>
            <option value={10}>Limit: 10</option>
            <option value={20}>Limit: 20</option>
          </select>

          <button type="submit" style={styles.btnPrimary} disabled={isSearching}>
            {isSearching ? 'SEARCHING...' : 'DISCOVER WATER BODIES'}
          </button>
        </form>

        {searchError && <div style={styles.errorBanner}>{searchError}</div>}
      </section>

      {/* Discovery Results Table */}
      {results.length > 0 && (
        <section style={styles.card}>
          <div style={styles.header}>
            <h3 style={styles.title}>
              DISCOVERY CANDIDATES ({results.length} RETURNED)
            </h3>
          </div>

          <div style={styles.tableWrapper}>
            <table style={styles.table}>
              <thead>
                <tr>
                  <th style={styles.th}>NAME</th>
                  <th style={styles.th}>LOCATION</th>
                  <th style={styles.th}>TYPE</th>
                  <th style={styles.th}>COORDINATES (CENTROID)</th>
                  <th style={styles.th}>AREA (APPROX)</th>
                  <th style={styles.th}>GEOMETRY</th>
                  <th style={styles.th}>ACTIONS</th>
                </tr>
              </thead>
              <tbody>
                {results.map((r) => {
                  const key = `${r.provider}:${r.source_id}`;
                  const statusLabel = importStatus[key];
                  const hasGeom = Boolean(r.geometry_geojson);

                  return (
                    <tr key={key}>
                      <td style={styles.tdBold}>{r.name}</td>
                      <td style={styles.td}>
                        {[r.district, r.state_province, r.country].filter(Boolean).join(', ') || '-'}
                      </td>
                      <td style={styles.tdMono}>
                        <span style={styles.typePill}>{r.water_body_type || 'water'}</span>
                      </td>
                      <td style={styles.tdMono}>
                        {r.centroid_lat != null && r.centroid_lon != null
                          ? `${r.centroid_lat.toFixed(4)}, ${r.centroid_lon.toFixed(4)}`
                          : '-'}
                      </td>
                      <td style={styles.td}>
                        {r.area_sq_km != null ? `${r.area_sq_km.toFixed(1)} km²` : '-'}
                      </td>
                      <td style={styles.td}>
                        <span
                          style={{
                            ...styles.geomPill,
                            backgroundColor: hasGeom ? 'var(--color-primary-subtle)' : '#f1f5f9',
                            borderColor: hasGeom ? 'var(--color-primary)' : 'var(--border-color)',
                            color: hasGeom ? 'var(--color-primary-dark)' : 'var(--color-text-muted)',
                          }}
                        >
                          {hasGeom ? 'GeoJSON Valid' : 'Point Only'}
                        </span>
                      </td>
                      <td style={styles.td}>
                        <div style={{ display: 'flex', gap: '0.4rem', alignItems: 'center' }}>
                          <button
                            type="button"
                            style={styles.btnSecondary}
                            onClick={() => setSelectedResult(r)}
                          >
                            DETAILS
                          </button>
                          <button
                            type="button"
                            style={styles.btnImport}
                            onClick={() => handleImport(r)}
                            disabled={statusLabel === 'Importing...'}
                          >
                            {statusLabel || 'IMPORT'}
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* Detail Modal/Card when a user clicks 'DETAILS' */}
      {selectedResult && (
        <section style={styles.detailCard}>
          <div style={styles.header}>
            <h3 style={styles.title}>
              GEOSPATIAL METADATA: {selectedResult.name.toUpperCase()}
            </h3>
            <button
              style={styles.closeBtn}
              onClick={() => setSelectedResult(null)}
            >
              CLOSE
            </button>
          </div>

          <div style={styles.detailGrid}>
            <div>
              <strong>Provider & Source ID:</strong> {selectedResult.provider} ({selectedResult.source_id})
            </div>
            <div>
              <strong>Bounding Box:</strong>{' '}
              {selectedResult.min_lat != null
                ? `[${selectedResult.min_lat}, ${selectedResult.min_lon}, ${selectedResult.max_lat}, ${selectedResult.max_lon}]`
                : 'Not available'}
            </div>
            <div>
              <strong>Geometry Hash:</strong>{' '}
              <span style={styles.monoText}>{selectedResult.geometry_hash || 'None'}</span>
            </div>
            <div>
              <strong>Full Description:</strong> {selectedResult.description || '-'}
            </div>
          </div>

          {selectedResult.geometry_geojson && (
            <div style={{ marginTop: '0.75rem' }}>
              <div style={styles.label}>RAW GEOJSON GEOMETRY PREVIEW:</div>
              <pre style={styles.jsonPreview}>
                {JSON.stringify(JSON.parse(selectedResult.geometry_geojson), null, 2)}
              </pre>
            </div>
          )}
        </section>
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
  card: {
    backgroundColor: 'var(--color-surface)',
    border: '1px solid var(--border-color)',
    padding: '1.25rem',
  },
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: '0.75rem',
    borderBottom: '1px solid var(--border-color)',
    paddingBottom: '0.5rem',
  },
  title: {
    fontSize: '0.85rem',
    fontWeight: 700,
    letterSpacing: '0.06em',
    color: 'var(--color-text-secondary)',
    margin: 0,
  },
  providerBadge: {
    fontSize: '0.7rem',
    fontFamily: 'var(--font-mono)',
    fontWeight: 700,
    color: 'var(--color-primary-dark)',
    backgroundColor: 'var(--color-primary-subtle)',
    padding: '0.2rem 0.5rem',
    border: '1px solid var(--color-primary)',
  },
  desc: {
    fontSize: '0.85rem',
    color: 'var(--color-text-secondary)',
    marginBottom: '1rem',
  },
  searchForm: {
    display: 'flex',
    gap: '0.5rem',
    flexWrap: 'wrap',
  },
  input: {
    flex: '1 1 300px',
    padding: '0.5rem 0.75rem',
    border: '1px solid var(--border-color-strong)',
    fontSize: '0.85rem',
    outline: 'none',
  },
  select: {
    padding: '0.5rem 0.75rem',
    border: '1px solid var(--border-color-strong)',
    fontSize: '0.8rem',
    backgroundColor: 'var(--color-surface)',
    cursor: 'pointer',
  },
  btnPrimary: {
    backgroundColor: 'var(--color-primary)',
    color: '#ffffff',
    border: 'none',
    padding: '0.5rem 1.25rem',
    fontWeight: 700,
    fontSize: '0.75rem',
    letterSpacing: '0.05em',
    cursor: 'pointer',
  },
  errorBanner: {
    marginTop: '0.75rem',
    backgroundColor: '#fef2f2',
    border: '1px solid var(--color-status-offline)',
    color: 'var(--color-status-offline)',
    padding: '0.5rem 0.75rem',
    fontSize: '0.8rem',
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
  tdBold: {
    border: '1px solid var(--border-color)',
    padding: '0.5rem 0.75rem',
    fontWeight: 700,
    color: 'var(--color-text-primary)',
  },
  tdMono: {
    border: '1px solid var(--border-color)',
    padding: '0.5rem 0.75rem',
    fontFamily: 'var(--font-mono)',
    fontSize: '0.75rem',
  },
  typePill: {
    display: 'inline-block',
    fontSize: '0.7rem',
    padding: '0.1rem 0.35rem',
    backgroundColor: 'var(--color-surface-subtle)',
    border: '1px solid var(--border-color)',
    textTransform: 'uppercase',
  },
  geomPill: {
    display: 'inline-block',
    fontSize: '0.7rem',
    padding: '0.15rem 0.4rem',
    border: '1px solid',
    fontWeight: 600,
  },
  btnSecondary: {
    backgroundColor: 'var(--color-surface-subtle)',
    border: '1px solid var(--border-color-strong)',
    padding: '0.25rem 0.5rem',
    fontSize: '0.7rem',
    fontWeight: 600,
    cursor: 'pointer',
  },
  btnImport: {
    backgroundColor: 'var(--color-accent)',
    color: '#ffffff',
    border: 'none',
    padding: '0.25rem 0.6rem',
    fontSize: '0.7rem',
    fontWeight: 700,
    cursor: 'pointer',
    letterSpacing: '0.03em',
  },
  detailCard: {
    backgroundColor: 'var(--color-surface)',
    border: '2px solid var(--color-primary)',
    padding: '1.25rem',
  },
  closeBtn: {
    backgroundColor: 'transparent',
    border: '1px solid var(--border-color)',
    padding: '0.2rem 0.5rem',
    fontSize: '0.7rem',
    cursor: 'pointer',
  },
  detailGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
    gap: '0.75rem',
    fontSize: '0.8rem',
  },
  label: {
    fontSize: '0.72rem',
    fontWeight: 700,
    color: 'var(--color-text-muted)',
    letterSpacing: '0.04em',
    marginBottom: '0.25rem',
  },
  monoText: {
    fontFamily: 'var(--font-mono)',
    fontSize: '0.75rem',
  },
  jsonPreview: {
    backgroundColor: 'var(--color-surface-subtle)',
    border: '1px solid var(--border-color)',
    padding: '0.75rem',
    fontFamily: 'var(--font-mono)',
    fontSize: '0.7rem',
    maxHeight: '180px',
    overflowY: 'auto',
  },
};
