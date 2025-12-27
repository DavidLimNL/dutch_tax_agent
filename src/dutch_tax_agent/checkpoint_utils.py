"""Utilities for working with LangGraph checkpoints.

These utilities help with:
- Inspecting checkpoint history
- Resuming from specific checkpoints
- Debugging state at any point in the graph
- Human-in-the-loop workflows
- Thread management and discovery
"""

import logging
from typing import Optional, Any
from uuid import uuid4
from datetime import datetime, timezone

from langgraph.checkpoint.base import BaseCheckpointSaver
from dutch_tax_agent.schemas.state import TaxGraphState

logger = logging.getLogger(__name__)


def generate_thread_id(prefix: str = "tax") -> str:
    """Generate a unique thread ID for a tax processing session.
    
    Args:
        prefix: Prefix for the thread ID (default: "tax")
        
    Returns:
        Unique thread ID string
    """
    return f"{prefix}-{uuid4().hex[:12]}"


def list_checkpoints(checkpointer: BaseCheckpointSaver, thread_id: str, limit: int = 10) -> list[dict]:
    """List all checkpoints for a given thread.
    
    Args:
        checkpointer: The checkpointer instance from the graph
        thread_id: Thread ID to list checkpoints for
        limit: Maximum number of checkpoints to return
        
    Returns:
        List of checkpoint metadata dicts
    """
    try:
        checkpoints = []
        config = {"configurable": {"thread_id": thread_id}}
        
        for checkpoint_tuple in checkpointer.list(config, limit=limit):
            checkpoint, metadata = checkpoint_tuple.checkpoint, checkpoint_tuple.metadata
            checkpoints.append({
                "checkpoint_id": checkpoint.get("id"),
                "thread_id": thread_id,
                "step": metadata.get("step", 0),
                "source": metadata.get("source", "unknown"),
                "writes": metadata.get("writes", {}),
            })
        
        return checkpoints
    except Exception as e:
        logger.error(f"Failed to list checkpoints for thread {thread_id}: {e}")
        return []


def get_checkpoint_state(
    checkpointer: BaseCheckpointSaver,
    thread_id: str,
    checkpoint_id: Optional[str] = None
) -> Optional[dict]:
    """Get the state at a specific checkpoint (raw dict format).
    
    Args:
        checkpointer: The checkpointer instance from the graph
        thread_id: Thread ID to get state for
        checkpoint_id: Specific checkpoint ID (if None, gets latest)
        
    Returns:
        State dict at the checkpoint, or None if not found
    """
    try:
        config = {"configurable": {"thread_id": thread_id}}
        if checkpoint_id:
            config["configurable"]["checkpoint_id"] = checkpoint_id
        
        checkpoint_tuple = checkpointer.get_tuple(config)
        if checkpoint_tuple:
            return checkpoint_tuple.checkpoint.get("channel_values", {})
        return None
    except Exception as e:
        logger.error(f"Failed to get checkpoint state for thread {thread_id}: {e}")
        return None


def get_thread_state(
    checkpointer: BaseCheckpointSaver,
    thread_id: str
) -> Optional[TaxGraphState]:
    """Get the latest state for a thread as a TaxGraphState object.
    
    Args:
        checkpointer: The checkpointer instance from the graph
        thread_id: Thread ID to get state for
        
    Returns:
        TaxGraphState instance, or None if not found or cannot be parsed
    """
    try:
        config = {"configurable": {"thread_id": thread_id}}
        checkpoint_tuple = checkpointer.get_tuple(config)
        
        if not checkpoint_tuple:
            logger.debug(f"No checkpoint found for thread {thread_id}")
            return None
        
        channel_values = checkpoint_tuple.checkpoint.get("channel_values", {})
        
        if not channel_values:
            logger.warning(f"Checkpoint exists but channel_values is empty for thread {thread_id}")
            return None
        
        # Try multiple strategies to find the state
        # Strategy 0: LangGraph stores state as flat channel values (each field is a top-level key)
        # Check if channel_values contains state fields directly (e.g., 'tax_year', 'documents')
        if "tax_year" in channel_values:
            try:
                # Filter out LangGraph internal keys (e.g., '__pregel_tasks', 'branch:to:hitl_control')
                state_dict = {
                    k: v for k, v in channel_values.items()
                    if not k.startswith("__") and ":" not in k
                }
                return TaxGraphState(**state_dict)
            except Exception as e:
                logger.debug(f"Failed to parse state from flat channel_values: {e}")
        
        # Strategy 1: Look for dict with "tax_year" key (nested structure)
        for key, value in channel_values.items():
            if isinstance(value, dict) and "tax_year" in value:
                try:
                    return TaxGraphState(**value)
                except Exception as e:
                    logger.debug(f"Failed to parse state from key '{key}': {e}")
                    continue
        
        # Strategy 2: Try common state key names
        for key in ["TaxGraphState", "taxgraphstate", "state", "__state__"]:
            if key in channel_values:
                value = channel_values[key]
                if isinstance(value, dict):
                    try:
                        return TaxGraphState(**value)
                    except Exception as e:
                        logger.debug(f"Failed to parse state from key '{key}': {e}")
        
        # Strategy 3: If channel_values has only one key, try that
        if len(channel_values) == 1:
            key, value = next(iter(channel_values.items()))
            if isinstance(value, dict):
                try:
                    return TaxGraphState(**value)
                except Exception as e:
                    logger.debug(f"Failed to parse state from single key '{key}': {e}")
        
        logger.warning(
            f"Could not parse state from checkpoint for thread {thread_id}. "
            f"Channel keys: {list(channel_values.keys())}"
        )
        return None
    except Exception as e:
        logger.error(f"Failed to get thread state for {thread_id}: {e}", exc_info=True)
        return None


