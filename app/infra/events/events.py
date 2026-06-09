"""
Event Definitions for ConFuse Platform

Python event classes that correspond to the Protobuf definitions.
These are used for serialization/deserialization with Kafka.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional, List
from pydantic import BaseModel, Field
import uuid

from .topics import Topics


# =============================================================================
# Common Types
# =============================================================================


class FileType(str, Enum):
    """File type classification"""
    UNKNOWN = "unknown"
    CODE = "code"
    DOCUMENT = "document"


class SourceType(str, Enum):
    """Source types for ingestion"""
    UNKNOWN = "unknown"
    GITHUB = "github"
    GITLAB = "gitlab"
    BITBUCKET = "bitbucket"
    LOCAL = "local"
    GOOGLE_DRIVE = "google_drive"
    NOTION = "notion"
    FILE_UPLOAD = "file_upload"
    DROPBOX = "dropbox"
    ONEDRIVE = "onedrive"
    WEB = "web"
    URL = "url"


class EventHeaders(BaseModel):
    """Event headers included in all events"""
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: str
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    source_service: str
    correlation_id: Optional[str] = None
    trace_id: Optional[str] = None
    
    @classmethod
    def create(cls, source_service: str, event_type: str) -> "EventHeaders":
        return cls(
            source_service=source_service,
            event_type=event_type,
        )


class EventMetadata(BaseModel):
    """Event metadata for processing context"""
    retry_count: int = 0
    original_event_id: Optional[str] = None
    user_id: Optional[str] = None
    tenant_id: Optional[str] = None


# =============================================================================
# Code Events
# =============================================================================


class CodeIngestedEvent(BaseModel):
    """
    Event published when a code file is ingested
    Topic: code.ingested
    """
    headers: EventHeaders
    metadata: EventMetadata = Field(default_factory=EventMetadata)
    file_id: str
    source_id: str
    file_path: str
    file_name: str
    file_extension: str
    file_size_bytes: int
    content_hash: str
    storage_location: str
    language: str
    is_config: bool = False
    
    @staticmethod
    def topic() -> str:
        return Topics.CODE_INGESTED


class StreamedFileEvent(BaseModel):
    """
    Event published when a file is streamed directly over Kafka.
    Used for repo code files and temporary documents.
    Topic: code.ingested
    """
    repo_id: str
    file_path: str
    content: str
    url: str
    user_id: Optional[str] = None
    is_deleted: bool = False

    @staticmethod
    def topic() -> str:
        return "code.ingested"


class CodeChunk(BaseModel):
    """Processed code chunk with AST information"""
    chunk_id: str
    content: str
    start_line: int
    end_line: int
    chunk_type: str
    name: Optional[str] = None
    parent_name: Optional[str] = None
    signature: Optional[str] = None


class CodeProcessedEvent(BaseModel):
    """
    Event published when a code file has been processed
    Topic: code.processed
    """
    headers: EventHeaders
    metadata: EventMetadata = Field(default_factory=EventMetadata)
    file_id: str
    source_id: str
    language: str
    chunks: List[CodeChunk]
    functions_count: int = 0
    classes_count: int = 0
    imports: List[str] = Field(default_factory=list)
    processing_time_ms: int
    
    @staticmethod
    def topic() -> str:
        return Topics.CODE_PROCESSED


# =============================================================================
# Document Events
# =============================================================================


class DocsIngestedEvent(BaseModel):
    """
    Event published when a document is ingested
    Topic: docs.ingested
    """
    headers: EventHeaders
    metadata: EventMetadata = Field(default_factory=EventMetadata)
    file_id: str
    source_id: str
    file_path: str
    file_name: str
    file_extension: str
    file_size_bytes: int
    content_hash: str
    storage_location: str
    document_type: str
    
    @staticmethod
    def topic() -> str:
        return Topics.DOCS_INGESTED


class DocChunk(BaseModel):
    """Processed document chunk"""
    chunk_id: str
    content: str
    page_number: Optional[int] = None
    chunk_type: str
    section_heading: Optional[str] = None


class ExtractedTable(BaseModel):
    """Table extracted from document"""
    table_id: str
    page_number: Optional[int] = None
    row_count: int
    column_count: int
    content_markdown: str


class DocsProcessedEvent(BaseModel):
    """
    Event published when a document has been processed
    Topic: docs.processed
    """
    headers: EventHeaders
    metadata: EventMetadata = Field(default_factory=EventMetadata)
    file_id: str
    source_id: str
    document_type: str
    chunks: List[DocChunk]
    page_count: int = 0
    word_count: int = 0
    has_tables: bool = False
    tables: List[ExtractedTable] = Field(default_factory=list)
    has_images: bool = False
    processing_time_ms: int
    
    @staticmethod
    def topic() -> str:
        return Topics.DOCS_PROCESSED


# =============================================================================
# Embedding Events
# =============================================================================


class EmbeddingGeneratedEvent(BaseModel):
    """
    Event published when embeddings have been generated
    Topic: embedding.generated
    """
    headers: EventHeaders
    metadata: EventMetadata = Field(default_factory=EventMetadata)
    file_id: str
    source_id: str
    chunk_ids: List[str]
    embedding_model: str
    embedding_dimension: int
    total_chunks: int
    vector_storage_location: Optional[str] = None
    processing_time_ms: int
    
    @staticmethod
    def topic() -> str:
        return Topics.EMBEDDING_GENERATED


# =============================================================================
# Graph Events
# =============================================================================


class GraphRelationship(BaseModel):
    """Relationship in knowledge graph"""
    source_node_id: str
    target_node_id: str
    relationship_type: str
    properties: Optional[str] = None


class GraphUpdatedEvent(BaseModel):
    """
    Event published when the knowledge graph has been updated
    Topic: graph.updated
    """
    headers: EventHeaders
    metadata: EventMetadata = Field(default_factory=EventMetadata)
    source_id: str
    file_id: Optional[str] = None
    nodes_added: int = 0
    nodes_updated: int = 0
    edges_added: int = 0
    edges_updated: int = 0
    sample_relationships: List[GraphRelationship] = Field(default_factory=list)
    processing_time_ms: int
    
    @staticmethod
    def topic() -> str:
        return Topics.GRAPH_UPDATED


class GraphBuildRequestedEvent(BaseModel):
    """
    Event to request a graph build
    Topic: graph.build.requested
    """
    headers: EventHeaders
    metadata: EventMetadata = Field(default_factory=EventMetadata)
    source_id: str
    force_rebuild: bool = False
    build_type: str = "incremental"
    
    @staticmethod
    def topic() -> str:
        return Topics.GRAPH_BUILD_REQUESTED


class GraphBuildCompletedEvent(BaseModel):
    """
    Event published when graph build completes
    Topic: graph.build.completed
    """
    headers: EventHeaders
    metadata: EventMetadata = Field(default_factory=EventMetadata)
    source_id: str
    relationships_created: int
    entities_created: int
    build_time_ms: int
    build_type: str
    
    @staticmethod
    def topic() -> str:
        return Topics.GRAPH_BUILD_COMPLETED


# =============================================================================
# Source Sync Events
# =============================================================================


class SourceSyncRequestedEvent(BaseModel):
    """
    Event triggered when source sync is requested
    Topic: source.sync.requested
    """
    headers: EventHeaders
    metadata: EventMetadata = Field(default_factory=EventMetadata)
    source_id: str
    source_type: SourceType
    source_url: str
    branch: Optional[str] = None
    access_token: Optional[str] = None
    full_sync: bool = False
    requested_by: Optional[str] = None
    
    @staticmethod
    def topic() -> str:
        return Topics.SOURCE_SYNC_REQUESTED


class SourceSyncCompletedEvent(BaseModel):
    """
    Event triggered when source sync completes
    Topic: source.sync.completed
    """
    headers: EventHeaders
    metadata: EventMetadata = Field(default_factory=EventMetadata)
    source_id: str
    files_processed: int
    code_files_count: int = 0
    doc_files_count: int = 0
    duration_ms: int
    job_id: Optional[str] = None
    
    @staticmethod
    def topic() -> str:
        return Topics.SOURCE_SYNC_COMPLETED


class SourceSyncFailedEvent(BaseModel):
    """
    Event triggered when source sync fails
    Topic: source.sync.failed
    """
    headers: EventHeaders
    metadata: EventMetadata = Field(default_factory=EventMetadata)
    source_id: str
    error: str
    error_code: str
    job_id: Optional[str] = None
    
    @staticmethod
    def topic() -> str:
        return Topics.SOURCE_SYNC_FAILED


# =============================================================================
# DLQ Events
# =============================================================================


class ProcessingFailedEvent(BaseModel):
    """
    Event published when processing fails
    Topic: dlq.processing.failed
    """
    headers: EventHeaders
    metadata: EventMetadata = Field(default_factory=EventMetadata)
    original_topic: str
    original_event_id: str
    error_message: str
    error_type: str
    error_code: str
    retry_count: int
    is_retryable: bool = False
    original_payload: str
    error_timestamp: str
    failed_service: str
    
    @staticmethod
    def topic() -> str:
        return Topics.DLQ_PROCESSING_FAILED


# =============================================================================
# Event-Driven Pipeline Events (Refactored Architecture)
# =============================================================================


class RepoIngestRequestedEvent(BaseModel):
    """
    Event published when a repository ingestion is requested
    Topic: repo-events
    """
    event_type: str = "REPO_INGEST_REQUESTED"
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    correlation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    payload: "RepoIngestRequestedPayload"
    
    @staticmethod
    def topic() -> str:
        return Topics.REPO_EVENTS


class RepoIngestRequestedPayload(BaseModel):
    """Payload for REPO_INGEST_REQUESTED event"""
    repo_id: str
    url: str
    branch: str
    provider: str  # github, gitlab, bitbucket
    commit_id: str
    credential_ref: str  # JWT token for credential exchange
    user_id: str
    organization_id: Optional[str] = None


class RepoUpdatedEvent(BaseModel):
    """
    Event published when a repository is updated (webhook)
    Topic: repo-events
    """
    event_type: str = "REPO_UPDATED"
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    correlation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    payload: "RepoUpdatedPayload"
    
    @staticmethod
    def topic() -> str:
        return Topics.REPO_EVENTS


class RepoUpdatedPayload(BaseModel):
    """Payload for REPO_UPDATED event"""
    repo_id: str
    url: str
    branch: str
    provider: str
    old_commit: str
    new_commit: str
    credential_ref: str
    update_type: str  # push, force_push, branch_update


class RepoIngestFailedEvent(BaseModel):
    """
    Event published when repository ingestion fails
    Topic: repo-events
    """
    event_type: str = "REPO_INGEST_FAILED"
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    correlation_id: str
    payload: "RepoIngestFailedPayload"
    
    @staticmethod
    def topic() -> str:
        return Topics.REPO_EVENTS


class RepoIngestFailedPayload(BaseModel):
    """Payload for REPO_INGEST_FAILED event"""
    repo_id: str
    error_code: str  # CLONE_FAILED, AUTH_FAILED, INVALID_REPO, PROCESSING_FAILED, TIMEOUT
    error_message: str
    retry_count: int = 0
    fatal: bool = False


class RepoIngestCompletedEvent(BaseModel):
    """
    Event published when repository ingestion completes successfully
    Topic: repo-events
    """
    event_type: str = "REPO_INGEST_COMPLETED"
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    correlation_id: str
    payload: "RepoIngestCompletedPayload"
    
    @staticmethod
    def topic() -> str:
        return Topics.REPO_EVENTS


class RepoIngestCompletedPayload(BaseModel):
    """Payload for REPO_INGEST_COMPLETED event"""
    repo_id: str
    commit_id: str
    stats: "RepoIngestStats"


class RepoIngestStats(BaseModel):
    """Statistics for repository ingestion"""
    files_processed: int
    chunks_created: int
    processing_duration_ms: int
    repository_size_bytes: int

