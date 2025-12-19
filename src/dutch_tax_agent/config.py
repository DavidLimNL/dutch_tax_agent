"""Configuration management for Dutch Tax Agent."""

import os
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings
from typing import Union

# Load environment variables
load_dotenv()


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # OpenAI Configuration
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4o-mini", alias="OPENAI_MODEL")

    # LangSmith Configuration
    langsmith_api_key: str = Field(default="", alias="LANGSMITH_API_KEY")
    langsmith_project: str = Field(default="dutch-tax-agent", alias="LANGSMITH_PROJECT")
    langsmith_tracing: bool = Field(default=False, alias="LANGSMITH_TRACING")
    langsmith_endpoint: str = Field(
        default="",
        alias="LANGSMITH_ENDPOINT",
        description="LangSmith endpoint URL (e.g., https://eu.smith.langchain.com for EU region)",
    )

    # ECB Configuration
    ecb_api_key: str = Field(default="", alias="ECB_API_KEY")
    ecb_rate_cache_days: int = Field(default=7, alias="ECB_RATE_CACHE_DAYS")

    # Application Configuration
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default="INFO", alias="LOG_LEVEL"
    )
    max_document_size_mb: int = Field(default=10, alias="MAX_DOCUMENT_SIZE_MB")
    pdf_min_chars: int = Field(default=50, alias="PDF_MIN_CHARS")
    supported_tax_years: Union[str, list[int]] = Field(
        default="2022,2023,2024,2025",
        alias="SUPPORTED_TAX_YEARS",
    )
    
    @field_validator("supported_tax_years", mode="after")
    @classmethod
    def parse_tax_years(cls, v):
        """Parse tax years from comma-separated string or JSON list."""
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            # Try JSON first
            if v.strip().startswith("["):
                import json
                try:
                    return json.loads(v)
                except json.JSONDecodeError:
                    pass
            # Otherwise treat as comma-separated
            return [int(year.strip()) for year in v.split(",") if year.strip()]
        return v

    # Document Processing
    enable_parallel_parsing: bool = Field(default=True, alias="ENABLE_PARALLEL_PARSING")
    max_parallel_docs: int = Field(default=10, alias="MAX_PARALLEL_DOCS")

    # Paths
    project_root: Path = Field(default_factory=lambda: Path(__file__).parent.parent.parent)
    data_dir: Path = Field(default_factory=lambda: Path(__file__).parent / "data")

    class Config:
        """Pydantic config."""

        env_file = ".env"
        case_sensitive = False


# Global settings instance
settings = Settings()

# Configure LangSmith if enabled
if settings.langsmith_tracing and settings.langsmith_api_key:
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"] = settings.langsmith_api_key
    os.environ["LANGCHAIN_PROJECT"] = settings.langsmith_project
    # Set EU endpoint if specified
    if settings.langsmith_endpoint:
        os.environ["LANGCHAIN_ENDPOINT"] = settings.langsmith_endpoint

