import { resolveApiUrl } from './client';

export type WeatherConditionCode =
  | 'clear'
  | 'partly_cloudy'
  | 'overcast'
  | 'fog'
  | 'drizzle'
  | 'rain'
  | 'heavy_rain'
  | 'thunderstorm'
  | 'snow'
  | 'unknown';

export type WaterLevelTrendType =
  | 'LIKELY_RISING'
  | 'POSSIBLY_RISING'
  | 'STABLE'
  | 'POSSIBLY_FALLING'
  | 'LIKELY_FALLING'
  | 'INSUFFICIENT_DATA';

export type ImpactLevel = 'HIGH' | 'MODERATE' | 'LOW' | 'NONE';
export type ConfidenceLevel = 'High' | 'Moderate' | 'Low';

export interface CurrentWeather {
  temperature_c: number;
  apparent_temperature_c: number;
  humidity_percent: number;
  precipitation_mm: number;
  rain_mm: number;
  cloud_cover_percent: number;
  wind_speed_kmh: number;
  wind_direction_deg?: number | null;
  weather_code: number;
  condition: string;
  condition_code: WeatherConditionCode;
}

export interface DailyForecastItem {
  date: string;
  weather_code: number;
  condition: string;
  condition_code: WeatherConditionCode;
  temp_max_c: number;
  temp_min_c: number;
  precipitation_mm: number;
  rain_mm: number;
  precipitation_probability_max?: number | null;
  wind_speed_max_kmh?: number | null;
  sunshine_duration_hours?: number | null;
  et0_evapotranspiration_mm?: number | null;
}

export interface WaterLevelTrendInterpretation {
  trend: WaterLevelTrendType;
  trend_arrow: string;
  trend_label: string;
  internal_score: number;
  confidence: ConfidenceLevel;
  rainfall_impact: ImpactLevel;
  dryness_impact: ImpactLevel;
  forecast_rainfall_7d_mm: number;
  wettest_day_date?: string | null;
  wettest_day_rainfall_mm?: number | null;
  rain_probability_label: string;
  reason: string;
  expected_response: string;
  satellite_baseline_status: string;
  satellite_baseline_detail?: string | null;
  disclaimer: string;
}

export interface LocationInfo {
  latitude: number;
  longitude: number;
  timezone: string;
}

export interface WeatherResponse {
  water_body_id: string;
  water_body_name: string;
  location: LocationInfo;
  provider: string;
  current: CurrentWeather;
  forecast: DailyForecastItem[];
  water_level_trend: WaterLevelTrendInterpretation;
  fetched_at: string;
}

export interface WeatherImpactResponse {
  water_body_id: string;
  water_body_name: string;
  provider: string;
  water_level_trend: WaterLevelTrendInterpretation;
  fetched_at: string;
}

export interface WeatherStatusResponse {
  enabled: boolean;
  provider: string;
  configured: boolean;
  requires_api_key: boolean;
  details: string;
}

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let msg = `Server returned ${res.status}`;
    try {
      const data = await res.json();
      if (data?.detail) {
        msg = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail);
      } else if (data?.error?.message) {
        msg = data.error.message;
      }
    } catch {
      // fallback
    }
    throw new Error(msg);
  }
  return res.json();
}

export async function getWeatherStatus(): Promise<WeatherStatusResponse> {
  const url = resolveApiUrl('/api/v1/weather/status');
  const res = await fetch(url, { headers: { Accept: 'application/json' } });
  return handleResponse<WeatherStatusResponse>(res);
}

export async function getWaterBodyWeather(
  waterBodyId: string,
  forceRefresh: boolean = false
): Promise<WeatherResponse> {
  const param = forceRefresh ? '?force_refresh=true' : '';
  const url = resolveApiUrl(`/api/v1/weather/water-bodies/${waterBodyId}${param}`);
  const res = await fetch(url, { headers: { Accept: 'application/json' } });
  return handleResponse<WeatherResponse>(res);
}

export async function getWaterBodyForecast(waterBodyId: string): Promise<DailyForecastItem[]> {
  const url = resolveApiUrl(`/api/v1/weather/water-bodies/${waterBodyId}/forecast`);
  const res = await fetch(url, { headers: { Accept: 'application/json' } });
  return handleResponse<DailyForecastItem[]>(res);
}

export async function getWaterBodyWeatherImpact(waterBodyId: string): Promise<WeatherImpactResponse> {
  const url = resolveApiUrl(`/api/v1/weather/water-bodies/${waterBodyId}/impact`);
  const res = await fetch(url, { headers: { Accept: 'application/json' } });
  return handleResponse<WeatherImpactResponse>(res);
}
