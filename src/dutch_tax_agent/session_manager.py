"""Session management for HITL workflows."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from langgraph.checkpoint.base import BaseCheckpointSaver

from dutch_tax_agent.schemas.state import TaxGraphState

logger = logging.getLogger(__name__)


class SessionManager:
    """Manages session persistence and resume logic for HITL workflows."""
    
    def __init__(self, registry_path: Optional[Path] = None):
        """Initialize session manager.
        
        Args:
            registry_path: Path to session registry JSON file
        """
        if registry_path is None:
            registry_path = Path.home() / ".dutch_tax_agent" / "sessions.json"
        
        self.registry_path = registry_path
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Create empty registry if it doesn't exist
        if not self.registry_path.exists():
            self._save_registry({})
    
    def _load_registry(self) -> dict:
        """Load session registry from disk."""
        try:
            with open(self.registry_path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError) as e:
            logger.warning(f"Failed to load session registry: {e}. Creating new registry.")
            return {}
    
    def _save_registry(self, registry: dict):
        """Save session registry to disk."""
        with open(self.registry_path, "w") as f:
            json.dump(registry, f, indent=2)
    
    def create_session(
        self, 
        thread_id: str, 
        tax_year: int,
        has_fiscal_partner: bool = True
    ) -> dict:
        """Register new session.
        
        Args:
            thread_id: Unique thread/session ID
            tax_year: Tax year being processed
            has_fiscal_partner: Whether fiscal partner is assumed
            
        Returns:
            Session metadata dict
        """
        registry = self._load_registry()
        
        session_data = {
            "thread_id": thread_id,
            "tax_year": tax_year,
            "has_fiscal_partner": has_fiscal_partner,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "status": "active",
        }
        
        registry[thread_id] = session_data
        self._save_registry(registry)
        
        logger.info(f"Created session: {thread_id} (tax year {tax_year})")
        
        return session_data
    
    def update_session(self, thread_id: str, updates: dict):
        """Update session metadata.
        
        Args:
            thread_id: Session ID to update
            updates: Dict of fields to update
        """
        registry = self._load_registry()
        
        if thread_id not in registry:
            logger.warning(f"Session {thread_id} not found in registry")
            return
        
        registry[thread_id].update(updates)
        registry[thread_id]["last_updated"] = datetime.now(timezone.utc).isoformat()
        
        self._save_registry(registry)
        logger.info(f"Updated session {thread_id}: {list(updates.keys())}")
    
    def get_session(self, thread_id: str) -> Optional[dict]:
        """Get session metadata.
        
        Args:
            thread_id: Session ID to retrieve
            
        Returns:
            Session metadata dict, or None if not found
        """
        registry = self._load_registry()
        return registry.get(thread_id)
    
    def list_sessions(self, active_only: bool = True) -> list[dict]:
        """List all sessions.
        
        Args:
            active_only: If True, only return active sessions
            
        Returns:
            List of session metadata dicts
        """
        registry = self._load_registry()
        sessions = list(registry.values())
        
        if active_only:
            sessions = [s for s in sessions if s.get("status") == "active"]
        
        # Sort by last_updated (most recent first)
        sessions.sort(key=lambda s: s.get("last_updated", ""), reverse=True)
        
        return sessions
    
    def delete_session(self, thread_id: str):
        """Delete session from registry.
        
        Note: This does NOT delete the checkpoint data itself, only the registry entry.
        
        Args:
            thread_id: Session ID to delete
        """
        registry = self._load_registry()
        
        if thread_id in registry:
            del registry[thread_id]
            self._save_registry(registry)
            logger.info(f"Deleted session {thread_id} from registry")
        else:
            logger.warning(f"Session {thread_id} not found in registry")
    
    def get_current_state(
        self, 
        checkpointer: BaseCheckpointSaver,
        thread_id: str
    ) -> Optional[TaxGraphState]:
        """Get latest state from checkpoint.
        
        Args:
            checkpointer: The checkpointer instance from the graph
            thread_id: Thread ID to get state for
            
        Returns:
            TaxGraphState instance, or None if not found
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
            
            # LangGraph stores state in channel_values, but the structure can vary
            # Try multiple strategies to find the state:
            
            # Strategy 1: Look for dict with "tax_year" key (most common case)
            for key, value in channel_values.items():
                if isinstance(value, dict) and "tax_year" in value:
                    try:
                        return TaxGraphState(**value)
                    except Exception as e:
                        logger.debug(f"Failed to parse state from key '{key}': {e}")
                        continue
            
            # Strategy 2: Try keys that might match the state class name
            state_class_name = "TaxGraphState"
            for key in [state_class_name, state_class_name.lower(), "state", "__state__"]:
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
                        # Try to create state even if tax_year is missing (might be default)
                        return TaxGraphState(**value)
                    except Exception as e:
                        logger.debug(f"Failed to parse state from single key '{key}': {e}")
            
            # Strategy 4: Check if channel_values itself is the state (unlikely but possible)
            if isinstance(channel_values, dict) and "tax_year" in channel_values:
                try:
                    return TaxGraphState(**channel_values)
                except Exception as e:
                    logger.debug(f"Failed to parse channel_values as state: {e}")
            
            # If all strategies fail, log detailed info for debugging
            channel_keys = list(channel_values.keys())
            logger.warning(
                f"Could not parse state from checkpoint for thread {thread_id}. "
                f"Channel keys found: {channel_keys}"
            )
            # Log structure of values for debugging
            for key, value in list(channel_values.items())[:3]:  # Log first 3 keys
                if isinstance(value, dict):
                    value_keys = list(value.keys())[:15]  # First 15 keys
                    logger.debug(f"Key '{key}' is dict with keys: {value_keys}")
                else:
                    logger.debug(f"Key '{key}' is {type(value).__name__}: {str(value)[:100]}")
            
            return None
        except Exception as e:
            logger.error(f"Failed to get checkpoint state for thread {thread_id}: {e}", exc_info=True)
            return None
    
    def update_and_resume(
        self,
        graph: Any,
        thread_id: str,
        updates: dict,
        as_node: Optional[str] = None
    ) -> Any:
        """Update state and resume graph execution.
        
        Args:
            graph: The compiled graph with checkpointer
            thread_id: Thread ID to resume
            updates: State updates to apply
            as_node: Optional node name to apply updates as (for proper routing)
            
        Returns:
            Final state after resuming execution
        """
        try:
            config = {"configurable": {"thread_id": thread_id}}
            
            # Apply state updates
            logger.info(f"Applying state updates: {list(updates.keys())}")
            graph.update_state(config, updates, as_node=as_node)
            
            # Resume execution with None input (continues from checkpoint)
            logger.info(f"Resuming graph execution (thread: {thread_id})")
            final_state = graph.invoke(None, config=config)
            
            # Update session metadata
            self.update_session(thread_id, {"last_updated": datetime.now(timezone.utc).isoformat()})
            
            return final_state
        except Exception as e:
            logger.error(f"Failed to resume from checkpoint: {e}")
            raise

