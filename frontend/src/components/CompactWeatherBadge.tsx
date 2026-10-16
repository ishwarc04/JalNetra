import React, { useState, useEffect } from 'react';
import { WeatherResponse, getWaterBodyWeather } from '../api/weather';

interface CompactWeatherBadgeProps {
  waterBodyId: string;
  onNavigateToAnalysis?: (waterBodyId: string) => void;
}

export const CompactWeatherBadge: React.FC<CompactWeatherBadgeProps> = ({
  waterBodyId,
  onNavigateToAnalysis,
}) => {
  const [weather, setWeather] = useState<WeatherResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<boolean>(false);

  useEffect(() => {
    let isMounted = true;
    if (!waterBodyId) return;

    setLoading(true);
    setError(false);

    getWaterBodyWeather(waterBodyId)
      .then((data) => {
        if (isMounted) {
          setWeather(data);
          setLoading(false);
        }
      })
      .catch((err) => {
        if (isMounted) {
          console.debug('Compact weather badge failed for', waterBodyId, err);
          setError(true);
          setLoading(false);
        }
      });

    return () => {
      isMounted = false;
    };
  }, [waterBodyId]);

  if (loading) {
    return (
      <div style={{ marginTop: '0.6rem', padding: '0.45rem 0.6rem', background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: '3px', fontSize: '0.72rem', color: '#64748b' }}>
        <span style={{ display: 'inline-block', marginRight: '0.4rem' }}>🌤</span>
        Loading local weather...
      </div>
    );
  }

  if (error || !weather) {
    return null; // Gracefully omit without cluttering if unavailable
  }

  const { current, water_level_trend: trend } = weather;

  const getTrendColor = (t: string) => {
    if (t.includes('RISING')) return '#059669'; // Emerald
    if (t.includes('FALLING')) return '#d97706'; // Amber
    return '#0284c7'; // Blue
  };

  return (
    <div
      style={{
        marginTop: '0.65rem',
        padding: '0.55rem 0.75rem',
        background: '#f0fdf4',
        border: '1px solid #bbf7d0',
        borderRadius: '3px',
        fontSize: '0.72rem',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.35rem' }}>
        <span style={{ fontWeight: 700, color: '#166534', letterSpacing: '0.04em', textTransform: 'uppercase', fontSize: '0.68rem' }}>
          🌤 LOCAL WEATHER &amp; TREND
        </span>
        <span style={{ fontSize: '0.68rem', background: '#dcfce7', color: '#15803d', padding: '0.1rem 0.35rem', borderRadius: '2px', fontWeight: 600 }}>
          Open-Meteo
        </span>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.35rem', marginBottom: '0.4rem', color: '#334155' }}>
        <div>
          <span style={{ color: '#64748b', fontSize: '0.65rem', display: 'block' }}>Current Weather</span>
          <span style={{ fontWeight: 600, color: '#0f172a' }}>
            {current.temperature_c.toFixed(1)}°C · {current.condition}
          </span>
        </div>
        <div>
          <span style={{ color: '#64748b', fontSize: '0.65rem', display: 'block' }}>Rain Today / 7-Day</span>
          <span style={{ fontWeight: 600, color: '#0f172a' }}>
            {current.rain_mm.toFixed(1)} mm / {trend.forecast_rainfall_7d_mm} mm
          </span>
        </div>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderTop: '1px solid #dcfce7', paddingTop: '0.35rem' }}>
        <div>
          <span style={{ color: '#64748b', fontSize: '0.65rem', display: 'block' }}>Water-Level Trend</span>
          <span style={{ fontWeight: 700, color: getTrendColor(trend.trend) }}>
            {trend.trend_arrow} {trend.trend_label}
          </span>
        </div>

        {onNavigateToAnalysis && (
          <button
            onClick={() => onNavigateToAnalysis(waterBodyId)}
            style={{
              background: '#ffffff',
              border: '1px solid #86efac',
              color: '#166534',
              fontWeight: 700,
              fontSize: '0.65rem',
              padding: '0.25rem 0.5rem',
              borderRadius: '2px',
              cursor: 'pointer',
              boxShadow: '0 1px 2px rgba(0,0,0,0.05)',
            }}
          >
            View Forecast →
          </button>
        )}
      </div>
    </div>
  );
};
