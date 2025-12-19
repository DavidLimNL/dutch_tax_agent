"""Pydantic schemas for Dutch Tax Agent."""

from dutch_tax_agent.schemas.documents import ExtractionResult, ScrubbedDocument
from dutch_tax_agent.schemas.state import TaxGraphState
from dutch_tax_agent.schemas.tax_entities import (
    Box1Income,
    Box3Asset,
    Box3Calculation,
    TaxReport,
)

__all__ = [
    "ScrubbedDocument",
    "ExtractionResult",
    "Box1Income",
    "Box3Asset",
    "Box3Calculation",
    "TaxReport",
    "TaxGraphState",
]

