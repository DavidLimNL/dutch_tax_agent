"""Parser agents for different document types."""

from dutch_tax_agent.graph.agents.dutch_parser import dutch_parser_agent
from dutch_tax_agent.graph.agents.salary_parser import salary_parser_agent
from dutch_tax_agent.graph.agents.us_broker_parser import us_broker_parser_agent

__all__ = ["dutch_parser_agent", "us_broker_parser_agent", "salary_parser_agent"]


