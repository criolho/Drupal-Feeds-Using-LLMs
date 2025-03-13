# config/settings.py

from typing import Optional  # For optional type hints
from pydantic_settings import BaseSettings  # Settings management with validation
from dotenv import load_dotenv
import os

# Load environment variables from .env file if present
load_dotenv()


class LLMProviderSettings(BaseSettings):
    """
    Base settings class for all LLM providers with common parameters.
    Using Pydantic for automatic validation and environment variable loading.
    """

    temperature: float = 0.0  # Default to 0 temperature (most deterministic outputs)
    max_tokens: Optional[int] = (
        None  # Max tokens to generate, None means use provider's default
    )
    max_retries: int = 3  # Number of retries for API failures


class OpenAISettings(LLMProviderSettings):
    """
    OpenAI-specific settings with API key and default model.
    """

    api_key: str = os.getenv("OPENAI_API_KEY")
    default_model: str = (
        "gpt-4o-mini"  # Default to GPT-4o, gpt-4o-mini is a less pricey alternative
    )


class AnthropicSettings(LLMProviderSettings):
    """
    Anthropic-specific settings with API key and default model.
    """

    api_key: str = os.getenv("ANTHROPIC_API_KEY")  # Load API key from environment
    default_model: str = "claude-3-7-sonnet-latest"  # Default to Claude 3.7 Sonnet


class GeminiSettings(LLMProviderSettings):
    """
    Google Gemini-specific settings with API key and default model.
    """

    api_key: str = os.getenv("GOOGLE_API_KEY")  # Load API key from environment
    default_model: str = "models/gemini-2.0-flash"  # Default to Gemini 2.0 Flash
    max_tokens: int = 8192  # Override the base class default for output length


class Settings(BaseSettings):
    """
    Main settings class that aggregates all provider-specific settings.
    """

    app_name: str = "GenAI Project Template"  # Application name
    openai: OpenAISettings = OpenAISettings()  # OpenAI settings
    anthropic: AnthropicSettings = AnthropicSettings()  # Anthropic settings
    gemini: GeminiSettings = GeminiSettings()  # Gemini settings


def get_settings():
    """
    Returns:
        Settings: Configured settings object with all provider settings
    """
    return Settings()
