"""Human-in-the-loop control node for managing ingestion/calculation flow."""

import logging
from typing import Literal

from langgraph.types import Command

from dutch_tax_agent.schemas.state import TaxGraphState

logger = logging.getLogger(__name__)


def hitl_control_node(state: TaxGraphState) -> Command[Literal["dispatcher", "start_box3", "__end__"]]:
    """Human-in-the-loop control node.
    
    This node is interrupted BEFORE execution (via interrupt_before in graph compilation).
    When resumed, it re-executes and evaluates next_action to determine routing:
    - "await_human" → Return with status update (graph will interrupt before re-execution)
    - "ingest_more" → Route to dispatcher to process new documents
    - "calculate" → Route to start_box3 to begin tax calculation
    
    Args:
        state: Current graph state
        
    Returns:
        Command with routing decision
    """
    logger.info(f"HITL Control Node - next_action: {state.next_action}, status: {state.status}")
    
    if state.next_action == "await_human":
        # Pause and wait for human command
        # The graph will interrupt before this node on next invocation
        logger.info("⏸  Pausing execution - awaiting human command")
        return Command(
            update={
                "status": "awaiting_human",
                "paused_at_node": "hitl_control",
            }
            # No goto needed - interrupt_before will pause before re-execution
        )
    
    elif state.next_action == "ingest_more":
        # Loop back to dispatcher to process new documents
        logger.info("🔄 Resuming ingestion mode - processing new documents")
        
        # Check if we have any documents to process
        if not state.documents:
            logger.warning("No documents to process - staying at HITL node")
            return Command(
                update={
                    "status": "awaiting_human",
                    "paused_at_node": "hitl_control",
                    "next_action": "await_human",  # Reset to await
                    "validation_warnings": state.validation_warnings + ["No new documents to process"]
                }
                # Graph will interrupt before re-execution of this node
            )
        
        return Command(
            update={
                "status": "ingesting",
                "next_action": "await_human",  # Reset for next pause
            },
            goto="dispatcher"
        )
    
    elif state.next_action == "calculate":
        # Proceed to Box 3 calculation
        logger.info("🧮 Starting tax calculation")
        
        # Validation checks before proceeding
        if state.status == "quarantine":
            logger.warning("Cannot calculate - state is in quarantine")
            return Command(
                update={
                    "status": "complete",
                    "validation_errors": state.validation_errors + [
                        "Cannot proceed to calculation - critical data validation failed"
                    ]
                }
                # Graph will interrupt before re-execution of this node
            )
        
        # Check if we have any Box 3 assets
        if state.box3_total_assets_jan1 <= 0:
            logger.info("No Box 3 assets - skipping Box 3 calculation")
            return Command(
                update={
                    "status": "complete",
                    "validation_warnings": state.validation_warnings + [
                        "No Box 3 assets found - Box 3 calculation skipped"
                    ]
                }
                # Graph will interrupt before re-execution of this node
            )
        
        # All checks passed - proceed to Box 3
        return Command(
            update={
                "status": "calculating",
            },
            goto="start_box3"
        )
    
    else:
        # Unknown action - error state
        logger.error(f"Unknown next_action: {state.next_action}")
        return Command(
                update={
                    "status": "error",
                    "validation_errors": state.validation_errors + [
                        f"Invalid next_action: {state.next_action}"
                    ]
                }
                # Graph will interrupt before re-execution of this node
            )

