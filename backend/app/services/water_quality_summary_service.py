from dataclasses import dataclass
from typing import Dict, Optional, Any


@dataclass
class WaterQualitySummary:
    label: str
    simple_view: str
    is_remote_sensing_proxy: bool = True
    disclaimer: str = "Remote-sensing optical proxy; does not substitute for laboratory testing or confirm potable water safety."


class WaterQualitySummaryService:
    """
    Translates available JalNetra spectral and optical indicators (NDTI, NDCI, FAI, Anomaly)
    into simple, cautious, human-readable summaries without fabricating laboratory claims.
    """

    @staticmethod
    def summarize_indicators(
        indicators: Optional[Dict[str, Any]] = None,
        has_clear_observation: bool = False,
    ) -> WaterQualitySummary:
        if not indicators:
            if has_clear_observation:
                return WaterQualitySummary(
                    label="Visually observed",
                    simple_view="Optical observation recorded; full spectral indicators have not been calculated yet.",
                )
            return WaterQualitySummary(
                label="Insufficient data",
                simple_view="No reliable water-quality indicator is currently available.",
            )

        # Retrieve individual indicator results if available
        anomaly_obj = indicators.get("anomaly")
        fai_obj = indicators.get("fai")
        ndci_obj = indicators.get("ndci")
        ndti_obj = indicators.get("ndti")

        def get_cls(obj) -> str:
            if not obj:
                return ""
            if isinstance(obj, dict):
                return (obj.get("classification") or "").upper()
            return (getattr(obj, "classification", "") or "").upper()

        anomaly_cls = get_cls(anomaly_obj)
        fai_cls = get_cls(fai_obj)
        ndci_cls = get_cls(ndci_obj)
        ndti_cls = get_cls(ndti_obj)

        # 1. Surface spectral anomaly check
        if anomaly_cls in ("ANOMALY", "HIGH"):
            return WaterQualitySummary(
                label="High visual/spectral anomaly",
                simple_view="Water reflectance deviates significantly from historical baseline; ground verification recommended.",
            )

        # 2. Surface floating algae check
        if fai_cls in ("HIGH", "ELEVATED"):
            return WaterQualitySummary(
                label="Elevated algal/organic proxy",
                simple_view="Water shows indicators of surface algae or vegetation growth, but this is not confirmed laboratory testing.",
            )

        # 3. Chlorophyll-a check
        if ndci_cls in ("HIGH", "ELEVATED"):
            return WaterQualitySummary(
                label="Elevated chlorophyll-a proxy",
                simple_view="Water shows higher chlorophyll indicators, suggesting potential phytoplankton activity.",
            )

        # 4. Turbidity / suspended matter check
        if ndti_cls == "HIGH":
            return WaterQualitySummary(
                label="Turbid",
                simple_view="Water shows higher turbidity indicators and looks somewhat cloudy.",
            )
        if ndti_cls == "ELEVATED":
            return WaterQualitySummary(
                label="Slightly turbid",
                simple_view="Water shows moderate particulate scattering and may appear slightly murky.",
            )

        # 5. Low / moderate / clear indications
        if ndti_cls in ("LOW", "MODERATE") or ndci_cls in ("LOW", "MODERATE") or anomaly_cls == "NORMAL":
            if ndti_cls == "LOW" and ndci_cls == "LOW":
                return WaterQualitySummary(
                    label="Clear-looking",
                    simple_view="Water looks relatively clear, but this does NOT mean it is safe to drink.",
                )
            return WaterQualitySummary(
                label="Relatively clear",
                simple_view="Water appears relatively clear, but this does NOT mean it is safe to drink.",
            )

        # Fallback if indicators dict has empty/None values
        if has_clear_observation:
            return WaterQualitySummary(
                label="Visually observed",
                simple_view="Optical observation recorded; full spectral indicators have not been calculated yet.",
            )

        return WaterQualitySummary(
            label="Insufficient data",
            simple_view="Not enough spectral data is available to judge the water condition.",
        )
