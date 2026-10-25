"""LLM provider abstraction for intent extraction."""
import json
import logging
from abc import ABC, abstractmethod
from datetime import date
from typing import Optional

from django.conf import settings

logger = logging.getLogger(__name__)


class LLMProviderError(Exception):
    """Raised when an LLM provider call fails."""
    pass


class BaseLLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    def chat_completion(self, system_prompt: str, user_message: str) -> str:
        """Send a chat completion request and return the response text."""
        pass


class GeminiProvider(BaseLLMProvider):
    """Google Gemini LLM provider using the google-generativeai SDK."""

    def __init__(self):
        api_key = settings.LLM_API_KEY
        if not api_key:
            raise LLMProviderError("LLM_API_KEY is not configured")

        import google.generativeai as genai
        # Use REST transport to avoid gRPC socket hangs on containerized cloud environments
        genai.configure(api_key=api_key, transport='rest')

        self.model_name = getattr(settings, 'LLM_MODEL', 'gemini-1.5-flash')
        self.model = genai.GenerativeModel(
            self.model_name,
            generation_config=genai.GenerationConfig(
                temperature=0.1,
                max_output_tokens=1000,
                response_mime_type="application/json",
            ),
        )

    def chat_completion(self, system_prompt: str, user_message: str) -> str:
        try:
            response = self.model.generate_content(
                [
                    {"role": "user", "parts": [system_prompt + "\n\nUser message:\n" + user_message]},
                ],
                request_options={"timeout": 15},
            )
            content = response.text
            if not content:
                raise LLMProviderError("Gemini returned empty response")
            return content
        except LLMProviderError:
            raise
        except Exception as e:
            logger.error(f"Gemini API call failed: {type(e).__name__}: {e}")
            raise LLMProviderError(f"Gemini API call failed: {e}") from e


class OpenAIProvider(BaseLLMProvider):
    """OpenAI-compatible LLM provider (works with OpenAI, Azure, local models)."""

    def __init__(self):
        api_key = settings.LLM_API_KEY
        if not api_key:
            raise LLMProviderError("LLM_API_KEY is not configured")

        from openai import OpenAI
        kwargs = {
            'api_key': api_key,
            'timeout': settings.LLM_TIMEOUT,
        }
        base_url = settings.LLM_BASE_URL
        if base_url:
            kwargs['base_url'] = base_url

        self.client = OpenAI(**kwargs)
        self.model = settings.LLM_MODEL

    def chat_completion(self, system_prompt: str, user_message: str) -> str:
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.1,
                max_tokens=1000,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content
            if not content:
                raise LLMProviderError("LLM returned empty response")
            return content
        except LLMProviderError:
            raise
        except Exception as e:
            logger.error(f"LLM API call failed: {type(e).__name__}")
            raise LLMProviderError(f"LLM API call failed: {e}") from e


class MockLLMProvider(BaseLLMProvider):
    """Mock LLM provider for testing without API access."""

    def chat_completion(self, system_prompt: str, user_message: str) -> str:
        """Return a general note intent for any input."""
        return json.dumps({
            "intent": "GENERAL_NOTE",
            "entities": {},
            "needs_clarification": False,
            "clarification_question": None,
        })


def get_llm_provider() -> BaseLLMProvider:
    """Factory to get the configured LLM provider."""
    provider_name = settings.LLM_PROVIDER

    if provider_name == 'mock':
        return MockLLMProvider()
    elif provider_name == 'gemini':
        return GeminiProvider()
    elif provider_name in ('openai', 'openai_compatible'):
        return OpenAIProvider()
    else:
        raise LLMProviderError(f"Unsupported LLM provider: {provider_name}")