def list_all_threads(checkpointer: BaseCheckpointSaver, limit: int = 100) -> list[dict]:
    """List all threads with their basic metadata.
    
    Note: This may be slow for large checkpoint databases.
    
    Args:
        checkpointer: The checkpointer instance
        limit: Maximum number of threads to return
        
    Returns:
        List of thread metadata dicts with: thread_id, tax_year, last_updated, 
        document_count, next_action
    """
    try:
        threads = {}
        
        # List checkpoints across all threads
        # Note: BaseCheckpointSaver doesn't have a "list all" method, 
        # so we need to use implementation-specific methods
        
        # For SqliteSaver, we can query the database directly
        if hasattr(checkpointer, 'conn'):
            cursor = checkpointer.conn.cursor()
            # Get distinct thread_ids
            cursor.execute("""
                SELECT DISTINCT thread_id 
                FROM checkpoints 
                ORDER BY checkpoint_id DESC 
                LIMIT ?
            """, (limit,))
            
            for (thread_id,) in cursor.fetchall():
                # Get the latest state for this thread
                state = get_thread_state(checkpointer, thread_id)
                if state:
                    threads[thread_id] = {
                        "thread_id": thread_id,
                        "tax_year": state.tax_year,
                        "last_updated": state.processing_started_at or datetime.now(timezone.utc).isoformat(),
                        "document_count": len(state.processed_documents),
                        "next_action": state.next_action,
                        "paused_at": state.paused_at_node,
                    }
        else:
            logger.warning("Checkpointer does not support listing all threads (not SqliteSaver)")
            return []
        
        # Sort by last_updated
        result = list(threads.values())
        result.sort(key=lambda x: x.get("last_updated", ""), reverse=True)
        
        return result
    except Exception as e:
        logger.error(f"Failed to list threads: {e}", exc_info=True)
        return []


def thread_exists(checkpointer: BaseCheckpointSaver, thread_id: str) -> bool:
    """Check if a thread exists in the checkpoint database.
    
    Args:
        checkpointer: The checkpointer instance
        thread_id: Thread ID to check
        
    Returns:
        True if thread exists, False otherwise
    """
    try:
        config = {"configurable": {"thread_id": thread_id}}
        checkpoint_tuple = checkpointer.get_tuple(config)
        return checkpoint_tuple is not None
    except Exception as e:
        logger.error(f"Failed to check if thread exists: {e}")
        return False


def resume_from_checkpoint(
    graph,
    thread_id: str,
    checkpoint_id: Optional[str] = None,
    updates: Optional[dict] = None
) -> Any:
    """Resume graph execution from a specific checkpoint.
    
    This is useful for human-in-the-loop workflows where you want to:
    1. Pause execution at a specific point (e.g., quarantine)
    2. Allow human to review and make corrections
    3. Resume execution with the corrected data
    
    Args:
        graph: The compiled graph with checkpointer
        thread_id: Thread ID to resume
        checkpoint_id: Specific checkpoint to resume from (if None, resumes from latest)
        updates: Optional state updates to apply before resuming
        
    Returns:
        Final state after resuming execution
    """
    try:
        config = {"configurable": {"thread_id": thread_id}}
        if checkpoint_id:
            config["configurable"]["checkpoint_id"] = checkpoint_id
        
        # If updates provided, apply them first
        if updates:
            logger.info(f"Applying state updates before resuming: {list(updates.keys())}")
            # Update the state with graph.update_state()
            graph.update_state(config, updates)
        
        # Resume execution
        logger.info(f"Resuming graph execution from checkpoint (thread: {thread_id})")
        final_state = graph.invoke(None, config=config)
        
        return final_state
    except Exception as e:
        logger.error(f"Failed to resume from checkpoint: {e}")
        raise


def inspect_state_at_node(
    checkpointer: BaseCheckpointSaver,
    thread_id: str,
    node_name: str
) -> Optional[dict]:
    """Inspect the state after a specific node executed.
    
    Useful for debugging or understanding what happened at each step.
    
    Args:
        checkpointer: The checkpointer instance
        thread_id: Thread ID to inspect
        node_name: Name of the node to inspect state after
        
    Returns:
        State dict after the node executed, or None if not found
    """
    try:
        config = {"configurable": {"thread_id": thread_id}}
        
        # Iterate through checkpoints to find the one after the target node
        for checkpoint_tuple in checkpointer.list(config):
            metadata = checkpoint_tuple.metadata
            if metadata.get("source") == node_name:
                return checkpoint_tuple.checkpoint.get("channel_values", {})
        
        logger.warning(f"No checkpoint found for node '{node_name}' in thread {thread_id}")
        return None
    except Exception as e:
        logger.error(f"Failed to inspect state at node {node_name}: {e}")
        return None


def print_checkpoint_history(checkpointer: BaseCheckpointSaver, thread_id: str, limit: int = 20) -> None:
    """Pretty-print the checkpoint history for debugging.
    
    Args:
        checkpointer: The checkpointer instance
        thread_id: Thread ID to print history for
        limit: Maximum number of checkpoints to print
    """
    print(f"\n{'='*80}")
    print(f"Checkpoint History for Thread: {thread_id}")
    print(f"{'='*80}\n")
    
    checkpoints = list_checkpoints(checkpointer, thread_id, limit=limit)
    
    if not checkpoints:
        print("No checkpoints found.")
        return
    
    for i, cp in enumerate(checkpoints, 1):
        print(f"{i}. Step {cp['step']} - Node: {cp['source']}")
        if cp.get("writes"):
            print(f"   Writes: {list(cp['writes'].keys())}")
        print()
    
    print(f"{'='*80}\n")

