"""
Prompt Compressor — Query & Response Optimization

Sits between AI agents and data-vent. Two jobs:

1. compress_query()  — Take natural-language prompt from agent,
   strip filler words, extract search-relevant keywords and intent.
   Produces a clean, compact query string for data-vent.

2. compress_response() — Take verbose JSON from data-vent,
   convert to compact tabular text that minimizes context tokens
   consumed by the calling LLM.
"""

import re
import time
import structlog
from dataclasses import dataclass, field
from typing import Any

logger = structlog.get_logger()


# ── Filler words to strip from agent prompts ─────────────────────────────────
# Broader than data-vent's stop words: also covers conversational filler
# that agents inject (e.g., "Could you please find...").

FILLER_WORDS: set[str] = {
    # Conversational
    "please", "could", "would", "should", "can", "help", "me",
    "find", "show", "tell", "give", "get", "look", "let",
    "know", "need", "want", "like", "think", "try",
    # Articles & determiners
    "a", "an", "the", "this", "that", "these", "those",
    # Pronouns
    "i", "my", "we", "our", "you", "your", "it", "its",
    "he", "his", "she", "her", "they", "them", "their",
    # Prepositions
    "in", "on", "at", "to", "for", "of", "with", "by", "from",
    "into", "about", "between", "through", "during", "before",
    "after", "above", "below", "up", "down", "out", "off",
    "over", "under",
    # Conjunctions
    "and", "or", "but", "nor", "so", "yet", "both",
    # Aux verbs
    "is", "am", "are", "was", "were", "be", "been", "being",
    "has", "have", "had", "do", "does", "did", "will",
    # Query filler
    "what", "how", "where", "when", "why", "which", "who",
    "all", "any", "some", "each", "every", "no", "not",
    "just", "only", "also", "very", "really", "quite",
    "more", "most", "much", "many", "few", "less", "least",
    "then", "than", "too", "here", "there", "now",
    # Misc
    "information", "details", "data", "stuff", "things",
    "regarding", "related", "about", "concerning",
}


@dataclass
class CompressedQuery:
    """Result of query compression."""
    original: str
    compressed: str        # Clean keyword string for data-vent
    keywords: list[str]    # Individual extracted keywords
    compression_ms: float = 0.0


