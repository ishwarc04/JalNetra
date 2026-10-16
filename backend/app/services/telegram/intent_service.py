import json
import logging
import re
from enum import Enum
from dataclasses import dataclass
from typing import Optional, List, Dict, Tuple, Any
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models.water_body import WaterBody
from app.services.ai.service import AIService

logger = logging.getLogger("jalnetra.services.telegram.intent")


class TelegramIntent(str, Enum):
    LIST_WATER_BODIES = "LIST_WATER_BODIES"
    WATER_BODY_INFO = "WATER_BODY_INFO"
    LATEST_IMAGE = "LATEST_IMAGE"
    LOCATION = "LOCATION"
    WATER_QUALITY = "WATER_QUALITY"
    WATER_EXTENT = "WATER_EXTENT"
    MONITORING_FREQUENCY = "MONITORING_FREQUENCY"
    WATER_VOLUME = "WATER_VOLUME"
    WEATHER = "WEATHER"
    RAIN_FORECAST = "RAIN_FORECAST"
    WATER_LEVEL_FORECAST = "WATER_LEVEL_FORECAST"
    DRINKABILITY = "DRINKABILITY"
    TOXICITY = "TOXICITY"
    BATHING_SAFETY = "BATHING_SAFETY"
    WATER_SAFETY = "WATER_SAFETY"
    HELP = "HELP"
    STATUS = "STATUS"
    AI_QUESTION = "AI_QUESTION"
    UNKNOWN = "UNKNOWN"


@dataclass
class IntentResult:
    intent: TelegramIntent
    secondary_intent: Optional[TelegramIntent] = None
    water_body: Optional[WaterBody] = None
    water_body_candidates: Optional[List[WaterBody]] = None
    raw_query: str = ""
    is_today_query: bool = False
    context_used: bool = False


# Generic water body stopwords that should not match a lake by themselves
GENERIC_WATER_TERMS = {
    "lake", "lakes", "reservoir", "reservoirs", "dam", "dams",
    "water", "waterbody", "waterbodies", "body", "pond", "ponds",
    "river", "rivers", "sea", "lagoon", "wetland", "tal", "taal",
    "the", "a", "an", "this", "that", "its", "it", "here", "there",
}

# Transliteration and alias dictionary for registered entities
ENTITY_SYNONYMS = {
    "phewa": ["fewa", "phewa", "फेवा"],
    "fewa": ["fewa", "phewa", "फेवा"],
    "फेवा": ["fewa", "phewa", "फेवा"],
    "harsul": ["harsul", "हरसूल"],
    "salim": ["salim", "सलीम"],
    "chilika": ["chilika", "चिलिका"],
    "ooty": ["ooty", "ऊटी"],
    "khadakwasla": ["khadakwasla", "खडकवासला"],
}


