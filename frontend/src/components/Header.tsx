import React from 'react';

interface HeaderProps {
  status: 'connected' | 'offline' | 'checking';
  serviceInfo?: { service: string; version: string } | null;
}

export const Header: React.FC<HeaderProps> = ({ status, serviceInfo }) => {
  return (
    <header style={styles.header}>
      <div style={styles.titleContainer}>
        <div style={styles.badge}>JN-2.0</div>
        <div>
          <h1 style={styles.title}>JALNETRA 2.0</h1>
          <p style={styles.subtitle}>Geospatial Water Resource Monitoring & Analysis Platform</p>
        </div>
      </div>

      <div style={styles.statusBox}>
        <a
          href="https://t.me/jalNetra_Helperbot"
          target="_blank"
          rel="noopener noreferrer"
          title="Open JalNetra Telegram Assistant"
          style={styles.telegramLink}
        >
          <span style={{ fontSize: '0.85rem' }}>💬</span>
          <span>Telegram Assistant</span>
        </a>

        <span style={styles.statusLabel}>Backend:</span>
        <span
          style={{
            ...styles.statusBadge,
            backgroundColor:
              status === 'connected'
                ? 'var(--color-primary-subtle)'
                : status === 'checking'
                ? 'var(--color-surface-subtle)'
                : '#fef2f2',
            color:
              status === 'connected'
                ? 'var(--color-primary)'
                : status === 'checking'
                ? 'var(--color-text-secondary)'
                : 'var(--color-status-offline)',
            borderColor:
              status === 'connected'
                ? 'var(--color-primary)'
                : status === 'checking'
                ? 'var(--border-color)'
                : 'var(--color-status-offline)',
          }}
        >
          <span
            style={{
              ...styles.statusDot,
              backgroundColor:
                status === 'connected'
                  ? 'var(--color-primary)'
                  : status === 'checking'
                  ? 'var(--color-text-muted)'
                  : 'var(--color-status-offline)',
            }}
          />
          {status === 'connected'
            ? `Connected (v${serviceInfo?.version || '2.0.0'})`
            : status === 'checking'
            ? 'Checking...'
            : 'Offline'}
        </span>
      </div>
    </header>
  );
};

const styles: Record<string, React.CSSProperties> = {
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: '0.875rem 1.5rem',
    backgroundColor: 'var(--color-surface)',
    borderBottom: '2px solid var(--color-primary)',
    boxShadow: '0 1px 2px rgba(0, 0, 0, 0.05)',
  },
  titleContainer: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.75rem',
  },
  badge: {
    backgroundColor: 'var(--color-primary)',
    color: '#ffffff',
    fontWeight: 700,
    fontSize: '0.75rem',
    padding: '0.25rem 0.5rem',
    letterSpacing: '0.05em',
  },
  title: {
    fontSize: '1.25rem',
    fontWeight: 800,
    letterSpacing: '0.05em',
    color: 'var(--color-text-primary)',
    margin: 0,
    lineHeight: 1.1,
  },
  subtitle: {
    fontSize: '0.75rem',
    color: 'var(--color-text-secondary)',
    margin: 0,
    fontWeight: 500,
  },
  statusBox: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.5rem',
    fontSize: '0.85rem',
  },
  statusLabel: {
    color: 'var(--color-text-secondary)',
    fontWeight: 600,
  },
  statusBadge: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: '0.4rem',
    padding: '0.25rem 0.6rem',
    border: '1px solid',
    fontSize: '0.75rem',
    fontWeight: 600,
    fontFamily: 'var(--font-mono)',
  },
  statusDot: {
    width: '6px',
    height: '6px',
    display: 'inline-block',
  },
  telegramLink: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: '0.4rem',
    padding: '0.25rem 0.65rem',
    backgroundColor: '#f0f9ff',
    border: '1px solid #7dd3fc',
    borderRadius: '3px',
    color: '#0369a1',
    fontSize: '0.75rem',
    fontWeight: 700,
    textDecoration: 'none',
    transition: 'all 0.15s ease',
  },
};
