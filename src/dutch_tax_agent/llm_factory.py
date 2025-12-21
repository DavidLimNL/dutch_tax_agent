"""LLM factory for creating LLM instances based on provider configuration."""

import logging

from langchain_core.language_models import BaseChatModel

from dutch_tax_agent.config import settings

logger = logging.getLogger(__name__)


def create_llm(temperature: float = 0) -> BaseChatModel:
    """Create an LLM instance based on the configured provider.
    
    Args:
        temperature: Temperature setting for the LLM (default: 0)
        
    Returns:
        BaseChatModel instance (ChatOpenAI or ChatOllama)
        
    Raises:
        ValueError: If provider is not supported or configuration is invalid
    """
    provider = settings.llm_provider.lower()
    
    # Determine model name
    model_name = settings.llm_model.strip() if settings.llm_model else None
    
    if provider == "openai":
        from langchain_openai import ChatOpenAI
        
        # Use llm_model if set, otherwise fall back to openai_model for backward compatibility
        model = model_name or settings.openai_model
        
        if not settings.openai_api_key:
            logger.warning(
                "OPENAI_API_KEY not set. LLM calls may fail. "
                "Set OPENAI_API_KEY environment variable."
            )
        
        logger.info(f"Creating OpenAI LLM with model: {model}, temperature: {temperature}")
        return ChatOpenAI(
            model=model,
            temperature=temperature,
            api_key=settings.openai_api_key or None,
        )
    
    elif provider == "ollama":
        try:
            from langchain_ollama import ChatOllama
        except ImportError:
            raise ImportError(
                "langchain-ollama is not installed. "
                "Install it with: uv add langchain-ollama"
            )
        
        # Default Ollama model if not specified
        model = model_name or "llama3.2"
        
        logger.info(
            f"Creating Ollama LLM with model: {model}, "
            f"base_url: {settings.ollama_base_url}, temperature: {temperature}"
        )
        return ChatOllama(
            model=model,
            base_url=settings.ollama_base_url,
            temperature=temperature,
        )
    
    else:
        raise ValueError(
            f"Unsupported LLM provider: {provider}. "
            f"Supported providers: 'openai', 'ollama'"
        )