class TelegramIntentService:
    """
    Deterministic intent and entity classification engine for JalNetra Telegram Bot,
    with conversational context tracking, multi-intent compound routing,
    and secure structured OpenAI fallback.
    """

    def __init__(self, ai_service: Optional[AIService] = None):
        self.ai_service = ai_service or AIService()
        # In-memory conversational context: chat_id -> last_water_body_id
        self._chat_context: Dict[int, str] = {}

    def get_chat_context(self, chat_id: int) -> Optional[str]:
        return self._chat_context.get(chat_id)

    def set_chat_context(self, chat_id: int, water_body_id: str):
        self._chat_context[chat_id] = water_body_id

    def clear_chat_context(self, chat_id: int):
        self._chat_context.pop(chat_id, None)

    def _find_water_body_entities(
        self, text: str, all_wbs: List[WaterBody]
    ) -> List[WaterBody]:
        """
        Extracts candidate water bodies mentioned in user text using exact,
        substring, token-based, and alias/transliteration matching.
        """
        clean_text = text.lower().strip()
        clean_text_words = set(re.findall(r"\b\w+\b", clean_text))

        # 1. Exact match against full name or normalized name
        for wb in all_wbs:
            wb_name = (wb.name or "").strip().lower()
            wb_norm = (wb.normalized_name or "").strip().lower()
            if wb_name and wb_name == clean_text:
                return [wb]
            if wb_norm and wb_norm == clean_text:
                return [wb]

        # 2. Full name substring inside user text (e.g. "show salim ali lake please")
        exact_substring_matches = []
        for wb in all_wbs:
            wb_name = (wb.name or "").strip().lower()
            wb_norm = (wb.normalized_name or "").strip().lower()
            if wb_name and wb_name in clean_text:
                exact_substring_matches.append(wb)
            elif wb_norm and wb_norm in clean_text:
                exact_substring_matches.append(wb)

        if exact_substring_matches:
            exact_substring_matches.sort(key=lambda w: len(w.name or ""), reverse=True)
            return exact_substring_matches

        # 3. Alias / transliteration matching (e.g. "phewa" <-> "fewa" <-> "फेवा")
        for word in clean_text_words:
            if word in ENTITY_SYNONYMS:
                synonyms = ENTITY_SYNONYMS[word]
                for wb in all_wbs:
                    wb_full = f"{wb.name or ''} {wb.normalized_name or ''}".lower()
                    if any(s in wb_full for s in synonyms):
                        return [wb]

        # 4. Specific distinctive tokens (e.g. "salim ali" for "Salim Ali Lake", "ooty" for "Ooty Lake")
        token_matches = []
        for wb in all_wbs:
            wb_name = (wb.name or "").strip().lower()
            wb_norm = (wb.normalized_name or "").strip().lower()
            name_tokens = set(re.findall(r"\b\w+\b", wb_name))
            norm_tokens = set(re.findall(r"\b\w+\b", wb_norm))
            all_tokens = name_tokens | norm_tokens

            distinctive_tokens = all_tokens - GENERIC_WATER_TERMS
            if not distinctive_tokens:
                distinctive_tokens = all_tokens

            # Check if any distinctive token >= 4 chars matches
            if distinctive_tokens and any(tok in clean_text_words and len(tok) >= 4 for tok in distinctive_tokens):
                token_matches.append(wb)
            elif distinctive_tokens and distinctive_tokens.issubset(clean_text_words):
                token_matches.append(wb)

        # Deduplicate matches
        seen = set()
        unique_matches = []
        for wb in token_matches:
            if wb.id not in seen:
                seen.add(wb.id)
                unique_matches.append(wb)

        return unique_matches

    def classify_intent(
        self,
        text: str,
        chat_id: int,
        all_wbs: List[WaterBody],
    ) -> IntentResult:
        """
        Main natural-language classifier.
        Uses deterministic keyword/entity rules first.
        Handles conversational context, pronoun references, and compound intents.
        Falls back to structured OpenAI classification only for ambiguous inputs.
        """
        raw = text.strip()
        lower = raw.lower()

        # Check for "today" phrasing
        is_today = bool(re.search(r"\btoday\b", lower))

        # 1. High-priority commands & greetings / help / status
        if lower in ("/start", "start", "hi", "hello", "hey"):
            return IntentResult(intent=TelegramIntent.HELP, raw_query=raw)

        if lower in ("/help", "help", "guide", "commands", "how to use"):
            return IntentResult(intent=TelegramIntent.HELP, raw_query=raw)

        if lower in ("/ping", "ping", "/status", "status", "health"):
            return IntentResult(intent=TelegramIntent.STATUS, raw_query=raw)

        # 2. List all water bodies
        list_patterns = [
            r"\b(list|all)\b.*\b(water|lakes?|reservoirs?|bodies)\b",
            r"\b(show|get|view)\b.*\b(all)\b",
            r"\bwhat\b.*\b(water\s*bodies|lakes)\b.*\b(do\s*you\s*have|available)\b",
            r"^/list$",
            r"^list$",
            r"^all water bodies$",
            r"^show all$",
        ]
        if any(re.search(pat, lower) for pat in list_patterns):
            return IntentResult(intent=TelegramIntent.LIST_WATER_BODIES, raw_query=raw)

        # 3. Entity detection & Context tracking
        matched_wbs = self._find_water_body_entities(raw, all_wbs)

        target_wb: Optional[WaterBody] = None
        context_used = False

        if len(matched_wbs) == 1:
            target_wb = matched_wbs[0]
            # Save context for future follow-ups
            self.set_chat_context(chat_id, target_wb.id)
        elif len(matched_wbs) > 1:
            # Multiple matches -> Disambiguation
            return IntentResult(
                intent=TelegramIntent.WATER_BODY_INFO,
                water_body_candidates=matched_wbs,
                raw_query=raw,
            )
        else:
            # No registered water body explicitly named.
            # Check if user named an explicit UNREGISTERED lake (e.g. "Lake Superior", "Pichola Reservoir")
            named_lake_match = re.search(
                r"\b([a-zA-Z0-9\-\'\s]{2,})\s+(lake|reservoir|dam|pond|talab|wetland|water\s*body)\b",
                lower,
            )
            is_explicit_unregistered_entity = False
            if named_lake_match:
                prefix = named_lake_match.group(1).strip()
                prefix_stopwords = {
                    "the", "a", "an", "this", "that", "its", "it", "our", "is", "will", "does",
                    "can", "to", "at", "in", "for", "about", "of", "from", "on", "what", "how",
                    "happen", "happens", "safe", "drinking", "level", "extent", "temperature",
                }
                substantive_prefix_words = set(prefix.split()) - prefix_stopwords
                if substantive_prefix_words:
                    is_explicit_unregistered_entity = True

            stored_id = self.get_chat_context(chat_id)
            if stored_id and not is_explicit_unregistered_entity:
                for wb in all_wbs:
                    if wb.id == stored_id:
                        target_wb = wb
                        context_used = True
                        break

        # 4. Compound / Multi-Intent Detection
        # A. Drinkability + Water Level Forecast
        is_drink = bool(re.search(r"\b(drink|drinkable|potable|drinking)\b", lower))
        is_level = bool(
            re.search(
                r"\b(water\s*level|lake\s*level|level\s+(increase|rise|fall|drop|decrease|go\s*down)|dry\s*up|fill\s*up|rise\s+or\s+fall)\b",
                lower,
            )
            or re.search(r"\bwill\s+(it|the\s+lake|water|reservoir)\s+(increase|rise|fall|dry|fill)\b", lower)
        )
        if is_drink and is_level:
            return IntentResult(
                intent=TelegramIntent.DRINKABILITY,
                secondary_intent=TelegramIntent.WATER_LEVEL_FORECAST,
                water_body=target_wb,
                raw_query=raw,
                is_today_query=is_today,
                context_used=context_used,
            )

        # B. Water Quality + Weather
        is_quality = bool(
            re.search(r"\b(how\s+is\s+the\s+water|water\s*quality|clarity|condition\s+of\s+the\s+water)\b", lower)
        )
        is_weather = bool(
            re.search(r"\b(weather|rain|raining|rainfall|forecast|temperature|hot|cold|climate)\b", lower)
        )
        if is_quality and is_weather:
            return IntentResult(
                intent=TelegramIntent.WATER_QUALITY,
                secondary_intent=TelegramIntent.WEATHER,
                water_body=target_wb,
                raw_query=raw,
                is_today_query=is_today,
                context_used=context_used,
            )

        # 5. Dedicated Single Intents

        # A. DRINKABILITY
        # "Is this water drinkable?", "Can I drink the water?", "Can I drink it?", "Is the lake safe for drinking?"
        drinkability_patterns = [
            r"\b(drinkable|potable|potability)\b",
            r"\b(can\s+(i|we)\s+drink|safe\s+(for|to)\s+drink|drink\s+(the|this|it)\s*water|drink\s+it)\b",
            r"\bdrinking\s+water\b",
            r"\bsafe\s+for\s+drinking\b",
        ]
        if any(re.search(pat, lower) for pat in drinkability_patterns):
            return IntentResult(
                intent=TelegramIntent.DRINKABILITY,
                water_body=target_wb,
                raw_query=raw,
                is_today_query=is_today,
                context_used=context_used,
            )

        # B. TOXICITY
        # "Is this water toxic?", "Is the water polluted?", "Is it toxic?", "Are there toxins?"
        toxicity_patterns = [
            r"\b(toxic|toxicity|poison|poisonous|toxin|toxins|polluted|pollution|contaminated|contamination)\b",
        ]
        if any(re.search(pat, lower) for pat in toxicity_patterns):
            return IntentResult(
                intent=TelegramIntent.TOXICITY,
                water_body=target_wb,
                raw_query=raw,
                is_today_query=is_today,
                context_used=context_used,
            )

        # C. BATHING / SWIMMING SAFETY
        # "Can I bathe here?", "Is it safe to swim?", "Can I swim in it?"
        bathing_patterns = [
            r"\b(bathe|bathing|bath|swim|swimming|swimmable)\b",
            r"\b(can\s+(i|we)\s+bathe|safe\s+to\s+swim|safe\s+for\s+swimming|can\s+(i|we)\s+swim)\b",
        ]
        if any(re.search(pat, lower) for pat in bathing_patterns):
            return IntentResult(
                intent=TelegramIntent.BATHING_SAFETY,
                water_body=target_wb,
                raw_query=raw,
                is_today_query=is_today,
                context_used=context_used,
            )

        # D. GENERAL WATER SAFETY
        # "Is the water safe?", "Is it safe?", "Is it safe here?"
        safety_patterns = [
            r"\b(is\s+(the\s+water|it|this\s+water)\s+safe|water\s+safe|safe\s+water|water\s+safety)\b",
        ]
        if any(re.search(pat, lower) for pat in safety_patterns):
            return IntentResult(
                intent=TelegramIntent.WATER_SAFETY,
                water_body=target_wb,
                raw_query=raw,
                is_today_query=is_today,
                context_used=context_used,
            )

        # E. WATER LEVEL FORECAST & HYDROLOGICAL OUTLOOK
        # "Will the water level increase?", "Will the lake level rise?", "Will the lake dry up?", "Will it go down?",
        # "Will the reservoir fill up?", "What will happen to the lake over the next few days?"
        water_level_patterns = [
            r"\b(water\s*level|lake\s*level|reservoir\s*level)\b",
            r"\b(level\s+(increase|rise|fall|drop|decrease|go\s*down))\b",
            r"\b(rise\s+or\s+fall|dry\s*up|drying\s*up|fill\s*up|filling\s*up|overflow)\b",
            r"\bwill\s+(it|the\s+lake|water|the\s+reservoir|its\s+level)\s+(increase|rise|fall|drop|decrease|dry|fill|go\s*down)\b",
            r"\bwill\s+its\s+level\s+(increase|rise|fall|drop|decrease|go\s*down)\b",
            r"\bwhat\s+will\s+happen\s+to\s+the\s+(lake|water|reservoir)\b",
            r"\bwill\s+rainfall\s+increase\s+the\s+water\s*level\b",
        ]
        if any(re.search(pat, lower) for pat in water_level_patterns):
            return IntentResult(
                intent=TelegramIntent.WATER_LEVEL_FORECAST,
                water_body=target_wb,
                raw_query=raw,
                is_today_query=is_today,
                context_used=context_used,
            )

        # F. LATEST IMAGE / PHOTO
        # "Show image", "Show me the lake", "Send the latest photo", "Can I see the latest image?",
        # "What does the lake look like?", "Show its satellite image", "Give me the latest visual"
        image_keywords = [
            "image", "photo", "picture", "visual", "satellite", "satellite image",
            "satellite view", "satellite photo", "look like",
        ]
        image_phrases = [
            r"\b(show\s+image|show\s+me\s+the\s+lake|send\s+(the\s+)?(latest\s+)?photo|see\s+(the\s+)?(latest\s+)?image|latest\s+visual)\b",
            r"\b(show\s+its\s+(latest\s+)?image|show\s+me\s+its\s+image|show\s+photo|latest\s+picture)\b",
        ]
        if any(kw in lower for kw in image_keywords) or any(re.search(pat, lower) for pat in image_phrases):
            return IntentResult(
                intent=TelegramIntent.LATEST_IMAGE,
                water_body=target_wb,
                raw_query=raw,
                is_today_query=is_today,
                context_used=context_used,
            )

        # G. WEATHER / RAIN FORECAST
        # "What's the weather there?", "Will it rain?", "Will it rain tomorrow?", "What is the forecast?",
        # "Will there be heavy rain this week?"
        rain_patterns = [
            r"\b(rain|raining|rainfall|rainy|precipitation)\b",
            r"\bwill\s+it\s+rain\b",
            r"\bheavy\s+rain\b",
        ]
        weather_patterns = [
            r"\b(weather|forecast|temperature|climate)\b",
            r"\bwhat\s+is\s+the\s+forecast\b",
            r"\bwhat(\'s|\s+is)\s+the\s+weather\b",
        ]
        if any(re.search(pat, lower) for pat in rain_patterns):
            return IntentResult(
                intent=TelegramIntent.RAIN_FORECAST,
                water_body=target_wb,
                raw_query=raw,
                is_today_query=is_today,
                context_used=context_used,
            )
        if any(re.search(pat, lower) for pat in weather_patterns):
            return IntentResult(
                intent=TelegramIntent.WEATHER,
                water_body=target_wb,
                raw_query=raw,
                is_today_query=is_today,
                context_used=context_used,
            )

        # H. LOCATION / GOOGLE MAPS
        # "Where is it?", "Where is Salim Ali Lake?", "Location of Phewa Tal"
        location_keywords = ["where is", "where's", "where", "location", "locate", "map", "maps", "coordinates", "situated", "directions"]
        if any(re.search(r"\b" + re.escape(kw) + r"\b", lower) for kw in location_keywords):
            return IntentResult(
                intent=TelegramIntent.LOCATION,
                water_body=target_wb,
                raw_query=raw,
                is_today_query=is_today,
                context_used=context_used,
            )

        # I. WATER QUALITY
        # "How is the water?", "What is the water quality of Chilika Lake?", "Water clarity", "Algae"
        quality_keywords = [
            "water quality", "quality", "clean", "dirty", "clarity", "clear",
            "algae", "algal", "turbid", "turbidity", "chlorophyll",
            "how is the water", "water condition", "condition of the water",
        ]
        if any(re.search(r"\b" + re.escape(kw) + r"\b", lower) for kw in quality_keywords):
            return IntentResult(
                intent=TelegramIntent.WATER_QUALITY,
                water_body=target_wb,
                raw_query=raw,
                is_today_query=is_today,
                context_used=context_used,
            )

        # J. WATER EXTENT / SURFACE AREA
        extent_keywords = ["surface area", "water extent", "how big", "area of", "extent of", "size"]
        if any(re.search(r"\b" + re.escape(kw) + r"\b", lower) for kw in extent_keywords):
            return IntentResult(
                intent=TelegramIntent.WATER_EXTENT,
                water_body=target_wb,
                raw_query=raw,
                is_today_query=is_today,
                context_used=context_used,
            )

        # K. MONITORING FREQUENCY / CHANGE
        freq_keywords = ["how often", "frequency", "change", "changes", "monitoring", "monitored", "how frequently", "observations", "observation history"]
        if any(re.search(r"\b" + re.escape(kw) + r"\b", lower) for kw in freq_keywords):
            return IntentResult(
                intent=TelegramIntent.MONITORING_FREQUENCY,
                water_body=target_wb,
                raw_query=raw,
                is_today_query=is_today,
                context_used=context_used,
            )

        # L. WATER VOLUME
        volume_keywords = ["volume", "how much water", "capacity", "water amount", "depth", "deep"]
        if any(re.search(r"\b" + re.escape(kw) + r"\b", lower) for kw in volume_keywords):
            return IntentResult(
                intent=TelegramIntent.WATER_VOLUME,
                water_body=target_wb,
                raw_query=raw,
                is_today_query=is_today,
                context_used=context_used,
            )

        # M. Recognized water body: "Show X", "Tell me about X", "How is X today?", "X"
        if target_wb is not None and (not context_used or is_today):
            return IntentResult(
                intent=TelegramIntent.WATER_BODY_INFO,
                water_body=target_wb,
                raw_query=raw,
                is_today_query=is_today,
                context_used=context_used,
            )

        # 6. Fallback: If configured with AI and query looks conversational/questioning
        if self.ai_service and getattr(self.ai_service, "is_configured", False) and ("?" in lower or len(lower.split()) > 2):
            ai_structured = self._classify_with_openai(raw, [w.name for w in all_wbs if w.name])
            if ai_structured:
                intent_enum = getattr(TelegramIntent, ai_structured.get("intent", "AI_QUESTION"), TelegramIntent.AI_QUESTION)
                wb_name = ai_structured.get("water_body_name")
                found_wb = None
                if wb_name:
                    for wb in all_wbs:
                        if wb.name.lower() == wb_name.lower():
                            found_wb = wb
                            self.set_chat_context(chat_id, wb.id)
                            break
                return IntentResult(
                    intent=intent_enum,
                    water_body=found_wb or target_wb,
                    raw_query=raw,
                    is_today_query=is_today,
                    context_used=context_used,
                )

        # 7. Default to AI question if it has a question mark or general conversational phrase
        if "?" in lower or lower.startswith(("what", "why", "how", "tell", "explain")):
            return IntentResult(
                intent=TelegramIntent.AI_QUESTION,
                water_body=target_wb,
                raw_query=raw,
                is_today_query=is_today,
                context_used=context_used,
            )

        return IntentResult(
            intent=TelegramIntent.UNKNOWN,
            water_body=target_wb,
            raw_query=raw,
            is_today_query=is_today,
            context_used=context_used,
        )

    def _classify_with_openai(self, text: str, available_names: List[str]) -> Optional[Dict[str, Any]]:
        """
        Uses OpenAI to classify intent strictly into structured JSON.
        Never executes code or mutations.
        """
        try:
            client = getattr(self.ai_service, "client", None)
            if not client:
                return None

            prompt = (
                "You are an intent classifier for a water-body monitoring system.\n"
                f"Available water bodies: {', '.join(available_names[:30])}\n\n"
                "Classify the user message into one of these intents:\n"
                "LIST_WATER_BODIES, WATER_BODY_INFO, LATEST_IMAGE, LOCATION, WATER_QUALITY, "
                "WATER_EXTENT, MONITORING_FREQUENCY, WATER_VOLUME, WEATHER, RAIN_FORECAST, "
                "WATER_LEVEL_FORECAST, DRINKABILITY, TOXICITY, BATHING_SAFETY, WATER_SAFETY, "
                "HELP, STATUS, AI_QUESTION.\n\n"
                "Return strictly a JSON object with keys:\n"
                "{\n"
                '  "intent": "<INTENT_NAME>",\n'
                '  "water_body_name": "<matched water body name or null>"\n'
                "}\n\n"
                f'User message: "{text}"'
            )

            res = client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=100,
                response_format={"type": "json_object"},
            )
            content = res.choices[0].message.content
            return json.loads(content)
        except Exception as e:
            logger.debug("OpenAI intent classification skipped/failed: %s", e)
            return None
