"""Human-in-the-loop control node for managing ingestion/calculation flow."""

import logging
from typing import Literal

from langgraph.types import Command

from dutch_tax_agent.schemas.state import TaxGraphState

logger = logging.getLogger(__name__)


def hitl_control_node(state: TaxGraphState) -> Command[Literal["dispatcher", "start_box3", "__end__"]]:
    """Human-in-the-loop control node.
    
    This node pauses execution and waits for human commands, then routes
    the graph based on the user's next action:
    - "await_human" → Pause (goto END)
    - "ingest_more" → Loop back to dispatcher for more documents
    - "calculate" → Proceed to Box 3 calculation
    
    Args:
        state: Current graph state
        
    Returns:
        Command with routing decision
    """
    logger.info(f"HITL Control Node - next_action: {state.next_action}, status: {state.status}")
    
    if state.next_action == "await_human":
        # Pause and wait for human command
        logger.info("⏸  Pausing execution - awaiting human command")
        return Command(
            update={
                "status": "awaiting_human",
                "paused_at_node": "hitl_control",
            },
            goto="__end__"
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
                },
                goto="__end__"
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
                },
                goto="__end__"
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
                },
                goto="__end__"
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
            },
            goto="__end__"
        )

