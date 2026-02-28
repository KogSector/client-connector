"""
Client Connector - Query Processor
Handles query processing pipeline: tokenize -> vectorize -> retrieve from data-vent -> format response
"""
import structlog
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field
import httpx

logger = structlog.get_logger()


@dataclass
class QueryResult:
    """Result from the query processing pipeline."""
    query: str
    chunks: List[Dict[str, Any]]
    vector_matches: int = 0
    graph_matches: int = 0
    completion_reached: bool = False
    total_time_ms: float = 0.0
    error: Optional[str] = None


class QueryProcessor:
    """
    Query processing pipeline for client-connector.
    Tokenizes queries, vectorizes via embeddings-service,
    retrieves from data-vent, and formats responses for MCP.
    """
    
    def __init__(
        self,
        data_vent_url: str = "http://data-vent:3005",
        embeddings_service_url: str = "http://embeddings-service:3001",
    ):
        self.data_vent_url = data_vent_url
        self.embeddings_service_url = embeddings_service_url
        self._http_client: Optional[httpx.AsyncClient] = None
    
    async def initialize(self):
        """Initialize HTTP client."""
        self._http_client = httpx.AsyncClient(timeout=30.0)
        logger.info("query_processor_initialized",
                     data_vent=self.data_vent_url,
                     embeddings=self.embeddings_service_url)
    
    async def close(self):
        """Clean up resources."""
        if self._http_client:
            await self._http_client.aclose()
    
    async def process_query(
        self,
        query: str,
        source_ids: Optional[List[str]] = None,
        limit: int = 20,
        search_type: str = "hybrid",  # "vector", "hybrid", "dfs"
    ) -> QueryResult:
        """
        Main query processing pipeline:
        1. Tokenize query
        2. Vectorize query via embeddings-service
        3. Send to data-vent for retrieval
        4. Format and return results
        """
        import time
        start_time = time.time()
        
        try:
            # Step 1: Tokenize query
            tokens = self.tokenize_query(query)
            logger.info("query_tokenized", token_count=len(tokens))
            
            # Step 2: Vectorize query
            query_vectors = await self.vectorize_query(query)
            if not query_vectors:
                return QueryResult(
                    query=query,
                    chunks=[],
                    error="Failed to vectorize query",
                )
            
            # Step 3: Retrieve from data-vent
            if search_type == "hybrid":
                result = await self._hybrid_search(query, query_vectors, limit, source_ids)
            elif search_type == "vector":
                result = await self._vector_search(query_vectors, limit, source_ids)
            else:
                result = await self._hybrid_search(query, query_vectors, limit, source_ids)
            
            total_time = (time.time() - start_time) * 1000
            result.total_time_ms = total_time
            
            logger.info("query_processed",
                         query=query[:50],
                         results=len(result.chunks),
                         time_ms=total_time)
            
            return result
            
        except Exception as e:
            logger.error("query_processing_failed", error=str(e), query=query[:50])
            return QueryResult(
                query=query,
                chunks=[],
                error=str(e),
            )
    
    def tokenize_query(self, query: str) -> List[str]:
        """Simple query tokenization."""
        # Basic tokenization: split on whitespace and punctuation
        import re
        tokens = re.findall(r'\w+', query.lower())
        return tokens
    
    async def vectorize_query(self, query: str) -> List[float]:
        """Call embeddings-service to vectorize the query."""
        try:
            response = await self._http_client.post(
                f"{self.embeddings_service_url}/api/v1/generate",
                json={"text": query},
            )
            response.raise_for_status()
            data = response.json()
            return data.get("embeddings", [])
        except Exception as e:
            logger.error("query_vectorization_failed", error=str(e))
            return []
    
    async def _vector_search(
        self,
        query_vectors: List[float],
        limit: int,
        source_ids: Optional[List[str]],
    ) -> QueryResult:
        """Vector-only search via data-vent."""
        try:
            payload = {
                "query_vectors": query_vectors,
                "limit": limit,
            }
            if source_ids:
                payload["source_ids"] = source_ids
            
            response = await self._http_client.post(
                f"{self.data_vent_url}/api/v1/search",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            
            return QueryResult(
                query="",
                chunks=data.get("chunks", []),
                vector_matches=data.get("total", 0),
            )
        except Exception as e:
            logger.error("vector_search_failed", error=str(e))
            return QueryResult(query="", chunks=[], error=str(e))
    
    async def _hybrid_search(
        self,
        query: str,
        query_vectors: List[float],
        limit: int,
        source_ids: Optional[List[str]],
    ) -> QueryResult:
        """Hybrid search via data-vent."""
        try:
            payload = {
                "query": query,
                "query_vectors": query_vectors,
                "limit": limit,
            }
            if source_ids:
                payload["source_ids"] = source_ids
            
            response = await self._http_client.post(
                f"{self.data_vent_url}/api/v1/hybrid-search",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            
            return QueryResult(
                query=query,
                chunks=data.get("chunks", []),
                vector_matches=data.get("vector_matches", 0),
                graph_matches=data.get("graph_matches", 0),
                completion_reached=data.get("completion_reached", False),
            )
        except Exception as e:
            logger.error("hybrid_search_failed", error=str(e))
            return QueryResult(query=query, chunks=[], error=str(e))
    
    def format_mcp_response(self, result: QueryResult) -> Dict[str, Any]:
        """Format query results as MCP tool response."""
        if result.error:
            return {
                "type": "error",
                "error": result.error,
            }
        
        # Format chunks for MCP consumption
        context_items = []
        for chunk in result.chunks:
            context_items.append({
                "uri": f"confuse://chunk/{chunk.get('chunk_id', '')}",
                "text": chunk.get("content", ""),
                "metadata": {
                    "score": chunk.get("score", 0),
                    "chunk_type": chunk.get("chunk_type", ""),
                    "source_id": chunk.get("source_id", ""),
                },
            })
        
        return {
            "type": "success",
            "content": context_items,
            "metadata": {
                "query": result.query,
                "total_results": len(result.chunks),
                "vector_matches": result.vector_matches,
                "graph_matches": result.graph_matches,
                "completion_reached": result.completion_reached,
                "time_ms": result.total_time_ms,
            },
        }
