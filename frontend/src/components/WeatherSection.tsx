import React, { useState, useEffect, useMemo } from 'react';
import './WeatherSection.css';
import {
  WeatherResponse,
  WeatherConditionCode,
  getWaterBodyWeather,
} from '../api/weather';

interface WeatherSectionProps {
  waterBodyId: string;
  waterBodyName?: string;
}

// ─── Weather SVG Icons ────────────────────────────────────────────────────────
const WeatherIcon: React.FC<{ code: WeatherConditionCode; size?: number }> = ({
  code,
  size = 32,
}) => {
  switch (code) {
    case 'clear':
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="#eab308" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="5" fill="#fef08a" />
          <line x1="12" y1="1" x2="12" y2="3" />
          <line x1="12" y1="21" x2="12" y2="23" />
          <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" />
          <line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
          <line x1="1" y1="12" x2="3" y2="12" />
          <line x1="21" y1="12" x2="23" y2="12" />
          <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" />
          <line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
        </svg>
      );
    case 'partly_cloudy':
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="#0284c7" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 2v2" stroke="#eab308" />
          <path d="M4.93 4.93l1.41 1.41" stroke="#eab308" />
          <path d="M20 12h2" stroke="#eab308" />
          <path d="M19.07 4.93l-1.41 1.41" stroke="#eab308" />
          <path d="M15.5 12a4.5 4.5 0 0 0-4.5-4.5 4.48 4.48 0 0 0-1.88.42" stroke="#eab308" />
          <path d="M17.5 19H9a5 5 0 0 1-.7-9.95A6 6 0 0 1 19.8 12a3.5 3.5 0 0 1-2.3 7z" fill="#e0f2fe" />
        </svg>
      );
    case 'overcast':
    case 'fog':
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="#475569" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z" fill="#f1f5f9" />
          {code === 'fog' && <line x1="4" y1="22" x2="20" y2="22" stroke="#94a3b8" strokeWidth="2" />}
        </svg>
      );
    case 'drizzle':
    case 'rain':
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="#0284c7" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M20 16.58A5 5 0 0 0 18 7h-1.26A8 8 0 1 0 4 15.25" fill="#f0f9ff" />
          <line x1="8" y1="19" x2="8" y2="22" stroke="#0ea5e9" strokeWidth="2" />
          <line x1="12" y1="17" x2="12" y2="22" stroke="#0ea5e9" strokeWidth="2" />
          <line x1="16" y1="19" x2="16" y2="22" stroke="#0ea5e9" strokeWidth="2" />
        </svg>
      );
    case 'heavy_rain':
    case 'thunderstorm':
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="#1e293b" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M19 14.58A5 5 0 0 0 17 5h-1.26A8 8 0 1 0 3 13.25" fill="#e2e8f0" />
          {code === 'thunderstorm' ? (
            <polygon points="13 11 9 17 12 17 11 23 16 16 13 16 13 11" fill="#eab308" stroke="#ca8a04" strokeWidth="1" />
          ) : (
            <>
              <line x1="8" y1="16" x2="6" y2="22" stroke="#0284c7" strokeWidth="2.5" />
              <line x1="12" y1="16" x2="10" y2="22" stroke="#0284c7" strokeWidth="2.5" />
              <line x1="16" y1="16" x2="14" y2="22" stroke="#0284c7" strokeWidth="2.5" />
            </>
          )}
        </svg>
      );
    case 'snow':
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="#0284c7" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M20 17.58A5 5 0 0 0 18 8h-1.26A8 8 0 1 0 4 16.25" fill="#f8fafc" />
          <line x1="8" y1="19" x2="8" y2="21" stroke="#38bdf8" strokeWidth="2" />
          <line x1="12" y1="18" x2="12" y2="21" stroke="#38bdf8" strokeWidth="2" />
          <line x1="16" y1="19" x2="16" y2="21" stroke="#38bdf8" strokeWidth="2" />
        </svg>
      );
    default:
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="#64748b" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="10" />
          <line x1="12" y1="8" x2="12" y2="12" />
          <line x1="12" y1="16" x2="12.01" y2="16" />
        </svg>
      );
  }
};

