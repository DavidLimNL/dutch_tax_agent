"""Parser agents for different document types."""

from dutch_tax_agent.graph.agents.dutch_parser import dutch_parser_agent
from dutch_tax_agent.graph.agents.investment_broker_parser import investment_broker_parser_agent
from dutch_tax_agent.graph.agents.salary_parser import salary_parser_agent

__all__ = ["dutch_parser_agent", "investment_broker_parser_agent", "salary_parser_agent"]


