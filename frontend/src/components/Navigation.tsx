import React from 'react';

interface NavigationProps {
  currentTab: string;
  onTabChange: (tab: string) => void;
}

export const Navigation: React.FC<NavigationProps> = ({ currentTab, onTabChange }) => {
  const tabs = [
    { id: 'overview', label: 'SYSTEM OVERVIEW' },
    { id: 'map', label: 'MONITORING MAP (PHASE 4)' },
    { id: 'analysis', label: 'ANALYSIS (TIME-SERIES)' },
    { id: 'discovery', label: 'GLOBAL DISCOVERY (PHASE 2)' },
    { id: 'catalog', label: 'WATER BODY CATALOG (PHASE 1)' },
    { id: 'satellite', label: 'SENTINEL-2 / SCENES (PHASE 3)' },
    { id: 'analytics', label: 'WATER DETECTION & ML (PHASE 5)' },
    { id: 'alerts', label: 'TELEMETRY & ALERTS (PHASE 6)' },
  ];

  return (
    <nav style={styles.nav}>
      <div style={styles.tabsList}>
        {tabs.map((tab) => {
          const isActive = currentTab === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => onTabChange(tab.id)}
              style={{
                ...styles.tabButton,
                backgroundColor: isActive ? 'var(--color-surface)' : 'transparent',
                color: isActive ? 'var(--color-primary)' : 'var(--color-text-secondary)',
                borderBottom: isActive ? '2px solid var(--color-accent)' : '2px solid transparent',
                fontWeight: isActive ? 700 : 500,
              }}
            >
              {tab.label}
            </button>
          );
        })}
      </div>
    </nav>
  );
};

const styles: Record<string, React.CSSProperties> = {
  nav: {
    backgroundColor: 'var(--color-surface-subtle)',
    borderBottom: '1px solid var(--border-color)',
    padding: '0 1.5rem',
  },
  tabsList: {
    display: 'flex',
    gap: '0.25rem',
    overflowX: 'auto',
  },
  tabButton: {
    background: 'none',
    border: 'none',
    padding: '0.75rem 1rem',
    cursor: 'pointer',
    fontSize: '0.75rem',
    letterSpacing: '0.04em',
    outline: 'none',
    whiteSpace: 'nowrap',
    transition: 'color 0.15s, border-color 0.15s',
  },
};
