"""Engram article synthesizer — compiles wiki-style articles from linked documents.

Inspired by Karpathy's LLM Knowledge Base approach: treat engrams as compiled
wiki articles synthesized from all source documents, not just one-sentence
descriptions from the first document that created the engram.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import aiosqlite

    from hypomnema.llm.base import LLMClient

from hypomnema.db.transactions import immediate_transaction

logger = logging.getLogger(__name__)

_DOC_BUDGET = 2000  # max chars per source document excerpt
_MAX_DOCS = 20  # max documents to include in synthesis prompt
_MIN_DOCS_FOR_ARTICLE = 2  # only synthesize engrams with 2+ linked docs

_SYSTEM_PROMPT = """\
You are a knowledge synthesis engine. Given source excerpts about a concept \
and its relationships in a knowledge graph, write a comprehensive wiki-style \
article in markdown. The article should:

- Start with a clear definition
- Cover key aspects and relationships mentioned across sources
- Note points of agreement or tension between sources
- Identify open questions or gaps in coverage
- Be factual — only state what the sources support
- Use concise, clear language suitable for a personal research wiki
- Do NOT add headings like "# Title" — the concept name is already shown
- Keep the article between 200-800 words depending on source richness
"""


async def synthesize_engram_article(
    db: aiosqlite.Connection,
    llm: LLMClient,
    engram_id: str,
) -> str | None:
    """Synthesize a wiki-style article for an engram from its linked documents.

    Returns the article text, or None if the engram has fewer than
    _MIN_DOCS_FOR_ARTICLE linked documents.
    """
    # Fetch engram info
    cursor = await db.execute(
        "SELECT canonical_name, description FROM engrams WHERE id = ?",
        (engram_id,),
    )
    row = await cursor.fetchone()
    await cursor.close()
    if row is None:
        logger.warning("synthesize_engram_article: engram %s not found", engram_id)
        return None

    canonical_name = row["canonical_name"]
    description = row["description"] or ""

    # Fetch linked documents
    cursor = await db.execute(
        "SELECT d.title, d.tidy_title, d.text, d.tidy_text, d.source_type "
        "FROM documents d "
        "JOIN document_engrams de ON de.document_id = d.id "
        "WHERE de.engram_id = ? "
        "ORDER BY d.created_at DESC LIMIT ?",
        (engram_id, _MAX_DOCS),
    )
    docs = [dict(r) for r in await cursor.fetchall()]
    await cursor.close()

    if len(docs) < _MIN_DOCS_FOR_ARTICLE:
        return None

    # Fetch edges for relational context
    cursor = await db.execute(
        "SELECT e.predicate, e.confidence, "
        "CASE WHEN e.source_engram_id = ? THEN t.canonical_name "
        "     ELSE s.canonical_name END AS related_name, "
        "CASE WHEN e.source_engram_id = ? THEN 'outgoing' ELSE 'incoming' END AS direction "
        "FROM edges e "
        "JOIN engrams s ON s.id = e.source_engram_id "
        "JOIN engrams t ON t.id = e.target_engram_id "
        "WHERE e.source_engram_id = ? OR e.target_engram_id = ? "
        "ORDER BY e.confidence DESC LIMIT 30",
        (engram_id, engram_id, engram_id, engram_id),
    )
    edges = [dict(r) for r in await cursor.fetchall()]
    await cursor.close()

    # Build prompt
    prompt = _build_prompt(canonical_name, description, docs, edges)

    # Call LLM
    article = await llm.complete(prompt, system=_SYSTEM_PROMPT)
    article = article.strip()

    if not article:
        logger.warning("synthesize_engram_article: empty LLM response for %s", engram_id)
        return None

    # Store
    now = datetime.now(UTC).replace(microsecond=0).isoformat()
    async with immediate_transaction(db):
        await db.execute(
            "UPDATE engrams SET article = ?, article_updated_at = ? WHERE id = ?",
            (article, now, engram_id),
        )

    logger.info("Synthesized article for '%s' (%d chars from %d docs)",
                canonical_name, len(article), len(docs))
    return article


def _build_prompt(
    name: str,
    description: str,
    docs: list[dict[str, object]],
    edges: list[dict[str, object]],
) -> str:
    """Build the LLM prompt for article synthesis."""
    parts = [f'Concept: "{name}"']
    if description:
        parts.append(f"Current description: {description}")

    # Source excerpts
    parts.append(f"\n## Source Documents ({len(docs)})\n")
    for i, doc in enumerate(docs, 1):
        title = doc.get("tidy_title") or doc.get("title") or "Untitled"
        text = str(doc.get("tidy_text") or doc.get("text") or "")
        text = text[:_DOC_BUDGET]
        src_type = doc.get("source_type", "unknown")
        parts.append(f"### Source {i}: {title} [{src_type}]\n{text}\n")

    # Relational context
    if edges:
        parts.append(f"\n## Knowledge Graph Relationships ({len(edges)})\n")
        for edge in edges:
            direction = edge["direction"]
            predicate = edge["predicate"]
            related = edge["related_name"]
            conf = edge.get("confidence", 0)
            if direction == "outgoing":
                arrow = f"{name} → {predicate} → {related}"
            else:
                arrow = f"{related} → {predicate} → {name}"
            parts.append(f"- {arrow} (confidence: {conf:.0%})")

    parts.append("\nWrite a comprehensive wiki article about this concept based on the sources above.")
    return "\n".join(parts)


async def synthesize_stale_articles(
    db: aiosqlite.Connection,
    llm: LLMClient,
    limit: int = 5,
) -> int:
    """Find engrams with stale or missing articles and regenerate them.

    Returns the number of articles synthesized.
    """
    cursor = await db.execute("""
        SELECT e.id, COUNT(de.document_id) AS doc_count
        FROM engrams e
        JOIN document_engrams de ON de.engram_id = e.id
        JOIN documents d ON d.id = de.document_id
        GROUP BY e.id
        HAVING doc_count >= ?
          AND (e.article IS NULL
               OR e.article_updated_at IS NULL
               OR e.article_updated_at < MAX(d.updated_at))
        ORDER BY doc_count DESC
        LIMIT ?
    """, (_MIN_DOCS_FOR_ARTICLE, limit))
    stale = [row["id"] for row in await cursor.fetchall()]
    await cursor.close()

    count = 0
    for engram_id in stale:
        try:
            result = await synthesize_engram_article(db, llm, engram_id)
            if result:
                count += 1
        except Exception:
            logger.exception("Failed to synthesize article for engram %s", engram_id)

    return count
