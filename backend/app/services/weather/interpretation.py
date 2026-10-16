import logging
from typing import List, Optional, Tuple
from app.services.weather.models import (
    DailyForecastItem,
    WaterLevelTrend,
    WaterLevelTrendInterpretation,
    ImpactLevel,
    ConfidenceLevel,
)

logger = logging.getLogger("jalnetra.weather.interpretation")


class WaterLevelTrendEngine:
    """
    Interpretable Rainfall-Driven Water-Level Trend Engine.
    Combines Open-Meteo multi-day meteorological forecast factors with
    recent satellite-derived apparent water extent observations to determine
    qualitative environmental expansion or contraction tendencies.

    CRITICAL SCIENTIFIC PRINCIPLE:
    This engine derives environmental tendencies from weather and satellite proxies.
    It NEVER fabricates numerical water depths, reservoir elevations, or volumes.
    """

    @classmethod
    def calculate_trend(
        cls,
        forecast: List[DailyForecastItem],
        recent_apparent_extents: Optional[List[Tuple[str, float]]] = None,
        # List of (sensing_date_str, apparent_extent_sq_km)
    ) -> WaterLevelTrendInterpretation:
        """
        Calculates an interpretable rainfall-driven water-level trend.
        """
        if not forecast:
            return WaterLevelTrendInterpretation(
                trend=WaterLevelTrend.INSUFFICIENT_DATA,
                trend_arrow="—",
                trend_label="Insufficient Data",
                internal_score=0,
                confidence=ConfidenceLevel.LOW,
                rainfall_impact=ImpactLevel.NONE,
                dryness_impact=ImpactLevel.NONE,
                forecast_rainfall_7d_mm=0.0,
                wettest_day_date=None,
                wettest_day_rainfall_mm=None,
                rain_probability_label="Unknown",
                reason="Insufficient meteorological forecast data to project a trend.",
                expected_response="No trend projection possible at this time.",
                satellite_baseline_status="unavailable",
                satellite_baseline_detail="No meteorological forecast received.",
            )

        # 1. Weather Factors Analysis
        total_precip_7d = sum(day.precipitation_mm for day in forecast)
        rainy_days_count = sum(1 for day in forecast if day.precipitation_mm >= 1.0)
        heavy_rainy_days = sum(1 for day in forecast if day.precipitation_mm >= 10.0)

        # Find wettest day
        wettest_day = max(forecast, key=lambda d: d.precipitation_mm, default=forecast[0])
        wettest_date = wettest_day.date if wettest_day.precipitation_mm > 0 else None
        wettest_mm = wettest_day.precipitation_mm if wettest_day.precipitation_mm > 0 else 0.0

        # Maximum rain probability
        probs = [d.precipitation_probability_max for d in forecast if d.precipitation_probability_max is not None]
        max_prob = max(probs) if probs else 0

        if max_prob >= 70:
            prob_label = "High"
        elif max_prob >= 40:
            prob_label = "Moderate"
        elif max_prob >= 15:
            prob_label = "Low"
        else:
            prob_label = "Very Low"

        # Dry & sunny factors
        dry_days_count = sum(1 for day in forecast if day.precipitation_mm < 0.5)
        avg_temp_max = sum(day.temp_max_c for day in forecast) / len(forecast) if forecast else 25.0
        avg_sunshine = sum(day.sunshine_duration_hours or 0.0 for day in forecast) / len(forecast) if forecast else 0.0
        total_et0 = sum(day.et0_evapotranspiration_mm or 0.0 for day in forecast)

        # 2. Meteorological Component Score (-70 to +70)
        weather_score = 0.0

        # Rainfall contribution (+0 to +60)
        if total_precip_7d >= 60.0:
            weather_score += 60.0
            rainfall_impact = ImpactLevel.HIGH
        elif total_precip_7d >= 30.0:
            weather_score += 45.0
            rainfall_impact = ImpactLevel.HIGH
        elif total_precip_7d >= 15.0:
            weather_score += 30.0
            rainfall_impact = ImpactLevel.MODERATE
        elif total_precip_7d >= 5.0:
            weather_score += 15.0
            rainfall_impact = ImpactLevel.LOW
        elif total_precip_7d >= 1.0:
            weather_score += 5.0
            rainfall_impact = ImpactLevel.LOW
        else:
            weather_score += 0.0
            rainfall_impact = ImpactLevel.NONE

        # Consecutive / concentrated rainfall boost (+0 to +10)
        if heavy_rainy_days >= 2 or (total_precip_7d >= 20.0 and max_prob >= 75):
            weather_score += 10.0

        # Dryness contribution (-0 to -60)
        if total_precip_7d < 2.0 and dry_days_count >= 5:
            if avg_temp_max >= 32.0 or avg_sunshine >= 8.0 or total_et0 >= 25.0:
                weather_score -= 55.0
                dryness_impact = ImpactLevel.HIGH
            else:
                weather_score -= 40.0
                dryness_impact = ImpactLevel.HIGH
        elif total_precip_7d < 6.0 and dry_days_count >= 4:
            weather_score -= 25.0
            dryness_impact = ImpactLevel.MODERATE
        elif total_precip_7d < 12.0:
            dryness_impact = ImpactLevel.LOW
        else:
            dryness_impact = ImpactLevel.NONE

        # 3. Satellite Water Extent Baseline Component (-30 to +30)
        satellite_baseline_status = "unavailable"
        satellite_baseline_detail = None
        satellite_score = 0.0
        satellite_trend_text = "unavailable"

        if recent_apparent_extents and len(recent_apparent_extents) >= 1:
            valid_extents = [(d, a) for (d, a) in recent_apparent_extents if a is not None and a > 0]
            if valid_extents:
                satellite_baseline_status = "available"
                latest_date, latest_extent = valid_extents[-1]

                if len(valid_extents) >= 2:
                    prev_date, prev_extent = valid_extents[-2]
                    delta = latest_extent - prev_extent
                    pct_change = (delta / prev_extent) * 100.0 if prev_extent > 0 else 0.0

                    if pct_change >= 4.0:
                        satellite_score += 25.0
                        satellite_trend_text = "expanding"
                        satellite_baseline_detail = (
                            f"Recent satellite observation ({latest_date}) shows expanding apparent water extent "
                            f"({latest_extent:.3f} km², +{pct_change:.1f}% vs {prev_date})."
                        )
                    elif pct_change <= -4.0:
                        satellite_score -= 25.0
                        satellite_trend_text = "contracting"
                        satellite_baseline_detail = (
                            f"Recent satellite observation ({latest_date}) shows contracting apparent water extent "
                            f"({latest_extent:.3f} km², {pct_change:.1f}% vs {prev_date})."
                        )
                    else:
                        satellite_trend_text = "stable"
                        satellite_baseline_detail = (
                            f"Recent satellite observations ({prev_date} → {latest_date}) indicate stable apparent extent "
                            f"around {latest_extent:.3f} km²."
                        )
                else:
                    satellite_trend_text = "single_baseline"
                    satellite_baseline_detail = (
                        f"Latest satellite observation ({latest_date}) confirms apparent water extent of {latest_extent:.3f} km²."
                    )
                    # Gentle neutral baseline
                    satellite_score = 0.0

        if satellite_baseline_status == "unavailable":
            satellite_baseline_detail = "No recent satellite observation baseline available; trend inferred from meteorology only."

        # 4. Total Internal Score (-100 to +100)
        raw_score = weather_score + satellite_score
        total_score = int(round(max(-100.0, min(100.0, raw_score))))

        # 5. Determine Trend Category
        if total_score >= 45:
            trend = WaterLevelTrend.LIKELY_RISING
            trend_arrow = "↑"
            trend_label = "Likely Rising"
            expected_response = "Water extent and reservoir surface area may increase following the forecast rainfall."
        elif total_score >= 18:
            trend = WaterLevelTrend.POSSIBLY_RISING
            trend_arrow = "↗"
            trend_label = "Moderate Chance of Expansion"
            expected_response = "Moderate chance of surface expansion if forecast precipitation materializes."
        elif total_score <= -45:
            trend = WaterLevelTrend.LIKELY_FALLING
            trend_arrow = "↓"
            trend_label = "Likely Falling"
            expected_response = "Water extent may gradually contract due to sustained dryness and evaporation."
        elif total_score <= -18:
            trend = WaterLevelTrend.POSSIBLY_FALLING
            trend_arrow = "↘"
            trend_label = "Possible Decline During Dry Conditions"
            expected_response = "Surface area may experience gradual seasonal decline under predominantly dry conditions."
        else:
            trend = WaterLevelTrend.STABLE
            trend_arrow = "→"
            trend_label = "Likely Stable"
            expected_response = "No strong weather-driven expansion or contraction signal detected across the 7-day period."

        # 6. Determine Confidence
        # Higher confidence when weather forecast and satellite baseline agree
        if satellite_baseline_status == "available":
            if (trend in (WaterLevelTrend.LIKELY_RISING, WaterLevelTrend.POSSIBLY_RISING) and satellite_trend_text == "expanding") or \
               (trend in (WaterLevelTrend.LIKELY_FALLING, WaterLevelTrend.POSSIBLY_FALLING) and satellite_trend_text == "contracting") or \
               (trend == WaterLevelTrend.STABLE and satellite_trend_text == "stable"):
                confidence = ConfidenceLevel.HIGH if max_prob >= 60 or dry_days_count >= 5 else ConfidenceLevel.MODERATE
            else:
                confidence = ConfidenceLevel.MODERATE
        else:
            # Weather-only trend
            confidence = ConfidenceLevel.LOW if max_prob < 50 and total_precip_7d > 0 else ConfidenceLevel.MODERATE

        # 7. Construct Reason Narrative
        reasons = []
        if total_precip_7d >= 20.0:
            reasons.append(f"Significant precipitation is forecast over the next 7 days ({total_precip_7d:.1f} mm total).")
            if wettest_date and wettest_mm >= 10.0:
                reasons.append(f"Wettest day is anticipated on {wettest_date} ({wettest_mm:.1f} mm).")
        elif total_precip_7d >= 5.0:
            reasons.append(f"Light to moderate rainfall is forecast ({total_precip_7d:.1f} mm across {rainy_days_count} day{'s' if rainy_days_count != 1 else ''}).")
        elif dry_days_count >= 5:
            reasons.append(f"Persistent dry conditions with {dry_days_count} rainless days and average daytime highs of {avg_temp_max:.1f}°C.")
        else:
            reasons.append("Moderate meteorological conditions with low precipitation impact forecast.")

        if satellite_baseline_status == "available" and satellite_trend_text in ("expanding", "contracting"):
            reasons.append(f"Aligned with recent satellite observation trends ({satellite_trend_text} baseline).")
        elif satellite_baseline_status == "unavailable":
            reasons.append("Satellite baseline unavailable. Weather-based trend only.")

        reason_str = " ".join(reasons)

        return WaterLevelTrendInterpretation(
            trend=trend,
            trend_arrow=trend_arrow,
            trend_label=trend_label,
            internal_score=total_score,
            confidence=confidence,
            rainfall_impact=rainfall_impact,
            dryness_impact=dryness_impact,
            forecast_rainfall_7d_mm=round(total_precip_7d, 1),
            wettest_day_date=wettest_date,
            wettest_day_rainfall_mm=round(wettest_mm, 1) if wettest_mm > 0 else None,
            rain_probability_label=prob_label,
            reason=reason_str,
            expected_response=expected_response,
            satellite_baseline_status=satellite_baseline_status,
            satellite_baseline_detail=satellite_baseline_detail,
        )
