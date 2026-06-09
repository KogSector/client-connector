"""
Topic Constants for ConFuse Platform

Defines all Kafka topics used in the platform.
These should match the topics pre-created in Confluent Cloud.
"""


class Topics:
    """All Kafka topics used by ConFuse platform"""

    # Source Sync Topics (data-connector → unified-processor)
    # Producer: data-connector
    # Consumer: unified-processor
    SOURCE_SYNC_REQUESTED = "source.sync.requested"
    SOURCE_SYNC_COMPLETED = "source.sync.completed"
    SOURCE_SYNC_FAILED = "source.sync.failed"

    # Chunk Processing Topics (unified-processor → embeddings-service)
    # Producer: unified-processor
    # Consumer: embeddings-service
    CHUNKS_RAW = "chunks.raw"

    # Embedding Topics (embeddings-service → unified-processor)
    # Producer: embeddings-service
    # Consumer: unified-processor
    EMBEDDING_GENERATED = "embedding.generated"

    # Graphify Episodes (data-connector → graphify-pipeline)
    # Producer: data-connector
    GRAPHIFY_EPISODES = "graphify.episodes.v1"

    # Code Processing Topics
    CODE_INGESTED = "code.ingested"
    CODE_PROCESSED = "code.processed"

    # Document Processing Topics
    DOCS_INGESTED = "docs.ingested"
    DOCS_PROCESSED = "docs.processed"

    # Graph Processing Topics
    GRAPH_UPDATED = "graph.updated"
    GRAPH_BUILD_REQUESTED = "graph.build.requested"
    GRAPH_BUILD_COMPLETED = "graph.build.completed"

    # Dead Letter Queue Topics
    DLQ_PROCESSING_FAILED = "dlq.processing.failed"

    # Event-Driven Pipeline Topics (repo event pipeline)
    REPO_EVENTS = "repo-events"

    @classmethod
    def all(cls) -> list[str]:
        """Get all active topics for Confluent Cloud provisioning"""
        return [
            cls.SOURCE_SYNC_REQUESTED,
            cls.SOURCE_SYNC_COMPLETED,
            cls.SOURCE_SYNC_FAILED,
            cls.CHUNKS_RAW,
            cls.EMBEDDING_GENERATED,
            cls.GRAPHIFY_EPISODES,
            cls.CODE_INGESTED,
            cls.CODE_PROCESSED,
            cls.DOCS_INGESTED,
            cls.DOCS_PROCESSED,
            cls.GRAPH_UPDATED,
            cls.GRAPH_BUILD_REQUESTED,
            cls.GRAPH_BUILD_COMPLETED,
            cls.DLQ_PROCESSING_FAILED,
            cls.REPO_EVENTS,
        ]
