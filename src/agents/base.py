"""Abstract base class for all Polyglot Swarm agents."""

from abc import ABC, abstractmethod
from typing import Any

from src.orchestrator.state import LearnerState


class BaseAgent(ABC):
    """Base class that all agents must implement.

    Each agent:
    1. Receives the full LearnerState
    2. Processes its specific concern (grammar, vocabulary, etc.)
    3. Returns a partial state update dict
    """

    name: str = "base_agent"

    @abstractmethod
    async def process(self, state: LearnerState) -> dict[str, Any]:
        """Process the current state and return updates.

        Args:
            state: Current LearnerState from the graph.

        Returns:
            Dictionary of state keys to update.
        """
        ...

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}>"
