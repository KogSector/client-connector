"""
Graphify Episode — Canonical Data Contract

Defines the standardised episode schema that all ConFuse microservices use
when emitting processed data to Graphify. This is the canonical handoff unit
between ingestion, embedding, and the Graphify knowledge graph.

Episode = chunk + metadata + embedding (optional at emission time).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ── Source type taxonomy ──────────────────────────────────────────────────────

class EpisodeSourceType(str, Enum):
    """Content source categories for Graphify episodes."""
    CODEBASE = "codebase"
    DOCUMENT = "document"
    WEB = "web"
    VIDEO = "video"
    AUDIO = "audio"
    IMAGE = "image"
    CHAT = "chat"
    MESSAGE = "message"
    UNKNOWN = "unknown"


class EpisodeChunkType(str, Enum):
    """Granularity / semantic type of the chunk."""
    # Codebase types
    FUNCTION = "function"
    CLASS = "class"
    MODULE = "module"
    IMPORT = "import"
    CODE_BLOCK = "code_block"
    DOCSTRING = "docstring"
    # Document types
    SECTION = "section"
    PARAGRAPH = "paragraph"
    SENTENCE = "sentence"
    TABLE = "table"
    CITATION = "citation"
    # Web types
    PAGE_OVERVIEW = "page_overview"
    WEB_SECTION = "web_section"
    WEB_METADATA = "web_metadata"
    # Media types
    VIDEO_SEGMENT = "video_segment"
    AUDIO_SEGMENT = "audio_segment"
    KEYFRAME = "keyframe"
    TRANSCRIPT = "transcript"
    # Chat types
    THREAD = "thread"
    MESSAGE_TURN = "message_turn"
    # Generic
    MIXED = "mixed"
    RAW = "raw"


# ── Sub-models ────────────────────────────────────────────────────────────────

class EpisodeMetadata(BaseModel):
    """
    Content-type-specific metadata attached to every episode.

    Fields are optional because not all content types produce all metadata.
    """
    mime_type: Optional[str] = None
    filename: Optional[str] = None
    author: Optional[str] = None
    language: Optional[str] = None
    # Document-specific
    title: Optional[str] = None
    page_number: Optional[int] = None
    heading: Optional[str] = None
    # Code-specific
    symbol_name: Optional[str] = None
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    complexity: Optional[int] = None
    # Media-specific
    duration_ms: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    exif: Optional[Dict[str, Any]] = None
    transcript: Optional[str] = None
    # Chat-specific
    participant: Optional[str] = None
    thread_id: Optional[str] = None
    # Entity hints for downstream graph construction
    entity_hints: List[Dict[str, Any]] = Field(default_factory=list)
    # Relationship hints for downstream graph construction
    relationship_hints: List[Dict[str, Any]] = Field(default_factory=list)
    # Arbitrary key-value pairs for extensibility
    extra: Dict[str, Any] = Field(default_factory=dict)


class EpisodeProvenance(BaseModel):
    """
    Provenance tracking — which service produced this episode, when, and how.
    Enables auditability and replay from any point in the pipeline.
    """
    origin_service: str = Field(
        ...,
        description="Service that created this episode (e.g. 'data-connector', 'unified-processor')",
    )
    version: str = Field(
        default="1.0.0",
        description="Schema version for forward/backward compatibility",
    )
    pipeline_run_id: Optional[str] = Field(
        default=None,
        description="ID of the pipeline run that created this episode",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp when this episode was created",
    )
    parent_episode_id: Optional[str] = Field(
        default=None,
        description="ID of the parent episode if this is a derived/split episode",
    )


# ── Canonical Episode ─────────────────────────────────────────────────────────

class GraphifyEpisode(BaseModel):
    """
    Canonical episode contract for Graphify ingestion.

    This is the standardised handoff unit used across all ConFuse services:
    - data-connector → Kafka → Graphify
    - embeddings-service → Kafka → Graphify
    - unified-processor → Graphify (direct or Kafka)

    Fields are designed to be content-type-agnostic while supporting
    rich metadata for every supported source type.
    """

    # ── Identity ──────────────────────────────────────────────────────────
    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Globally unique episode identifier",
    )
    source_type: EpisodeSourceType = Field(
        ...,
        description="Content source category",
    )
    source_id: str = Field(
        ...,
        description="Identifier of the source (repo ID, document ID, URL, etc.)",
    )

    # ── Content ───────────────────────────────────────────────────────────
    chunk_text: str = Field(
        ...,
        description="The actual text content of this episode chunk",
    )
    chunk_type: EpisodeChunkType = Field(
        default=EpisodeChunkType.RAW,
        description="Semantic type / granularity of this chunk",
    )

    # ── Embedding (populated by embeddings-service) ───────────────────────
    embedding: Optional[List[float]] = Field(
        default=None,
        description="Float vector embedding — populated after embedding generation",
    )
    embedding_model: Optional[str] = Field(
        default=None,
        description="Name of the model used to generate the embedding",
    )
    embedding_dimension: Optional[int] = Field(
        default=None,
        description="Dimensionality of the embedding vector",
    )

    # ── Context ───────────────────────────────────────────────────────────
    language: Optional[str] = Field(
        default=None,
        description="Programming or natural language of the content",
    )
    content_path: Optional[str] = Field(
        default=None,
        description="File path, URL, or location within the source",
    )
    group_id: Optional[str] = Field(
        default=None,
        description="Logical grouping / tenant ID for graph partitioning",
    )

    # ── Timestamps ────────────────────────────────────────────────────────
    start_timestamp: Optional[datetime] = Field(
        default=None,
        description="Start time for temporal content (video/audio segments)",
    )
    end_timestamp: Optional[datetime] = Field(
        default=None,
        description="End time for temporal content (video/audio segments)",
    )

    # ── Rich metadata ─────────────────────────────────────────────────────
    metadata: EpisodeMetadata = Field(
        default_factory=EpisodeMetadata,
        description="Content-type-specific metadata",
    )

    # ── Provenance ────────────────────────────────────────────────────────
    provenance: EpisodeProvenance = Field(
        ...,
        description="Origin and version tracking",
    )

    # ── Security / Governance ─────────────────────────────────────────────
    pii_detected: bool = Field(
        default=False,
        description="Whether PII was detected in this episode's content",
    )
    acl_tags: List[str] = Field(
        default_factory=list,
        description="Access control tags for graph query authorization",
    )

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }

    def to_kafka_payload(self) -> dict:
        """Serialize to a Kafka-friendly dict (JSON-serializable)."""
        return self.model_dump(mode="json")

    @classmethod
    def from_kafka_payload(cls, payload: dict) -> "GraphifyEpisode":
        """Deserialize from a Kafka payload dict."""
        return cls.model_validate(payload)