class PromptCompressor:
    """
    Compresses agent prompts into optimized retrieval queries
    and compresses data-vent responses into compact text.
    """

    def __init__(self, filler_words: set[str] | None = None):
        self.filler_words = filler_words or FILLER_WORDS

    # ── Query compression ────────────────────────────────────────────────

    def compress_query(self, raw_query: str) -> CompressedQuery:
        """
        Take a natural-language agent prompt and extract only
        the search-relevant keywords.

        Steps:
        1. Normalize whitespace, lowercase
        2. Preserve quoted phrases as-is
        3. Preserve technical identifiers (snake_case, dotted paths)
        4. Strip filler words from remaining text
        5. Deduplicate
        """
        start = time.perf_counter()

        if not raw_query or not raw_query.strip():
            return CompressedQuery(
                original=raw_query or "",
                compressed="",
                keywords=[],
            )

        text = raw_query.strip()

        # 1. Extract quoted phrases (keep intact)
        quoted: list[str] = []
        for match in re.finditer(r'"([^"]+)"', text):
            phrase = match.group(1).strip()
            if len(phrase) >= 2:
                quoted.append(phrase)
        # Remove quoted strings from remaining text
        remaining = re.sub(r'"[^"]*"', " ", text)

        # 2. Extract technical identifiers (module.class, snake_case_name)
        identifiers: list[str] = []
        for match in re.finditer(
            r"\b([a-zA-Z][a-zA-Z0-9]*(?:[._][a-zA-Z][a-zA-Z0-9]*)+)\b",
            remaining,
        ):
            identifiers.append(match.group(1))
        remaining = re.sub(
            r"\b[a-zA-Z][a-zA-Z0-9]*(?:[._][a-zA-Z][a-zA-Z0-9]*)+\b",
            " ",
            remaining,
        )

        # 3. Extract UPPER_CASE constants
        for match in re.finditer(r"\b([A-Z][A-Z0-9_]{2,})\b", remaining):
            identifiers.append(match.group(1))
        remaining = re.sub(r"\b[A-Z][A-Z0-9_]{2,}\b", " ", remaining)

        # 4. Normalize and strip filler
        words = re.sub(r"[^\w\s]", " ", remaining.lower()).split()
        keywords = [
            w for w in words
            if w not in self.filler_words and len(w) >= 2
        ]

        # 5. Combine: identifiers first (highest value), then keywords
        all_keywords: list[str] = []
        seen: set[str] = set()
        for kw in identifiers + quoted + keywords:
            normalized = kw.lower()
            if normalized not in seen:
                seen.add(normalized)
                all_keywords.append(kw)

        compressed = " ".join(all_keywords)

        elapsed = (time.perf_counter() - start) * 1000

        logger.info(
            "prompt_compressed",
            original_len=len(raw_query),
            compressed_len=len(compressed),
            keywords_count=len(all_keywords),
            compression_ms=round(elapsed, 2),
        )

        return CompressedQuery(
            original=raw_query,
            compressed=compressed,
            keywords=all_keywords,
            compression_ms=round(elapsed, 2),
        )

    # ── Response compression ─────────────────────────────────────────────

    def compress_response(self, data: dict[str, Any]) -> str:
        """
        Convert data-vent RetrieveResponse JSON into compact tabular text.
        Strips verbose keys, keeps only content the LLM needs.
        """
        lines: list[str] = []

        results = data.get("results", data.get("chunks", []))
        total = data.get("total_results", data.get("total", len(results)))
        error = data.get("error")

        # Header
        lines.append(f"[RESULTS] {total} found")

        if error:
            lines.append(f"[ERROR] {error}")

        if not results:
            if not error:
                lines.append("No results.")
            return "\n".join(lines)

        # Timing (if available)
        total_ms = data.get("total_time_ms")
        if total_ms is not None:
            lines.append(f"[TIME] {total_ms:.0f}ms")

        lines.append("")

        for r in results:
            # Check if this result looks like a Graph node (has id and type/label)
            node_type = r.get("type", r.get("label", r.get("node_type")))
            node_id = r.get("id", r.get("node_id"))

            if node_type and node_id:
                # TOON Serialization for Graph Nodes
                props = r.get("properties", r.get("metadata", {}))
                
                # Extract score if available
                score = r.get("final_score", r.get("similarity_score", r.get("score")))
                if score is not None:
                    props["score"] = f"{score:.3f}" if isinstance(score, float) else str(score)

                # Format properties as concise key=value pairs
                props_str = ", ".join(
                    f"{k}={v}" for k, v in props.items() 
                    if k not in ["content", "text", "relationships", "edges"]
                )
                
                if props_str:
                    lines.append(f"Node | {node_type}:{node_id} | {props_str}")
                else:
                    lines.append(f"Node | {node_type}:{node_id}")

                # Format relationships (TOON style graph edges)
                rels = r.get("relationships", r.get("edges", []))
                for rel in rels:
                    rel_type = rel.get("type", rel.get("label", "RELATED_TO"))
                    target = rel.get("target", rel.get("target_id", "Unknown"))
                    lines.append(f"  -> {rel_type} -> {target}")

                # Handle raw content (like code snippets)
                content = r.get("content", r.get("text", ""))
                if content:
                    if len(content) > 2000:
                        content = content[:2000] + "\n...[TRUNCATED]"
                    lines.append(content.strip())
                
                lines.append("")
                continue

            # TOON-style standard chunk processing fallback
            score = r.get("final_score", r.get("similarity_score", r.get("score", 0.0)))
            score_str = f"{score:.3f}" if isinstance(score, float) else str(score)
            source = r.get("source_id", r.get("source", r.get("document_id", "-")))
            
            lines.append(f"Chunk | {source} | score={score_str}")
            
            content = r.get("content", r.get("text", ""))
            if len(content) > 2000:
                content = content[:2000] + "\n...[TRUNCATED]"
            
            lines.append(content.strip())
            lines.append("")

        return "\n".join(lines)

    def compress_batch_response(self, queries: list[dict], batch_data: dict[str, Any]) -> str:
        """
        Convert data-vent RetrieveBatchResponse JSON into compact tabular text for multiple queries.
        """
        lines: list[str] = []
        
        total_time = batch_data.get("total_batch_time_ms")
        if total_time is not None:
            lines.append(f"[BATCH TIME] {total_time:.0f}ms")
            lines.append("")

        responses = batch_data.get("responses", [])
        
        for idx, (query, resp) in enumerate(zip(queries, responses)):
            intent = query.get("intent", "Unknown Query")
            lines.append(f"=== RESULTS FOR: \"{intent}\" ===")
            
            # Use the existing compress_response logic for each individual response
            compressed = self.compress_response(resp)
            lines.append(compressed)
            lines.append("")
            
        return "\n".join(lines)
