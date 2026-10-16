import logging
from typing import List, Dict, Any, Optional
from openai import OpenAI, OpenAIError, AuthenticationError, RateLimitError, APITimeoutError, APIConnectionError
from app.core.config import settings

logger = logging.getLogger("jalnetra.services.ai")


class AIServiceError(Exception):
    def __init__(self, message: str, code: str = "AI_SERVICE_ERROR", status_code: int = 500):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code


class OpenAIClientWrapper:
    """
    Isolated wrapper around OpenAI Python SDK.
    Ensures API keys are never exposed in logs or client exceptions.
    """

    def __init__(self):
        self._client: Optional[OpenAI] = None

    def _get_client(self) -> OpenAI:
        if not settings.AI_ENABLED:
            raise AIServiceError(
                message="AI service is currently disabled in system configuration.",
                code="AI_DISABLED",
                status_code=503,
            )
        api_key = settings.OPENAI_API_KEY.strip()
        if not api_key:
            raise AIServiceError(
                message="AI service is not configured. Missing API key.",
                code="AI_NOT_CONFIGURED",
                status_code=503,
            )
        if self._client is None:
            self._client = OpenAI(api_key=api_key, timeout=30.0)
        return self._client

    def generate_chat_completion(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: float = 0.3,
    ) -> str:
        client = self._get_client()
        target_model = model or settings.OPENAI_MODEL
        target_tokens = max_tokens or settings.AI_MAX_OUTPUT_TOKENS

        try:
            logger.info("Sending chat completion request to OpenAI (model: %s)", target_model)
            response = client.chat.completions.create(
                model=target_model,
                messages=messages,
                max_tokens=target_tokens,
                temperature=temperature,
            )
            if not response.choices or not response.choices[0].message:
                raise AIServiceError(
                    message="OpenAI returned an empty response.",
                    code="AI_EMPTY_RESPONSE",
                    status_code=502,
                )
            content = response.choices[0].message.content or ""
            return content.strip()

        except AuthenticationError as e:
            logger.warning("OpenAI authentication failed: invalid API key")
            raise AIServiceError(
                message="OpenAI authentication failed. Please verify your configured API key.",
                code="AI_AUTH_ERROR",
                status_code=502,
            )
        except RateLimitError as e:
            logger.warning("OpenAI rate limit exceeded")
            raise AIServiceError(
                message="AI rate limit reached. Please wait a moment and try again.",
                code="AI_RATE_LIMIT",
                status_code=429,
            )
        except (APITimeoutError, APIConnectionError) as e:
            logger.warning("OpenAI connection / timeout error: %s", type(e).__name__)
            raise AIServiceError(
                message="AI service is currently unreachable. Please try again shortly.",
                code="AI_TIMEOUT",
                status_code=504,
            )
        except OpenAIError as e:
            logger.error("OpenAI API error: %s", type(e).__name__)
            raise AIServiceError(
                message="AI service encountered an error while generating a response.",
                code="AI_API_ERROR",
                status_code=502,
            )
        except AIServiceError:
            raise
        except Exception as e:
            logger.error("Unexpected error in AI client: %s", type(e).__name__)
            raise AIServiceError(
                message="An unexpected error occurred while contacting AI service.",
                code="AI_INTERNAL_ERROR",
                status_code=500,
            )
