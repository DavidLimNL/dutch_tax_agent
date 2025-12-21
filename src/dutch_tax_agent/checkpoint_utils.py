"""Utilities for working with LangGraph checkpoints.

These utilities help with:
- Inspecting checkpoint history
- Resuming from specific checkpoints
- Debugging state at any point in the graph
- Human-in-the-loop workflows
"""

import logging
from typing import Optional, Any
from uuid import uuid4

from langgraph.checkpoint.base import BaseCheckpointSaver

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
    """Get the state at a specific checkpoint.
    
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

