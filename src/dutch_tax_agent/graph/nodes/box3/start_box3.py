"""Start Box 3 calculation node for the main graph.

This node acts as a passthrough that triggers parallel Box 3 calculations.
"""

import logging

from dutch_tax_agent.schemas.state import TaxGraphState

logger = logging.getLogger(__name__)


def start_box3_node(state: TaxGraphState) -> dict:
    """Passthrough node that triggers parallel Box 3 calculations.
    
    Args:
        state: Current graph state
        
    Returns:
        State dict (unchanged, just passes through)
    """
    logger.info("Starting parallel Box 3 calculations")
    return {"status": "calculating"}

