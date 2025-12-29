"""Document-related schemas for ingestion and processing."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ScrubbedDocument(BaseModel):
    """A document after PII scrubbing (Phase 1 output)."""

    doc_id: str = Field(description="Unique identifier for this document")
    filename: str = Field(description="Original filename")
    scrubbed_text: str = Field(description="Text with PII replaced by tokens")
    page_count: int = Field(description="Number of pages in PDF")
    char_count: int = Field(description="Character count (for validation)")
    scrubbed_entities: list[str] = Field(
        default_factory=list,
        description="Types of PII that were scrubbed (e.g., ['BSN', 'IBAN'])",
    )
    created_at: datetime = Field(default_factory=datetime.now)


class DocumentClassification(BaseModel):
    """Result of document type classification."""

    doc_id: str
    doc_type: Literal[
        "dutch_bank_statement",
        "us_broker_statement",
        "crypto_broker_statement",
        "salary_statement",
        "mortgage_statement",
        "revolut_statement",
        "unknown",
    ]
    confidence: float = Field(ge=0.0, le=1.0, description="Classification confidence")
    reasoning: str = Field(description="Why this classification was chosen")
    tax_year: int | None = Field(
        default=None,
        description="Tax year extracted from document (None if not found or unclear)",
    )
    statement_subtype: Literal["jan_period", "dec_period", "dec_prev_year", "full_year", None] = Field(
        default=None,
        description="For broker statements: jan_period (Jan statement), dec_period (Dec statement of tax year), dec_prev_year (Dec statement of previous year, used as Jan 1 value), or full_year (full year statement). None for non-broker documents.",
    )


class ExtractionResult(BaseModel):
    """Result from a parser agent (Phase 2 output).
    
    Note: This schema does NOT contain raw text - only structured data.
    """

    doc_id: str = Field(description="Links back to ScrubbedDocument")
    source_filename: str = Field(description="Original filename for audit trail")
    status: Literal["success", "error", "partial"] = Field(
        description="Extraction status"
    )
    
    # Structured data (no raw text!)
    extracted_data: dict = Field(
        default_factory=dict,
        description="Structured entities extracted by the agent",
    )
    
    # Metadata for audit trail
    extraction_confidence: float = Field(
        ge=0.0,
        le=1.0,
        default=1.0,
        description="Agent's confidence in extraction",
    )
    extracted_at: datetime = Field(default_factory=datetime.now)
    extracted_by_model: str = Field(
        default="gpt-4o-mini",
        description="Model used for extraction",
    )
    
    # Error handling
    errors: list[str] = Field(
        default_factory=list,
        description="List of errors encountered during extraction",
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Non-critical issues",
    )

