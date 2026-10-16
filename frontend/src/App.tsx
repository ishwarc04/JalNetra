import React, { useEffect, useState, useCallback } from 'react';
import { Header } from './components/Header';
import { Navigation } from './components/Navigation';
import { Dashboard } from './pages/Dashboard';
import { DiscoveryPage } from './pages/DiscoveryPage';
import { SatellitePage } from './pages/SatellitePage';
import { MapPage } from './pages/MapPage';
import { AnalysisPage } from './pages/AnalysisPage';
import { checkHealth, HealthStatus } from './api';

class ErrorBoundary extends React.Component<
  { children: React.ReactNode },
  { hasError: boolean; error: Error | null }
> {
  constructor(props: { children: React.ReactNode }) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error) {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: any) {
    console.error('ErrorBoundary caught error:', error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{ padding: '2rem', textAlign: 'center', backgroundColor: '#fef2f2', border: '1px solid #f87171', margin: '1rem' }}>
          <h3 style={{ color: '#991b1b', marginBottom: '0.5rem' }}>WORKSTATION RENDERING ERROR</h3>
          <p style={{ color: '#7f1d1d', fontFamily: 'monospace', fontSize: '0.85rem' }}>
            {this.state.error?.message || 'An unexpected error occurred while rendering the map workstation.'}
          </p>
          <button
            onClick={() => this.setState({ hasError: false, error: null })}
            style={{ marginTop: '1rem', padding: '0.5rem 1rem', cursor: 'pointer', backgroundColor: '#15803d', color: '#fff', border: 'none' }}
          >
            RETRY COMPONENT
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

export const App: React.FC = () => {
  const [currentTab, setCurrentTab] = useState<string>('map');
  const [selectedWbIdForAnalysis, setSelectedWbIdForAnalysis] = useState<string | null>(null);
  const [backendStatus, setBackendStatus] = useState<'checking' | 'connected' | 'offline'>('checking');
  const [healthData, setHealthData] = useState<HealthStatus | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const handleNavigateToAnalysis = useCallback((waterBodyId?: string) => {
    if (waterBodyId) {
      setSelectedWbIdForAnalysis(waterBodyId);
    }
    setCurrentTab('analysis');
  }, []);

  const handleNavigateToMap = useCallback((waterBodyId?: string) => {
    if (waterBodyId) {
      try { localStorage.setItem('jalnetra_selected_wb_id', waterBodyId); } catch {}
    }
    setCurrentTab('map');
  }, []);

  const fetchStatus = useCallback(async () => {
    setBackendStatus('checking');
    try {
      const data = await checkHealth();
      setHealthData(data);
      setBackendStatus('connected');
      setErrorMessage(null);
    } catch (err: unknown) {
      setHealthData(null);
      setBackendStatus('offline');
      if (err instanceof Error) {
        setErrorMessage(err.message);
      } else {
        setErrorMessage('Failed to connect to backend server');
      }
    }
  }, []);

  useEffect(() => {
    fetchStatus();
    // Optional periodic poll every 30 seconds
    const interval = setInterval(fetchStatus, 30000);
    return () => clearInterval(interval);
  }, [fetchStatus]);

  return (
    <div style={styles.appContainer}>
      <Header status={backendStatus} serviceInfo={healthData} />
      <Navigation currentTab={currentTab} onTabChange={setCurrentTab} />

      <main style={currentTab === 'map' ? styles.mapMainContent : styles.mainContent}>
        {currentTab === 'overview' && (
          <Dashboard
            status={backendStatus}
            healthData={healthData}
            error={errorMessage}
            onRefresh={fetchStatus}
          />
        )}
        {currentTab === 'map' && (
          <ErrorBoundary>
            <MapPage onNavigateToAnalysis={handleNavigateToAnalysis} />
          </ErrorBoundary>
        )}
        {currentTab === 'analysis' && (
          <ErrorBoundary>
            <AnalysisPage
              initialWaterBodyId={selectedWbIdForAnalysis || undefined}
              onNavigateToMap={handleNavigateToMap}
            />
          </ErrorBoundary>
        )}
        {currentTab === 'discovery' && <DiscoveryPage />}
        {currentTab === 'satellite' && <SatellitePage />}
        {currentTab === 'catalog' && (
          <Dashboard
            status={backendStatus}
            healthData={healthData}
            error={errorMessage}
            onRefresh={fetchStatus}
          />
        )}
        {currentTab !== 'overview' && currentTab !== 'map' && currentTab !== 'analysis' && currentTab !== 'discovery' && currentTab !== 'satellite' && currentTab !== 'catalog' && (
          <div style={styles.placeholderCard}>
            <h3 style={styles.placeholderTitle}>MODULE RESERVED FOR FUTURE PHASE</h3>
            <p style={styles.placeholderDesc}>
              This subsystem will be activated in subsequent releases. The core storage and API architecture are currently prepared for integration.
            </p>
          </div>
        )}
      </main>

      <footer style={styles.footer}>
        <span>JalNetra 2.0 &bull; Operational Water Body Monitoring & Remote Sensing System</span>
        <span style={styles.footerMono}>ENV: LOCAL_DEV</span>
      </footer>
    </div>
  );
};

const styles: Record<string, React.CSSProperties> = {
  appContainer: {
    display: 'flex',
    flexDirection: 'column',
    minHeight: '100vh',
    backgroundColor: 'var(--color-bg)',
  },
  mainContent: {
    flex: 1,
    padding: '1.5rem',
    maxWidth: '1280px',
    width: '100%',
    margin: '0 auto',
  },
  mapMainContent: {
    flex: 1,
    width: '100%',
    height: 'calc(100vh - 125px)',
    minHeight: '600px',
    display: 'flex',
    flexDirection: 'column',
    position: 'relative',
    overflow: 'hidden',
    padding: 0,
    margin: 0,
  },
  placeholderCard: {
    backgroundColor: 'var(--color-surface)',
    border: '1px solid var(--border-color)',
    padding: '2rem',
    textAlign: 'center',
  },
  placeholderTitle: {
    fontSize: '0.9rem',
    fontWeight: 700,
    letterSpacing: '0.05em',
    color: 'var(--color-accent)',
    marginBottom: '0.5rem',
  },
  placeholderDesc: {
    fontSize: '0.85rem',
    color: 'var(--color-text-secondary)',
  },
  footer: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: '0.75rem 1.5rem',
    backgroundColor: 'var(--color-surface)',
    borderTop: '1px solid var(--border-color)',
    fontSize: '0.75rem',
    color: 'var(--color-text-muted)',
  },
  footerMono: {
    fontFamily: 'var(--font-mono)',
    fontWeight: 600,
  },
};

export default App;
