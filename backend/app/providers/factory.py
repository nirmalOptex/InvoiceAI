from app.config import Settings, get_settings
from app.providers.base import (
    InvoiceVisionProvider,
    ProviderConfigurationError,
)
from app.providers.claude import ClaudeVisionProvider
from app.providers.gemini import GeminiVisionProvider
from app.providers.local import LocalRuleBasedProvider


def create_vision_provider(settings: Settings | None = None) -> InvoiceVisionProvider:
    config = settings or get_settings()
    provider_name = config.ai_provider.strip().lower()
    if provider_name == "local":
        return LocalRuleBasedProvider()
    if provider_name == "gemini":
        if not config.gemini_api_key:
            raise ProviderConfigurationError(
                "AI_PROVIDER is 'gemini', but GEMINI_API_KEY is not configured."
            )
        return GeminiVisionProvider(
            api_key=config.gemini_api_key,
            model=config.gemini_model,
            timeout_seconds=config.provider_timeout_seconds,
        )
    if provider_name == "claude":
        if not config.anthropic_api_key:
            raise ProviderConfigurationError(
                "AI_PROVIDER is 'claude', but ANTHROPIC_API_KEY is not configured."
            )
        return ClaudeVisionProvider(
            api_key=config.anthropic_api_key,
            model=config.anthropic_model,
            timeout_seconds=config.provider_timeout_seconds,
        )
    raise ProviderConfigurationError(
        "Unsupported AI_PROVIDER. Choose 'local', 'gemini', or 'claude'."
    )
