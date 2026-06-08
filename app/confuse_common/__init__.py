"""
ConFuse Common - Shared Python Library

This package provides:
- Event schemas matching the Protobuf definitions
- Kafka producer/consumer helpers for Confluent Cloud
- Authentication, rate limiting, and security middleware
- Configuration utilities for ConFuse services
"""

# Events module
from .events import (
    KafkaConfig,
    Topics,
    EventHeaders,
    EventMetadata,
    FileType,
    SourceType,
    CodeIngestedEvent,
    CodeProcessedEvent,
    CodeChunk,
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
    EventProducer,
    EventConsumer,
    EventHandler,
)

# Middleware module
from .middleware import (
    AuthMiddleware,
    AuthenticatedUser,
    get_current_user,
    get_optional_user,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
)

# Config module
from .config import (
    BaseConFuseApp,
    BaseServiceApp,
    BaseConFuseSettings,
    get_settings,
)

__version__ = "0.2.0"

__all__ = [
    # Events
    "KafkaConfig",
    "Topics",
    "EventHeaders",
    "EventMetadata",
    "FileType",
    "SourceType",
    "CodeIngestedEvent",
    "CodeProcessedEvent",
    "CodeChunk",
    "DocsIngestedEvent",
    "DocsProcessedEvent",
    "DocChunk",
    "EmbeddingGeneratedEvent",
    "GraphUpdatedEvent",
    "GraphBuildRequestedEvent",
    "GraphBuildCompletedEvent",
    "SourceSyncRequestedEvent",
    "SourceSyncCompletedEvent",
    "SourceSyncFailedEvent",
    "ProcessingFailedEvent",
    "EventProducer",
    "EventConsumer",
    "EventHandler",
    # Middleware
    "AuthMiddleware",
    "AuthenticatedUser",
    "get_current_user",
    "get_optional_user",
    "RateLimitMiddleware",
    "SecurityHeadersMiddleware",
    # Config
    "BaseConFuseApp",
    "BaseServiceApp",
    "BaseConFuseSettings",
    "get_settings",
]