// ─── Formatters ───────────────────────────────────────────────────────────────
function formatDayLabel(dateStr: string, index: number): { day: string; date: string } {
  if (index === 0) {
    try {
      const d = new Date(dateStr + 'T00:00:00');
      const datePart = d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
      return { day: 'TODAY', date: datePart };
    } catch {
      return { day: 'TODAY', date: dateStr };
    }
  }
  try {
    const d = new Date(dateStr + 'T00:00:00');
    const dayName = d.toLocaleDateString(undefined, { weekday: 'short' }).toUpperCase();
    const datePart = d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
    return { day: dayName, date: datePart };
  } catch {
    return { day: dateStr, date: '' };
  }
}

function formatUpdatedTimestamp(isoStr: string): string {
  try {
    const d = new Date(isoStr);
    return d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  } catch {
    return 'Just now';
  }
}

export const WeatherSection: React.FC<WeatherSectionProps> = ({ waterBodyId, waterBodyName }) => {
  const [weather, setWeather] = useState<WeatherResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [refreshing, setRefreshing] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const fetchWeather = async (force: boolean = false) => {
    if (force) setRefreshing(true);
    else setLoading(true);
    setError(null);

    try {
      const data = await getWaterBodyWeather(waterBodyId, force);
      setWeather(data);
    } catch (err: any) {
      console.error('Weather retrieval error:', err);
      setError(err.message || 'Unable to retrieve meteorological forecast data.');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    if (waterBodyId) {
      fetchWeather(false);
    }
  }, [waterBodyId]);

  // Determine trend styling class
  const trendClass = useMemo(() => {
    if (!weather) return 'jn-trend-unknown';
    const t = weather.water_level_trend.trend;
    if (t === 'LIKELY_RISING' || t === 'POSSIBLY_RISING') return 'jn-trend-rising';
    if (t === 'LIKELY_FALLING' || t === 'POSSIBLY_FALLING') return 'jn-trend-falling';
    if (t === 'STABLE') return 'jn-trend-stable';
    return 'jn-trend-unknown';
  }, [weather]);

  const trendColor = useMemo(() => {
    if (!weather) return '#475569';
    const t = weather.water_level_trend.trend;
    if (t.includes('RISING')) return '#15803d';
    if (t.includes('FALLING')) return '#b45309';
    return '#0369a1';
  }, [weather]);

  if (loading) {
    return (
      <div className="jn-weather-dashboard" style={{ padding: '1.5rem', textAlign: 'center' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.65rem', color: '#0284c7', fontSize: '0.85rem', fontWeight: 600 }}>
          <span style={{ fontSize: '1.25rem', animation: 'spin 1.5s linear infinite' }}>⏳</span>
          <span>Connecting to Open-Meteo &amp; retrieving weather intelligence...</span>
        </div>
      </div>
    );
  }

  if (error || !weather) {
    return (
      <div className="jn-weather-dashboard">
        <div className="jn-weather-header">
          <div className="jn-weather-title-group">
            <div className="jn-weather-kicker">
              <span>🌤</span>
              <span>METEOROLOGICAL INTELLIGENCE</span>
            </div>
            <h3 className="jn-weather-title">
              Weather &amp; Water Forecast {waterBodyName ? `— ${waterBodyName}` : ''}
            </h3>
          </div>
          <div className="jn-weather-header-actions">
            <span className="jn-provider-badge">Open-Meteo</span>
            <button className="jn-refresh-btn" onClick={() => fetchWeather(true)}>
              ↻ Retry
            </button>
          </div>
        </div>
        <div style={{ padding: '1.25rem', backgroundColor: '#fef2f2', borderTop: '1px solid #fee2e2', color: '#991b1b', fontSize: '0.78rem' }}>
          <div style={{ fontWeight: 800, marginBottom: '0.25rem' }}>⚠️ WEATHER DATA UNAVAILABLE</div>
          <div>{error || 'Unable to retrieve meteorological forecast data.'}</div>
          <div style={{ marginTop: '0.5rem', fontSize: '0.72rem', color: '#7f1d1d' }}>
            Satellite monitoring, temporal comparisons, and spectral proxies remain fully operational.
          </div>
        </div>
      </div>
    );
  }

  const { current, forecast, water_level_trend: trend, location } = weather;
  const maxPrecip = Math.max(...forecast.map((d) => d.precipitation_mm), 10.0);
  const totalRain7d = trend.forecast_rainfall_7d_mm;
  const isAllZeroRain = forecast.every((d) => d.precipitation_mm === 0);

  return (
    <div className="jn-weather-dashboard">
      {/* ─── Header ─── */}
      <div className="jn-weather-header">
        <div className="jn-weather-title-group">
          <div className="jn-weather-kicker">
            <span>🌤</span>
            <span>METEOROLOGICAL INTELLIGENCE &amp; HYDROLOGICAL FORECAST</span>
          </div>
          <h3 className="jn-weather-title">
            Weather &amp; Water Forecast {waterBodyName ? `— ${waterBodyName}` : ''}
          </h3>
          <div className="jn-weather-meta">
            <span>Centroid: {location.latitude.toFixed(3)}°N, {location.longitude.toFixed(3)}°E</span>
            <span>•</span>
            <span>Timezone: {location.timezone}</span>
            <span>•</span>
            <span>Updated: {formatUpdatedTimestamp(weather.fetched_at)}</span>
          </div>
        </div>

        <div className="jn-weather-header-actions">
          <span className="jn-provider-badge">
            <span style={{ display: 'inline-block', width: '6px', height: '6px', borderRadius: '50%', backgroundColor: '#0284c7' }} />
            Open-Meteo · Live Forecast
          </span>
          <button
            className="jn-refresh-btn"
            onClick={() => fetchWeather(true)}
            disabled={refreshing}
            title="Bypass cache and query Open-Meteo"
          >
            <span style={{ display: 'inline-block', transform: refreshing ? 'rotate(180deg)' : 'none', transition: 'transform 0.3s' }}>
              ↻
            </span>
            <span>{refreshing ? 'Updating...' : 'Refresh'}</span>
          </button>
        </div>
      </div>

      <div className="jn-weather-body">
        {/* ─── Top Row: Current Weather & Qualitative Trend ─── */}
        <div className="jn-top-row">
          {/* Card 1: Current Weather Conditions */}
          <div className="jn-card" style={{ display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
            <div>
              <div className="jn-card-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span className="jn-card-label">CURRENT WEATHER CONDITIONS</span>
                <span style={{ fontSize: '0.68rem', fontWeight: 700, backgroundColor: '#f1f5f9', color: '#334155', padding: '0.15rem 0.45rem', borderRadius: '2px' }}>
                  {current.condition}
                </span>
              </div>

              <div className="jn-current-display" style={{ display: 'flex', alignItems: 'center', gap: '1.25rem' }}>
                <WeatherIcon code={current.condition_code} size={52} />
                <div>
                  <div className="jn-current-temp" style={{ fontSize: '2.5rem', fontWeight: 800, color: '#0f172a' }}>
                    {current.temperature_c.toFixed(1)}°C
                  </div>
                  <div className="jn-current-condition" style={{ fontSize: '0.85rem', fontWeight: 700, color: '#334155' }}>
                    {current.condition}
                  </div>
                  <div className="jn-current-feels" style={{ fontSize: '0.72rem', color: '#64748b' }}>
                    Feels like {current.apparent_temperature_c.toFixed(1)}°C
                  </div>
                </div>
              </div>
            </div>

            {/* 2x2 Metric Grid with explicit spacing */}
            <div className="jn-metrics-grid" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem', borderTop: '1px solid #f1f5f9', paddingTop: '0.85rem' }}>
              <div className="jn-metric-item">
                <span className="jn-metric-label" style={{ fontSize: '0.68rem', color: '#64748b', display: 'block', marginBottom: '0.15rem' }}>Relative Humidity</span>
                <span className="jn-metric-value" style={{ fontSize: '0.95rem', fontWeight: 700, color: '#0f172a' }}>{current.humidity_percent}%</span>
              </div>
              <div className="jn-metric-item">
                <span className="jn-metric-label" style={{ fontSize: '0.68rem', color: '#64748b', display: 'block', marginBottom: '0.15rem' }}>Rainfall Today</span>
                <span className="jn-metric-value" style={{ fontSize: '0.95rem', fontWeight: 700, color: '#0f172a' }}>{current.rain_mm.toFixed(1)} mm</span>
              </div>
              <div className="jn-metric-item">
                <span className="jn-metric-label" style={{ fontSize: '0.68rem', color: '#64748b', display: 'block', marginBottom: '0.15rem' }}>Cloud Cover</span>
                <span className="jn-metric-value" style={{ fontSize: '0.95rem', fontWeight: 700, color: '#0f172a' }}>{current.cloud_cover_percent}%</span>
              </div>
              <div className="jn-metric-item">
                <span className="jn-metric-label" style={{ fontSize: '0.68rem', color: '#64748b', display: 'block', marginBottom: '0.15rem' }}>Wind Speed</span>
                <span className="jn-metric-value" style={{ fontSize: '0.95rem', fontWeight: 700, color: '#0f172a' }}>
                  {current.wind_speed_kmh.toFixed(1)} km/h {current.wind_direction_deg ? `(${current.wind_direction_deg}°)` : ''}
                </span>
              </div>
            </div>
          </div>

          {/* Card 2: Water-Level Trend Signal Card */}
          <div className={`jn-trend-card ${trendClass}`} style={{ display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
            <div>
              <div className="jn-card-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span className="jn-card-label">WATER-LEVEL TREND OUTLOOK</span>
                <span style={{ fontSize: '0.68rem', fontWeight: 800, textTransform: 'uppercase', color: trendColor }}>
                  {trend.confidence} Confidence
                </span>
              </div>

              {/* Big Visual Signal */}
              <div className="jn-trend-hero" style={{ display: 'flex', alignItems: 'center', gap: '1rem', margin: '0.5rem 0 1rem' }}>
                <div className="jn-trend-arrow-box" style={{ color: trendColor, fontSize: '2rem', minWidth: '54px', height: '54px', display: 'flex', alignItems: 'center', justifyContent: 'center', backgroundColor: '#ffffff', border: '1px solid #cbd5e1' }}>
                  {trend.trend_arrow}
                </div>
                <div>
                  <div className="jn-trend-status-title" style={{ fontSize: '1.25rem', fontWeight: 900, color: trendColor, letterSpacing: '0.01em' }}>
                    {trend.trend_label}
                  </div>
                  <div className="jn-trend-status-sub" style={{ fontSize: '0.72rem', color: '#475569', marginTop: '0.15rem' }}>
                    Rainfall-driven hydrological tendency
                  </div>
                </div>
              </div>

              {/* 4 Factor Badges */}
              <div className="jn-trend-factors-grid">
                <div>
                  <span style={{ fontSize: '0.62rem', color: '#64748b', display: 'block', textTransform: 'uppercase', fontWeight: 700 }}>Dryness Impact</span>
                  <span style={{ fontSize: '0.8rem', fontWeight: 800, color: '#0f172a' }}>{trend.dryness_impact}</span>
                </div>
                <div>
                  <span style={{ fontSize: '0.62rem', color: '#64748b', display: 'block', textTransform: 'uppercase', fontWeight: 700 }}>Rainfall Impact</span>
                  <span style={{ fontSize: '0.8rem', fontWeight: 800, color: '#0f172a' }}>{trend.rainfall_impact}</span>
                </div>
                <div>
                  <span style={{ fontSize: '0.62rem', color: '#64748b', display: 'block', textTransform: 'uppercase', fontWeight: 700 }}>7-Day Rain</span>
                  <span style={{ fontSize: '0.8rem', fontWeight: 800, color: '#0f172a' }}>{trend.forecast_rainfall_7d_mm} mm</span>
                </div>
                <div>
                  <span style={{ fontSize: '0.62rem', color: '#64748b', display: 'block', textTransform: 'uppercase', fontWeight: 700 }}>Confidence</span>
                  <span style={{ fontSize: '0.8rem', fontWeight: 800, color: '#0f172a' }}>{trend.confidence}</span>
                </div>
              </div>

              <div className="jn-trend-reason" style={{ fontSize: '0.74rem', lineHeight: 1.45, color: '#1e293b', marginBottom: '0.6rem' }}>
                {trend.reason}
              </div>
            </div>

            <div className="jn-trend-disclaimer" style={{ fontSize: '0.65rem', color: '#64748b', fontStyle: 'italic', borderTop: '1px dashed rgba(0,0,0,0.15)', paddingTop: '0.45rem' }}>
              ℹ️ Weather-based inference — not a physical water-depth gauge measurement.
            </div>
          </div>
        </div>

        {/* ─── 7-Day Forecast Strip ─── */}
        <div>
          <div className="jn-section-title-row" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
            <span className="jn-section-title">
              <span>📅</span> 7-DAY METEOROLOGICAL FORECAST
            </span>
            <span className="jn-section-hint">Scroll horizontally on smaller screens →</span>
          </div>

          <div className="jn-forecast-scroll-container" style={{ overflowX: 'auto', width: '100%', WebkitOverflowScrolling: 'touch' }}>
            <div
              className="jn-forecast-strip"
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(7, minmax(125px, 1fr))',
                gap: '0.65rem',
                minWidth: '890px',
              }}
            >
              {forecast.map((day, idx) => {
                const dayMeta = formatDayLabel(day.date, idx);
                const hasRain = day.precipitation_mm > 0;

                return (
                  <div
                    key={day.date}
                    className={`jn-forecast-card ${idx === 0 ? 'is-today' : ''}`}
                    style={{
                      display: 'flex',
                      flexDirection: 'column',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      padding: '0.75rem 0.5rem',
                      border: idx === 0 ? '2px solid #86efac' : '1px solid #cbd5e1',
                      backgroundColor: idx === 0 ? '#f0fdf4' : '#f8fafc',
                    }}
                  >
                    <div>
                      <div className="jn-forecast-day-label" style={{ fontSize: '0.72rem', fontWeight: 800, color: '#0f172a' }}>
                        {dayMeta.day}
                      </div>
                      <div className="jn-forecast-date-sub" style={{ fontSize: '0.65rem', color: '#64748b', marginBottom: '0.35rem' }}>
                        {dayMeta.date}
                      </div>
                    </div>

                    <div className="jn-forecast-icon-wrapper" style={{ margin: '0.25rem 0', height: '36px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                      <WeatherIcon code={day.condition_code} size={30} />
                    </div>

                    <div className="jn-forecast-condition" style={{ fontSize: '0.68rem', fontWeight: 600, color: '#334155', minHeight: '1.2rem', textAlign: 'center' }}>
                      {day.condition}
                    </div>

                    <div className="jn-forecast-temps" style={{ fontSize: '0.85rem', fontWeight: 800, color: '#0f172a', margin: '0.25rem 0' }}>
                      {Math.round(day.temp_max_c)}° / <span className="jn-forecast-temp-min" style={{ color: '#64748b', fontWeight: 500 }}>{Math.round(day.temp_min_c)}°</span>
                    </div>

                    <div>
                      <div className={`jn-forecast-rain-pill ${hasRain ? 'jn-forecast-rain-has' : 'jn-forecast-rain-none'}`} style={{ display: 'inline-flex', alignItems: 'center', gap: '0.25rem', padding: '0.15rem 0.45rem', fontSize: '0.68rem', fontWeight: 700 }}>
                        <span>💧</span>
                        <span>{day.precipitation_mm.toFixed(1)} mm</span>
                      </div>

                      <div className="jn-forecast-prob" style={{ fontSize: '0.65rem', color: '#64748b', marginTop: '0.2rem' }}>
                        {day.precipitation_probability_max != null ? `${day.precipitation_probability_max}% rain` : '0% rain'}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        {/* ─── Forecast Rainfall Chart & Probability ─── */}
        <div className="jn-chart-panel" style={{ backgroundColor: '#f8fafc', border: '1px solid #cbd5e1', padding: '1.15rem' }}>
          <div className="jn-chart-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem', marginBottom: '1rem' }}>
            <div>
              <span className="jn-section-title" style={{ fontSize: '0.75rem', fontWeight: 800 }}>
                <span>🌧</span> FORECAST RAINFALL ACCUMULATION
              </span>
              <span style={{ fontSize: '0.68rem', color: '#64748b', display: 'block', marginTop: '0.15rem' }}>
                Projected 7-day precipitation distribution in millimeters (mm)
              </span>
            </div>

            <div className="jn-chart-summary-stats" style={{ display: 'flex', gap: '1.5rem', alignItems: 'center' }}>
              <div className="jn-chart-stat-item">
                <span className="jn-chart-stat-label">7-Day Total</span>
                <span className="jn-chart-stat-val" style={{ color: totalRain7d > 0 ? '#0284c7' : '#0f172a' }}>
                  {totalRain7d.toFixed(1)} mm
                </span>
              </div>
              <div className="jn-chart-stat-item">
                <span className="jn-chart-stat-label">Wettest Day</span>
                <span className="jn-chart-stat-val">
                  {trend.wettest_day_date ? `${trend.wettest_day_rainfall_mm} mm (${trend.wettest_day_date})` : 'None (0 mm)'}
                </span>
              </div>
              <div className="jn-chart-stat-item">
                <span className="jn-chart-stat-label">Rain Probability</span>
                <span className="jn-chart-stat-val">{trend.rain_probability_label}</span>
              </div>
            </div>
          </div>

          {/* SVG Bar Chart with proper height & visible bars */}
          <div className="jn-chart-svg-container" style={{ width: '100%', height: '175px', backgroundColor: '#ffffff', border: '1px solid #e2e8f0', padding: '0.5rem' }}>
            <svg viewBox="0 0 700 130" style={{ width: '100%', height: '100%', overflow: 'visible' }}>
              {/* Gridlines */}
              <line x1="45" y1="20" x2="685" y2="20" stroke="#f1f5f9" strokeWidth="1" />
              <line x1="45" y1="58" x2="685" y2="58" stroke="#f1f5f9" strokeWidth="1" />
              <line x1="45" y1="96" x2="685" y2="96" stroke="#cbd5e1" strokeWidth="1.5" />

              {/* Y-axis Labels */}
              <text x="36" y="24" textAnchor="end" fontSize="10" fill="#94a3b8" fontFamily="monospace">
                {maxPrecip.toFixed(0)}mm
              </text>
              <text x="36" y="62" textAnchor="end" fontSize="10" fill="#94a3b8" fontFamily="monospace">
                {(maxPrecip / 2).toFixed(0)}mm
              </text>
              <text x="36" y="100" textAnchor="end" fontSize="10" fill="#64748b" fontWeight="600" fontFamily="monospace">
                0mm
              </text>

              {/* Bars for 7 days */}
              {forecast.map((day, idx) => {
                const x = 55 + idx * 88;
                const barWidth = 48;
                const barHeight = (day.precipitation_mm / maxPrecip) * 76;
                const y = 96 - barHeight;
                const hasRain = day.precipitation_mm > 0;
                const dayMeta = formatDayLabel(day.date, idx);

                return (
                  <g key={day.date}>
                    {/* Bar background track */}
                    <rect x={x} y="20" width={barWidth} height="76" fill="#f8fafc" rx="1" />

                    {/* Active Bar */}
                    {hasRain ? (
                      <rect
                        x={x}
                        y={y}
                        width={barWidth}
                        height={Math.max(barHeight, 4)}
                        fill="#0284c7"
                        rx="1"
                      />
                    ) : (
                      /* Zero indicator line */
                      <line x1={x + 4} y1="95" x2={x + barWidth - 4} y2="95" stroke="#94a3b8" strokeWidth="2" strokeDasharray="2 2" />
                    )}

                    {/* Value label above bar */}
                    <text
                      x={x + barWidth / 2}
                      y={hasRain ? Math.max(y - 5, 14) : 90}
                      textAnchor="middle"
                      fontSize="9.5"
                      fill={hasRain ? '#0369a1' : '#94a3b8'}
                      fontWeight={hasRain ? '700' : '500'}
                      fontFamily="monospace"
                    >
                      {day.precipitation_mm.toFixed(1)}
                    </text>

                    {/* X-axis Day Label */}
                    <text
                      x={x + barWidth / 2}
                      y="114"
                      textAnchor="middle"
                      fontSize="10"
                      fill="#334155"
                      fontWeight="700"
                    >
                      {dayMeta.day}
                    </text>
                  </g>
                );
              })}
            </svg>
          </div>

          {/* Zero Rain Explicit Banner */}
          {isAllZeroRain && (
            <div className="jn-zero-rain-banner">
              <span>☀️</span>
              <span>
                <strong>0 mm Expected:</strong> No measurable rainfall is currently forecast for the next 7 days.
              </span>
            </div>
          )}
        </div>

        {/* ─── Bottom Row: Weather Impact Flow & Satellite Baseline ─── */}
        <div className="jn-impact-flow-panel">
          {/* Panel 1: Environmental Flow */}
          <div className="jn-card">
            <span className="jn-section-title">
              <span>🔄</span> WEATHER IMPACT ON WATER EXTENT
            </span>
            <div className="jn-flow-steps-container">
              <div className="jn-flow-step">
                <div className="jn-flow-step-num">Step 1</div>
                <div className="jn-flow-step-label">Meteorology</div>
                <div className="jn-flow-step-desc">
                  {current.condition} · {current.temperature_c.toFixed(0)}°C
                </div>
              </div>
              <div className="jn-flow-step">
                <div className="jn-flow-step-num">Step 2</div>
                <div className="jn-flow-step-label">Precipitation</div>
                <div className="jn-flow-step-desc">
                  {totalRain7d.toFixed(1)} mm (7 days)
                </div>
              </div>
              <div className="jn-flow-step">
                <div className="jn-flow-step-num">Step 3</div>
                <div className="jn-flow-step-label">Response</div>
                <div className="jn-flow-step-desc">
                  {trend.expected_response}
                </div>
              </div>
              <div className="jn-flow-step" style={{ backgroundColor: trendClass === 'jn-trend-rising' ? '#f0fdf4' : (trendClass === 'jn-trend-falling' ? '#fffbeb' : '#f0f9ff'), borderColor: trendColor }}>
                <div className="jn-flow-step-num" style={{ color: trendColor }}>Outcome</div>
                <div className="jn-flow-step-label" style={{ color: trendColor, fontWeight: 800 }}>
                  {trend.trend_arrow} {trend.trend_label}
                </div>
                <div className="jn-flow-step-desc">
                  {trend.confidence} confidence
                </div>
              </div>
            </div>
          </div>

          {/* Panel 2: Satellite Baseline Integration */}
          <div className="jn-baseline-card">
            <div>
              <span className="jn-section-title" style={{ marginBottom: '0.4rem' }}>
                <span>🛰</span> SATELLITE BASELINE
              </span>
              <div style={{ fontSize: '0.72rem', color: '#475569', lineHeight: 1.45, marginTop: '0.4rem' }}>
                {trend.satellite_baseline_detail || 'No recent satellite observation baseline available.'}
              </div>
            </div>
            <div style={{ marginTop: '0.65rem', paddingTop: '0.4rem', borderTop: '1px solid #e2e8f0', fontSize: '0.68rem', color: '#64748b' }}>
              Status: <strong style={{ color: trend.satellite_baseline_status === 'available' ? '#15803d' : '#64748b' }}>
                {trend.satellite_baseline_status.toUpperCase()}
              </strong>
            </div>
          </div>
        </div>

        {/* ─── Bottom Callout: What This Means ─── */}
        <div className="jn-summary-callout">
          <strong style={{ color: '#0f172a', display: 'block', marginBottom: '0.2rem' }}>
            WHAT THIS MEANS FOR ENVIRONMENTAL MONITORING:
          </strong>
          {totalRain7d < 2.0 ? (
            <span>
              Low or zero precipitation is forecast over the next 7 days. Under persistent dry and warm conditions,
              evaporation will dominate and surface water extent may contract gradually.
              This inference guides ground-truth inspections and is not a direct physical water-depth measurement.
            </span>
          ) : (
            <span>
              Forecast rainfall of {totalRain7d.toFixed(1)} mm is anticipated over the 7-day period. Runoff may temporarily expand
              surface water spread and elevate sediment turbidity proxies (NDTI). Remote sensing observations will confirm physical retention.
            </span>
          )}
        </div>
      </div>
    </div>
  );
};
