"""
ConFuse Common Events Module

Event schemas and Kafka helpers for ConFuse platform.
"""

from .config import KafkaConfig
from .topics import Topics
from .events import (
    EventHeaders,
    EventMetadata,
    FileType,
    SourceType,
    CodeIngestedEvent,
    CodeProcessedEvent,
    CodeChunk,
    StreamedFileEvent,
    DocsIngestedEvent,
    DocsProcessedEvent,
    DocChunk,
    EmbeddingGeneratedEvent,
    GraphUpdatedEvent,
    GraphBuildRequestedEvent,
    GraphBuildCompletedEvent,
    SourceSyncRequestedEvent,
    SourceSyncCompletedEvent,
    SourceSyncFailedEvent,
    ProcessingFailedEvent,
    RepoIngestRequestedEvent,
    RepoIngestRequestedPayload,
    RepoUpdatedEvent,
    RepoUpdatedPayload,
    RepoIngestFailedEvent,
    RepoIngestFailedPayload,
    RepoIngestCompletedEvent,
    RepoIngestCompletedPayload,
    RepoIngestStats,
)
from .episode import (
    GraphifyEpisode,
    EpisodeSourceType,
    EpisodeChunkType,
    EpisodeMetadata,
    EpisodeProvenance,
)
from .producer import EventProducer
from .consumer import EventConsumer, EventHandler

__version__ = "0.2.0"

__all__ = [
    # Config
    "KafkaConfig",
    "Topics",
    # Common types
    "EventHeaders",
    "EventMetadata",
    "FileType",
    "SourceType",
    # Code events
    "CodeIngestedEvent",
    "CodeProcessedEvent",
    "CodeChunk",
    "StreamedFileEvent",
    # Document events
    "DocsIngestedEvent",
    "DocsProcessedEvent",
    "DocChunk",
    # Other events
    "EmbeddingGeneratedEvent",
    "GraphUpdatedEvent",
    "GraphBuildRequestedEvent",
    "GraphBuildCompletedEvent",
    "SourceSyncRequestedEvent",
    "SourceSyncCompletedEvent",
    "SourceSyncFailedEvent",
    "ProcessingFailedEvent",
    # Event-driven pipeline events
    "RepoIngestRequestedEvent",
    "RepoIngestRequestedPayload",
    "RepoUpdatedEvent",
    "RepoUpdatedPayload",
    "RepoIngestFailedEvent",
    "RepoIngestFailedPayload",
    "RepoIngestCompletedEvent",
    "RepoIngestCompletedPayload",
    "RepoIngestStats",
    # Graphify episodes
    "GraphifyEpisode",
    "EpisodeSourceType",
    "EpisodeChunkType",
    "EpisodeMetadata",
    "EpisodeProvenance",
    # Producer/Consumer
    "EventProducer",
    "EventConsumer",
    "EventHandler",
]
