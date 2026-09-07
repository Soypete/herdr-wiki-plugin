"""
Agent Contract - Shared interface for memory system adapters.

Vendored copy of the shared dataclasses/protocol so this plugin is
self-contained and installable on its own.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol, runtime_checkable


class RelationType(str, Enum):
    """Standard relation types for Phase B (Semantic Overlay)"""

    # Structural
    CONTAINS = "contains"
    PART_OF = "part_of"

    # Semantic
    IMPLEMENTS = "implements"
    DEPENDS_ON = "depends_on"
    USES_PATTERN = "uses_pattern"
    DOCUMENTS = "documents"

    # Cross-cutting
    SIMILAR_TO = "similar_to"
    CONTRADICTS = "contradicts"
    DERIVED_FROM = "derived_from"

    # Temporal
    SUPERSEDES = "supersedes"
    FOLLOWS = "follows"

    # Provenance
    COPIED_FROM = "copied_from"
    GENERATED_BY = "generated_by"


class Scope(str, Enum):
    """Search scope options"""

    ALL = "all"
    WING = "wing"
    ROOM = "room"
    DRAWER = "drawer"


@dataclass
class MemoryResult:
    """Single search result from memory system"""

    id: str
    content: str
    score: float
    source: str
    created_at: datetime


@dataclass
class Link:
    """A link between two memory items"""

    source_id: str
    target_id: str
    relation: str
    confidence: float = 1.0


@dataclass
class MemoryItem:
    """Complete memory item with metadata"""

    id: str
    content: str
    metadata: dict
    links: list[Link]
    created_at: datetime
    updated_at: datetime


@dataclass
class TraversalStep:
    """Single step in a path traversal"""

    from_id: str
    to_id: str
    relation: str
    reason: str


@dataclass
class PathExplanation:
    """Explanation of how system arrived at a result"""

    query: str
    steps: list[TraversalStep]
    total_hops: int
    confidence: float


@dataclass
class SystemStats:
    """System statistics"""

    total_items: int
    total_links: int
    wings: int
    rooms: int
    drawers: int
    storage_size_bytes: int


@runtime_checkable
class MemorySystem(Protocol):
    """
    All adapters must implement this interface.

    Used for fair comparison across LLMWiki, Graphify, and MemPalace.
    """

    def search_memory(
        self,
        query: str,
        scope: str = "all",
        top_k: int = 10,
    ) -> list[MemoryResult]:
        """Search memory system for relevant content."""
        ...

    def read_memory(self, id: str) -> MemoryItem:
        """Read a specific memory item by ID."""
        ...

    def explain_path(self, query_or_id: str) -> PathExplanation:
        """Explain how the system arrived at a result."""
        ...

    def write_memory(
        self,
        input: str,
        metadata: dict,
    ) -> str:
        """Write new content to memory. Returns ID of created item."""
        ...

    def link_memory(
        self,
        source_id: str,
        target_id: str,
        relation: str,
    ) -> bool:
        """Create a link between two memory items."""
        ...

    def get_stats(self) -> SystemStats:
        """Get system statistics."""
        ...


class ResultQuality(str, Enum):
    CORRECT = "Correct"
    PARTIAL = "Partial"
    INCORRECT = "Incorrect"


@dataclass
class ExperimentResult:
    """Result of a single experiment task"""

    date: datetime
    system: str
    phase: str
    task: str
    steps_taken: list[str]
    observations: str

    # Metrics
    turns: int
    search_ops: int
    latency_seconds: float
    notes: str

    result_quality: ResultQuality
    surprises_failures: str
    hypothesis_update: str
