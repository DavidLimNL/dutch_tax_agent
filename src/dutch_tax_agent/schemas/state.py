"""LangGraph state definitions for the main graph and subgraphs."""

from typing import Annotated, Literal, Optional, TypeVar, Union, List

from langgraph.graph import add_messages
from pydantic import BaseModel, ConfigDict, Field

from dutch_tax_agent.schemas.documents import ExtractionResult, ScrubbedDocument
from dutch_tax_agent.schemas.tax_entities import (
    Box1Income,
    Box3Asset,
    Box3Calculation,
    FiscalPartner,
)

T = TypeVar("T")

class Replace(List[T]):
    """Wrapper to signal replacement in a reducer."""
    pass

def add_or_replace(existing: List[T], new: Union[List[T], Replace[T]]) -> List[T]:
    """Reducer that appends by default, but replaces if Replace wrapper is used."""
    if isinstance(new, Replace):
        return list(new)
    return existing + new


class TaxGraphState(BaseModel):
    """Main graph state for the entire tax processing pipeline.
    
    This state follows the governance principle:
    - Raw text is NEVER stored here
    - Only structured, validated data persists
    - PII has already been scrubbed in Phase 1
    """

    # --- Input: Scrubbed Documents (Phase 1 Output) ---
    documents: list[ScrubbedDocument] = Field(
        default_factory=list,
        description="Scrubbed documents ready for LLM processing",
    )
    
    # --- Input: User Profile Data ---
    fiscal_partner: Optional[FiscalPartner] = Field(
        None,
        description="Fiscal partner details for optimization"
    )

    # --- Routing: Classified Documents (Dispatcher Output) ---
    classified_documents: list[dict] = Field(
        default_factory=list,
        description="Documents classified and ready for routing to parser agents",
    )
    quarantined_documents: list[dict] = Field(
        default_factory=list,
        description="Documents quarantined due to tax year mismatch or other issues",
    )
    
    # --- Processing: Extraction Results (Phase 2 Output) ---
    # Using Annotated with 'add_or_replace' operator to accumulate results from parallel parser agents
    # But allowing full replacement for removals
    extraction_results: Annotated[list[ExtractionResult], add_or_replace] = Field(
        default_factory=list,
        description="Raw extraction results from parser agents (before validation)",
    )
    
    # --- Validation Results (Validator Output) ---
    # Using Annotated with 'add_or_replace' operator to accumulate results from parallel validators
    validated_results: Annotated[list[dict], add_or_replace] = Field(
        default_factory=list,
        description="Validated results from validator nodes (accumulated from parallel executions)",
    )
    
    # --- Aggregated Data: Validated Entities (Phase 2 Reducer Output) ---
    # Using Annotated with 'add_or_replace' operator to accumulate items across multiple ingestions
    box1_income_items: Annotated[list[Box1Income], add_or_replace] = Field(
        default_factory=list,
        description="All validated Box 1 income items",
    )
    box3_asset_items: Annotated[list[Box3Asset], add_or_replace] = Field(
        default_factory=list,
        description="All validated Box 3 asset items",
    )
    
    # --- Aggregated Totals ---
    box1_total_income: float = Field(
        default=0.0,
        description="Sum of all Box 1 gross income",
    )
    box3_total_assets_jan1: float = Field(
        default=0.0,
        description="Sum of all Box 3 assets on Jan 1",
    )
    
    # --- Validation & Status ---
    validation_errors: list[str] = Field(
        default_factory=list,
        description="Critical errors that block calculation",
    )
    validation_warnings: list[str] = Field(
        default_factory=list,
        description="Non-critical issues",
    )
    status: Literal[
        "initialized",
        "ingesting",
        "classifying",
        "extracting",
        "validating",
        "quarantine",
        "awaiting_human",
        "ready_for_calculation",
        "calculating",
        "complete",
        "error",
    ] = Field(
        default="initialized",
        description="Current pipeline status",
    )
    
    # --- Box 3 Calculation Results (Phase 3 Output) ---
    box3_fictional_yield_result: Optional[Box3Calculation] = Field(
        None,
        description="Result from fictional yield method",
    )
    box3_actual_return_result: Optional[Box3Calculation] = Field(
        None,
        description="Result from actual return method",
    )
    
    # --- Final Recommendation ---
    recommended_method: Optional[Literal["fictional_yield", "actual_return"]] = None
    recommendation_reasoning: Optional[str] = None
    potential_savings_eur: Optional[float] = None
    
    # --- Metadata ---
    tax_year: int = Field(
        default=2024,
        description="Tax year being processed",
    )
    processing_started_at: Optional[str] = None
    processing_completed_at: Optional[str] = None
    
    # --- Human-in-the-Loop (HITL) ---
    human_corrections: dict = Field(
        default_factory=dict,
        description="Manual corrections provided by user during quarantine",
    )
    requires_human_review: bool = Field(
        default=False,
        description="Flag to trigger human intervention",
    )
    next_action: Literal["await_human", "ingest_more", "calculate"] = Field(
        default="await_human",
        description="Next action to take at HITL control node",
    )
    
    # --- Document Tracking ---
    processed_documents: list[dict] = Field(
        default_factory=list,
        description="List of documents with metadata: {id, filename, hash, page_count, timestamp}",
    )
    
    # --- Session Metadata ---
    session_id: str = Field(
        default="",
        description="Unique session identifier (same as thread_id)",
    )
    last_command: Optional[str] = Field(
        default=None,
        description="Last CLI command executed",
    )
    paused_at_node: Optional[str] = Field(
        default=None,
        description="Node where execution paused",
    )

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
    )


# Annotated types for message-like fields (if needed for streaming)
MessagesState = Annotated[list, add_messages]

