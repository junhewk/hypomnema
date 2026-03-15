"""LLM entity extraction from document text."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import re
from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from hypomnema.llm.base import LLMClient

from hypomnema.ontology.normalizer import normalize
from hypomnema.tidy import DEFAULT_TIDY_LEVEL, TidyLevel, get_tidy_level_spec


class ExtractionError(ValueError):
    """Raised when entity extraction fails due to malformed LLM output."""


@dataclasses.dataclass(frozen=True)
class ExtractedEntity:
    name: str
    description: str


@dataclasses.dataclass(frozen=True)
class ExtractionResult:
    entities: list[ExtractedEntity]
    tidy_title: str | None = None
    tidy_text: str | None = None


@dataclasses.dataclass
class ExtractionTrace:
    prompt_variant: str = ""
    tidy_level: TidyLevel = DEFAULT_TIDY_LEVEL
    strategy: Literal["single", "map_reduce"] | None = None
    chunk_count: int = 0


@dataclasses.dataclass(frozen=True)
class ExtractorPromptVariant:
    name: str
    extraction_system: str
    map_system: str
    merge_system: str
    reduce_system: str


_CHUNK_THRESHOLD = 8000
_MAX_EVIDENCE_LINES_PER_CHUNK = 12
_FINAL_RENDER_EVIDENCE_CHARS = 6000
_MERGE_GROUP_SIZE = 4
_MARKDOWN_PREFIX_RE = re.compile(r"^(?:#{1,6}\s+|[-*+]\s+)")
_ENTITY_TOKEN_RE = re.compile(r"[A-Za-z0-9]+|[가-힣]+")
_ENTITY_FINGERPRINT_NOISE = {
    "a", "an", "and", "for", "of", "or", "the", "vs",
    "구분", "문제", "필요",
}

_BASE_EXTRACTION_PREFIX = (
    "You are an ontology extraction engine. Given a text, extract the key conceptual "
    "entities: theories, methodologies, phenomena, named concepts, significant people, "
    "and core ideas. For each entity, provide a canonical name and a one-sentence description.\n\n"
)

_LEGACY_EXTRACTION_SYSTEM = (
    _BASE_EXTRACTION_PREFIX
    +
    "Additionally, produce a tidy version of the input text:\n"
    "- tidy_title: a concise, descriptive title derived from the text content\n"
    "- tidy_text: the same content rendered according to the tidy level instructions.\n\n"
    "Common tidy requirements:\n"
    "1. Do NOT add content not present in the original.\n"
    "2. Do NOT fabricate information.\n"
    "3. Preserve the original language.\n"
    "4. If the input is already well-structured markdown, preserve it unless the tidy level "
    "explicitly allows heavier revision.\n\n"
    "Return ONLY valid JSON in this exact format:\n"
    '{"entities": [{"name": "...", "description": "..."}], '
    '"tidy_title": "...", "tidy_text": "..."}\n'
    "If no meaningful entities can be extracted, return an empty entities list. "
    "Always provide tidy_title and tidy_text."
)

_GROUNDED_EXTRACTION_SYSTEM = (
    _BASE_EXTRACTION_PREFIX
    +
    "Additionally, produce a tidy version of the input text:\n"
    "- tidy_title: a concise, descriptive title using only wording already present in the text. "
    "The title must stay in the dominant source language and script. Never translate, romanize, "
    "or anglicize names. If the text already has a clear title or subject line, preserve it with "
    "light cleanup.\n"
    "- tidy_text: a markdown rendering of the same content that follows the requested tidy level.\n\n"
    "Common rules for tidy_text:\n"
    "1. Preserve the dominant language and script of the input. Never translate. "
    "If the source mixes languages, preserve that mix.\n"
    "2. Preserve quoted text, URLs, markdown links, inline code, HTML tags and attributes, "
    "numbers, dates, acronyms, speaker names, ordered-list numbers, and specialized terms "
    "exactly as written unless a typo is obvious.\n"
    "2a. Also preserve compact note tokens and mixed-language shorthand exactly, including markers "
    "such as V, N, from F, ARPA-H, and parenthetical prompts.\n"
    "3. Match the amount of cleanup and restructuring to the requested tidy level. "
    "Keep rough notes rough unless the tidy level explicitly allows stronger revision.\n"
    "4. Do not invent metadata, addressees, dates, headings, transitions, interpretations, or "
    "conclusions that are not explicitly present in the text.\n"
    "5. Use markdown structure appropriate to the requested tidy level. If the input already uses "
    "markdown, HTML, README, or docs-like structure, edit it in place unless the tidy level "
    "explicitly allows heavier restructuring.\n"
    "5a. If the input already uses markdown headings, preserve heading levels and list-marker style "
    "exactly unless a tidy level explicitly allows a directly grounded reorganization.\n"
    "6. Preserve source casing for technical terms and note fragments unless the source clearly contains a typo. "
    "Do not sentence-case lower-case note lines just to make them look polished.\n"
    "7. When in doubt, copy the source phrasing instead of rewriting.\n\n"
    "8. Do not collapse structured docs, READMEs, or reference material into generic summary bullets "
    "or memo prose.\n\n"
    "Return ONLY valid JSON in this exact format:\n"
    '{"entities": [{"name": "...", "description": "..."}], '
    '"tidy_title": "...", "tidy_text": "..."}\n'
    "If no meaningful entities can be extracted, return an empty entities list. "
    "Always provide tidy_title and tidy_text."
)

_BASE_MAP_PREFIX = (
    "You are an ontology extraction engine processing one chunk of a larger document. "
    "Extract the key conceptual entities: theories, methodologies, phenomena, named concepts, "
    "significant people, and core ideas. For each entity, provide a canonical name and a "
    "one-sentence description.\n\n"
)

_LEGACY_MAP_SYSTEM = (
    _BASE_MAP_PREFIX
    +
    "Also provide concise evidence lines copied from this chunk for later reconstruction. "
    "Preserve the original language — do not translate or fabricate content.\n\n"
    "Return ONLY valid JSON in this exact format:\n"
    '{"entities": [{"name": "...", "description": "..."}], '
    '"evidence_lines": ["..."], "chunk_summary": "..."}'
)

_GROUNDED_MAP_SYSTEM = (
    _BASE_MAP_PREFIX
    +
    "Also provide source-grounded evidence lines for later reconstruction. Each evidence line must "
    "stay in the original language, preserve mixed-language spans, keep key terms verbatim, and "
    "avoid generic conclusions or memo framing. Prefer bullet-ready note fragments over abstract "
    "prose. Copy exact wording whenever possible instead of paraphrasing. Never guess at spelling "
    "or normalization: if a token is uncertain, copy it exactly from the chunk. Preserve URLs, "
    "markdown links, inline code, HTML tags and attributes, ordered-list numbers, and quoted spans "
    "exactly. Do not introduce an English lead sentence unless the chunk itself starts that way.\n\n"
    "Return ONLY valid JSON in this exact format:\n"
    '{"entities": [{"name": "...", "description": "..."}], '
    '"evidence_lines": ["..."], "chunk_summary": "..."}'
)

_BASE_REDUCE_PREFIX = (
    "You are an ontology extraction engine. You are given entity lists and summaries from "
    "chunks of a single document.\n\n"
)

_LEGACY_REDUCE_SYSTEM = (
    "You are given a grounded JSON artifact for a single document. The artifact contains "
    "evidence_lines copied from the source document.\n\n"
    +
    "Generate tidy_title and tidy_text from the evidence_lines.\n"
    "Do NOT add content not present in the evidence_lines. "
    "Do NOT fabricate. Preserve original language. Follow the requested tidy level.\n\n"
    "Return ONLY valid JSON in this exact format:\n"
    '{"tidy_title": "...", "tidy_text": "..."}'
)

_GROUNDED_REDUCE_SYSTEM = (
    "You are given a grounded JSON artifact for a single document. The artifact contains "
    "evidence_lines copied from the source document.\n\n"
    +
    "Generate tidy_title using only source wording already present in the evidence_lines.\n"
    "Generate tidy_text by stitching the evidence_lines into a markdown rendering of the original "
    "document that follows the requested tidy level.\n\n"
    "Common rules for tidy_text:\n"
    "- Preserve the original language and mixed-language spans. Do not introduce a new language "
    "for the title or body.\n"
    "- Preserve note structure, speaker labels, lists, code fences, markdown links, HTML blocks, "
    "and fragments when present\n"
    "- Preserve URLs, quoted spans, inline code, numbers, ordered-list numbering, acronyms, and "
    "specialized terms exactly\n"
    "- Preserve compact shorthand, mixed-language note tokens, and parenthetical prompts exactly, including tokens such as V, N, and from F\n"
    "- If the evidence_lines already reflect markdown, HTML, README, or docs-like structure, edit "
    "in place rather than converting them into summary bullets\n"
    "- Preserve markdown heading levels and list-marker style exactly when they already appear in the evidence_lines\n"
    "- Do not introduce memo framing, abstract conclusions, or section headers unless they already "
    "exist in the evidence_lines\n"
    "- Use markdown appropriate to the requested tidy level\n"
    "- Keep the wording close to the evidence_lines unless the tidy level explicitly allows heavier revision\n"
    "- Do not start with a summary sentence or thesis statement unless the source already has one\n"
    "- Preserve source casing for note fragments and technical terms; do not sentence-case lower-case evidence lines unless the source itself supports it\n"
    "- Preserve quoted spans and specialized terms exactly\n"
    "- Never guess at spelling corrections; when uncertain, copy tokens exactly from the evidence_lines\n"
    "- For short fragmentary notes, avoid umbrella introductions and keep one grounded bullet per source idea unless the source clearly supports stronger restructuring\n"
    "- Do not collapse documentation or README material into generic summary bullets\n\n"
    "Return ONLY valid JSON in this exact format:\n"
    '{"tidy_title": "...", "tidy_text": "..."}'
)

_GROUNDED_V2_MAP_SYSTEM = (
    _BASE_MAP_PREFIX
    +
    "Also provide source-grounded evidence lines for later reconstruction.\n"
    "Requirements:\n"
    "1. Stay in the exact source language mix of the chunk. Never translate.\n"
    "2. Output 4-12 short evidence lines, not prose summary paragraphs. If the source is already "
    "markdown, HTML, README, or docs-like, preserve the original structural lines even if they are "
    "not bullet-ready.\n"
    "3. Reuse source wording whenever possible. For note-style inputs, prefer copying full source "
    "lines verbatim. Each evidence line must be copied from one source line or be a minimal "
    "whitespace-cleaned version of it. Do not guess at spelling or normalize uncertain tokens. "
    "Preserve markdown link syntax, inline code, HTML tags and attributes, URLs, and ordered-list "
    "numbers exactly.\n"
    "4. Preserve quoted text, dates, numbers, acronyms, speaker labels, technical terms, compact shorthand, "
    "and mixed-language note tokens exactly.\n"
    "5. Do not add lead-in sentences, conclusions, memo framing, or inferred structure. When the "
    "source is already structured documentation, prefer structural fidelity over compression.\n\n"
    "Return ONLY valid JSON in this exact format:\n"
    '{"entities": [{"name": "...", "description": "..."}], '
    '"evidence_lines": ["..."], "chunk_summary": "..."}'
)

_BASE_MERGE_PREFIX = (
    "You are merging grounded evidence from several chunks of the same document. "
    "The input JSON has an 'artifacts' list and each artifact contains evidence_lines copied from "
    "the source.\n\n"
)

_LEGACY_MERGE_SYSTEM = (
    _BASE_MERGE_PREFIX
    +
    "Deduplicate overlap and keep the best source lines in order. Do not invent new lines, "
    "headings, or conclusions.\n\n"
    "Return ONLY valid JSON in this exact format:\n"
    '{"evidence_lines": ["..."]}'
)

_GROUNDED_MERGE_SYSTEM = (
    _BASE_MERGE_PREFIX
    +
    "Tasks:\n"
    "1. Remove duplicate overlap between artifacts\n"
    "2. Keep only wording that is explicitly present in the input evidence_lines\n"
    "3. Preserve source order and language mix as much as possible\n"
    "4. If two lines are near-duplicates, keep one original input line rather than rewriting them\n"
    "5. Preserve URLs, markdown links, inline code, HTML tags and attributes, quoted spans, and "
    "ordered-list numbers exactly\n"
    "6. Do not add headers, conclusions, transitions, or summaries\n\n"
    "Return ONLY valid JSON in this exact format:\n"
    '{"evidence_lines": ["..."]}'
)

_GROUNDED_V2_MERGE_SYSTEM = (
    _BASE_MERGE_PREFIX
    +
    "Requirements:\n"
    "1. Output only evidence_lines that are directly supported by the input evidence_lines.\n"
    "2. Preserve the dominant source language and script. Never translate.\n"
    "3. Remove chunk-overlap duplicates while preserving source order.\n"
    "4. Keep quoted spans, URLs, markdown links, inline code, HTML tags and attributes, numbers, "
    "ordered-list numbering, acronyms, speaker labels, and specialized terms exactly.\n"
    "5. Keep compact shorthand, mixed-language note tokens, and parenthetical prompts exactly.\n"
    "6. If two lines say the same thing, keep one original line rather than paraphrasing.\n"
    "7. Do not create any new sentence, title, section header, or memo framing.\n"
    "8. Preserve structural documentation lines and existing markdown heading levels instead of collapsing them into simplified notes.\n\n"
    "Return ONLY valid JSON in this exact format:\n"
    '{"evidence_lines": ["..."]}'
)

_GROUNDED_V2_REDUCE_SYSTEM = (
    "You are given a grounded JSON artifact for a single document. The artifact contains "
    "evidence_lines copied from the source document.\n\n"
    "Your tasks:\n"
    "1. Generate tidy_title using only wording already present in the evidence_lines and in the "
    "dominant source language\n"
    "2. Generate tidy_text by arranging the evidence_lines into markdown that follows the requested tidy level\n\n"
    "Common requirements for tidy_text:\n"
    "1. Preserve the dominant source language and script. Never add a new English title or summary "
    "sentence to a Korean-dominant document.\n"
    "2. Keep the output aligned with source form unless the tidy level explicitly allows stronger "
    "reorganization. If the source already looks like markdown, HTML, README, or docs, edit in place first.\n"
    "3. Keep wording close to the evidence_lines unless the tidy level explicitly allows heavier revision.\n"
    "4. Preserve quoted spans, URLs, markdown links, inline code, HTML tags and attributes, numbers, "
    "ordered-list numbering, acronyms, speaker labels, and specialized terms exactly.\n"
    "5. Use markdown intensity appropriate to the requested tidy level.\n"
    "6. Never guess at spelling corrections or token normalization. If uncertain, copy exact source "
    "tokens from the evidence_lines.\n"
    "7. Preserve source casing for note fragments and technical terms. Do not sentence-case lower-case source lines just to make them look polished.\n"
    "8. Preserve compact shorthand, mixed-language note tokens, and parenthetical prompts exactly, including tokens such as V, N, and from F.\n"
    "9. Preserve markdown heading levels and existing speaker-section boundaries when they already appear in the evidence_lines.\n"
    "10. Do not add new section headers, conclusions, or framing language unless they already exist "
    "in the evidence_lines.\n"
    "11. For short fragmentary notes, avoid umbrella introductions or thesis sentences and keep the rewrite close to one grounded bullet per source idea.\n"
    "12. For transcripts, discussion notes, and bullet-heavy source text, keep bullets and speaker sections instead of converting them into explanatory paragraphs.\n"
    "13. Do not collapse documentation or README material into generic summary bullets or memo framing.\n\n"
    "Return ONLY valid JSON in this exact format:\n"
    '{"tidy_title": "...", "tidy_text": "..."}'
)

_TIDY_ONLY_SINGLE_SYSTEM = (
    "You are cleaning a single source document into tidy_title and tidy_text only.\n\n"
    "Generate tidy_title using only wording already present in the text and keep the dominant source "
    "language and script.\n"
    "Generate tidy_text from the same source text using the requested tidy level.\n\n"
    "Common rules:\n"
    "1. Never translate.\n"
    "2. Preserve quotes, URLs, markdown links, inline code, HTML tags and attributes, numbers, dates, "
    "acronyms, ordered-list numbers, names, and specialized terms.\n"
    "2a. Preserve compact shorthand, mixed-language note tokens, and parenthetical prompts exactly, including tokens such as V, N, and from F.\n"
    "3. If the source is already markdown, HTML, README, or docs-like, edit it in place instead of "
    "converting it into summary bullets or memo prose.\n"
    "3a. If the source already uses markdown headings or bullet markers, preserve heading levels and list-marker style exactly unless whitespace cleanup is the only change.\n"
    "4. Preserve source casing for note fragments and technical terms unless the source clearly contains a typo. "
    "Do not sentence-case lower-case note lines, capitalize fragment starts, or add finishing punctuation just to make them look polished.\n"
    "5. For short fragmentary notes, avoid umbrella introductions, thesis sentences, and explanatory padding. "
    "Keep the rewrite close to one grounded bullet per source idea unless the source clearly supports a fuller paragraph.\n"
    "6. For transcripts, discussion notes, and bullet-heavy source text, preserve bullets and speaker sections instead of converting them into multi-paragraph exposition.\n"
    "7. Always return a non-empty tidy_text. If a rewrite risks dropping an exact token, copy the original line verbatim.\n"
    "8. Do not invent metadata, conclusions, addressees, or unsupported context.\n"
    "9. Return ONLY valid JSON in this exact format:\n"
    '{"tidy_title": "...", "tidy_text": "..."}'
)

_TIDY_ONLY_MAP_SYSTEM = (
    "You are preparing source-grounded evidence lines for a later tidy-text rendering pass.\n"
    "Return 4-12 short evidence_lines copied from this chunk or minimally whitespace-cleaned.\n"
    "Preserve the exact source language mix, markdown links, inline code, HTML tags and attributes, "
    "URLs, quoted spans, numbers, ordered-list numbers, acronyms, speaker labels, and specialized "
    "terms. If the source is already structured markdown or HTML, prefer full structural lines over "
    "compressed notes. Do not add conclusions, memo framing, or inferred structure.\n\n"
    "Return ONLY valid JSON in this exact format:\n"
    '{"evidence_lines": ["..."], "chunk_summary": "..."}'
)

_PROMPT_VARIANTS = {
    "legacy-baseline": ExtractorPromptVariant(
        name="legacy-baseline",
        extraction_system=_LEGACY_EXTRACTION_SYSTEM,
        map_system=_LEGACY_MAP_SYSTEM,
        merge_system=_LEGACY_MERGE_SYSTEM,
        reduce_system=_LEGACY_REDUCE_SYSTEM,
    ),
    "grounded-v1": ExtractorPromptVariant(
        name="grounded-v1",
        extraction_system=_GROUNDED_EXTRACTION_SYSTEM,
        map_system=_GROUNDED_MAP_SYSTEM,
        merge_system=_GROUNDED_MERGE_SYSTEM,
        reduce_system=_GROUNDED_REDUCE_SYSTEM,
    ),
    "grounded-v2": ExtractorPromptVariant(
        name="grounded-v2",
        extraction_system=_GROUNDED_EXTRACTION_SYSTEM,
        map_system=_GROUNDED_V2_MAP_SYSTEM,
        merge_system=_GROUNDED_V2_MERGE_SYSTEM,
        reduce_system=_GROUNDED_V2_REDUCE_SYSTEM,
    ),
}

DEFAULT_PROMPT_VARIANT = "grounded-v2"


def list_prompt_variants() -> tuple[str, ...]:
    """Return the available extractor prompt variants."""
    return tuple(_PROMPT_VARIANTS)


def get_prompt_variant(name: str = DEFAULT_PROMPT_VARIANT) -> ExtractorPromptVariant:
    """Fetch a prompt variant by name."""
    try:
        return _PROMPT_VARIANTS[name]
    except KeyError as exc:
        available = ", ".join(_PROMPT_VARIANTS)
        raise ValueError(f"Unknown prompt variant {name!r}. Available: {available}") from exc


def _with_tidy_level(system: str, tidy_level: TidyLevel) -> str:
    """Append tidy-level-specific instructions to a base prompt."""
    return f"{system.rstrip()}\n\n{get_tidy_level_spec(tidy_level).prompt_directive}"


def _split_chunks(text: str, chunk_size: int = 4000, overlap: int = 200) -> list[str]:
    """Split text into chunks on paragraph boundaries with overlap."""
    if len(text) <= chunk_size:
        return [text]

    paragraphs = text.split("\n\n")
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for para in paragraphs:
        para_len = len(para) + 2  # account for \n\n separator
        if current_len + para_len > chunk_size and current:
            chunks.append("\n\n".join(current))
            # Keep last paragraph(s) for overlap
            overlap_parts: list[str] = []
            overlap_len = 0
            for p in reversed(current):
                if overlap_len + len(p) > overlap:
                    break
                overlap_parts.insert(0, p)
                overlap_len += len(p)
            current = overlap_parts
            current_len = overlap_len
        current.append(para)
        current_len += para_len

    if current:
        chunks.append("\n\n".join(current))

    return chunks


@dataclasses.dataclass(frozen=True)
class _ChunkResult:
    entities: list[ExtractedEntity]
    evidence_lines: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class _TidyChunkResult:
    evidence_lines: tuple[str, ...]


async def _extract_chunk(
    llm: LLMClient,
    chunk: str,
    variant: ExtractorPromptVariant,
) -> _ChunkResult:
    """Extract entities and summary from a single chunk."""
    try:
        result = await llm.complete_json(chunk, system=variant.map_system)
    except ValueError as exc:
        raise ExtractionError(f"LLM returned malformed output for chunk: {exc}") from exc

    raw_entities = result.get("entities", [])
    if not isinstance(raw_entities, list):
        raw_entities = []

    entities: list[ExtractedEntity] = []
    for item in raw_entities:
        if not isinstance(item, dict):
            continue
        name = item.get("name", "").strip()
        description = item.get("description", "").strip()
        if name:
            entities.append(ExtractedEntity(name=name, description=description))

    evidence_lines = _extract_evidence_lines(result)

    return _ChunkResult(entities=entities, evidence_lines=evidence_lines)


async def _extract_tidy_chunk(
    llm: LLMClient,
    chunk: str,
) -> _TidyChunkResult:
    """Extract evidence lines for tidy-only rendering."""
    try:
        result = await llm.complete_json(chunk, system=_TIDY_ONLY_MAP_SYSTEM)
    except ValueError as exc:
        raise ExtractionError(f"LLM returned malformed tidy chunk output: {exc}") from exc
    return _TidyChunkResult(evidence_lines=_extract_evidence_lines(result))


def _extract_evidence_lines(
    data: dict[str, Any],
    *,
    limit: int | None = _MAX_EVIDENCE_LINES_PER_CHUNK,
) -> tuple[str, ...]:
    """Parse evidence lines from a chunk or merge response."""
    raw_lines = data.get("evidence_lines", [])
    if isinstance(raw_lines, list):
        return _dedupe_evidence_lines(
            (item for item in raw_lines if isinstance(item, str)),
            limit=limit,
        )

    summary = data.get("chunk_summary", "")
    if isinstance(summary, str):
        return _summary_to_evidence_lines(summary, limit=limit)
    return ()


def _summary_to_evidence_lines(summary: str, *, limit: int | None = _MAX_EVIDENCE_LINES_PER_CHUNK) -> tuple[str, ...]:
    """Fallback path for older chunk prompts that only returned chunk_summary."""
    if not summary.strip():
        return ()
    return _dedupe_evidence_lines(summary.splitlines(), limit=limit)


def _dedupe_evidence_lines(lines: Any, *, limit: int | None = None) -> tuple[str, ...]:
    """Normalize whitespace and remove exact duplicates while preserving order."""
    deduped: list[str] = []
    seen: set[str] = set()
    for item in lines:
        if not isinstance(item, str):
            continue
        line = item.strip()
        if not line:
            continue
        key = _normalize_evidence_line(line)
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(line)
        if limit is not None and len(deduped) >= limit:
            break
    return tuple(deduped)


def _normalize_evidence_line(line: str) -> str:
    """Normalize a line for overlap detection without changing numbered content."""
    stripped = line.strip()
    stripped = _MARKDOWN_PREFIX_RE.sub("", stripped)
    stripped = re.sub(r"\s+", " ", stripped)
    return stripped


def _prefer_entity(current: ExtractedEntity, candidate: ExtractedEntity) -> ExtractedEntity:
    """Keep the richer description while preserving the earlier canonical spelling by default."""
    if len(candidate.description) > len(current.description):
        return ExtractedEntity(name=current.name, description=candidate.description)
    return current


def _dedupe_entities(
    entities: Iterable[ExtractedEntity],
    key_fn: Callable[[str], Any],
) -> list[ExtractedEntity]:
    """Generic entity dedup: group by key_fn(name), keep richer description."""
    merged: dict[Any, ExtractedEntity] = {}
    order: list[Any] = []
    for entity in entities:
        key = key_fn(entity.name)
        if not key:
            continue
        existing = merged.get(key)
        if existing is None:
            merged[key] = entity
            order.append(key)
        else:
            merged[key] = _prefer_entity(existing, entity)
    return [merged[k] for k in order]


def _casefold_key(name: str) -> str:
    return name.strip().casefold()


def _normalized_key(name: str) -> str:
    try:
        return normalize(name)
    except ValueError:
        return _casefold_key(name)


def _entity_fingerprint(name: str) -> tuple[str, ...]:
    """Coarse lexical signature inspired by the engram concept-hash fallback."""
    lowered = name.lower()
    lowered = lowered.replace(" vs ", " ")
    lowered = re.sub(r"\b(?:and|or|the|a|an|of|for)\b", " ", lowered)
    lowered = re.sub(r"\b및\b", " ", lowered)
    lowered = re.sub(r"([가-힣a-z0-9])(?:와|과)\s+", r"\1 ", lowered)
    lowered = re.sub("[/:()\"’\u201c\u201d\u2018\u2019-]+", " ", lowered)
    tokens = [
        token
        for token in _ENTITY_TOKEN_RE.findall(lowered)
        if token not in _ENTITY_FINGERPRINT_NOISE
    ]
    if not tokens:
        return ()
    return tuple(dict.fromkeys(tokens))


def _fingerprint_key(name: str) -> tuple[str, ...]:
    return _entity_fingerprint(name) or (_casefold_key(name),)


def _merge_entities(chunk_results: list[_ChunkResult]) -> list[ExtractedEntity]:
    """Apply an in-memory analogue of the engram dedup tiers for long-doc entities."""
    flat = [e for cr in chunk_results for e in cr.entities]
    exact = _dedupe_entities(flat, _casefold_key)
    normalized = _dedupe_entities(exact, _normalized_key)
    return _dedupe_entities(normalized, _fingerprint_key)


def _merge_evidence_from_chunks(chunk_results: list[_ChunkResult]) -> tuple[str, ...]:
    """Deterministically merge evidence lines from all chunks, removing overlap duplicates."""
    return _dedupe_evidence_lines(
        line
        for chunk_result in chunk_results
        for line in chunk_result.evidence_lines
    )


def _serialized_evidence_size(evidence_lines: tuple[str, ...]) -> int:
    """Estimate the payload size for final tidy rendering."""
    return len(json.dumps({"evidence_lines": list(evidence_lines)}, ensure_ascii=False))


def _is_grounded_merge(
    merged_lines: tuple[str, ...],
    source_lines: tuple[str, ...],
) -> bool:
    """Check that merged evidence lines are copied from the input artifacts."""
    if not merged_lines:
        return False
    source_keys = {_normalize_evidence_line(line) for line in source_lines}
    return all(_normalize_evidence_line(line) in source_keys for line in merged_lines)


async def _merge_evidence_group(
    llm: LLMClient,
    group: list[tuple[str, ...]],
    variant: ExtractorPromptVariant,
) -> tuple[str, ...]:
    """Merge a small group of evidence artifacts with a grounded-model pass."""
    merged_input = {
        "artifacts": [
            {"evidence_lines": list(lines)}
            for lines in group
        ]
    }
    source_lines = tuple(line for lines in group for line in lines)
    try:
        result = await llm.complete_json(
            json.dumps(merged_input, ensure_ascii=False),
            system=variant.merge_system,
        )
    except ValueError:
        return _dedupe_evidence_lines(source_lines)

    merged_lines = _extract_evidence_lines(result, limit=None)
    if not _is_grounded_merge(merged_lines, source_lines):
        return _dedupe_evidence_lines(source_lines)
    return merged_lines


async def _compress_evidence_lines(
    llm: LLMClient,
    chunk_results: list[_ChunkResult],
    variant: ExtractorPromptVariant,
) -> tuple[str, ...]:
    """Use deterministic dedupe first, then hierarchical merge only when still too large."""
    merged = _merge_evidence_from_chunks(chunk_results)
    if _serialized_evidence_size(merged) <= _FINAL_RENDER_EVIDENCE_CHARS:
        return merged

    artifacts = [chunk_result.evidence_lines for chunk_result in chunk_results if chunk_result.evidence_lines]
    if not artifacts:
        return merged

    while len(artifacts) > 1:
        next_level: list[tuple[str, ...]] = []
        for index in range(0, len(artifacts), _MERGE_GROUP_SIZE):
            group = artifacts[index:index + _MERGE_GROUP_SIZE]
            next_level.append(await _merge_evidence_group(llm, group, variant))
        artifacts = next_level
        if len(artifacts) == 1 and _serialized_evidence_size(artifacts[0]) <= _FINAL_RENDER_EVIDENCE_CHARS:
            return artifacts[0]

    return artifacts[0] if artifacts else merged


async def _compress_tidy_evidence_lines(
    llm: LLMClient,
    chunk_results: list[_TidyChunkResult],
    variant: ExtractorPromptVariant,
) -> tuple[str, ...]:
    """Compress evidence lines for tidy-only rendering."""
    merged = _dedupe_evidence_lines(
        line
        for chunk_result in chunk_results
        for line in chunk_result.evidence_lines
    )
    if _serialized_evidence_size(merged) <= _FINAL_RENDER_EVIDENCE_CHARS:
        return merged

    artifacts = [chunk_result.evidence_lines for chunk_result in chunk_results if chunk_result.evidence_lines]
    if not artifacts:
        return merged

    while len(artifacts) > 1:
        next_level: list[tuple[str, ...]] = []
        for index in range(0, len(artifacts), _MERGE_GROUP_SIZE):
            group = artifacts[index:index + _MERGE_GROUP_SIZE]
            next_level.append(await _merge_evidence_group(llm, group, variant))
        artifacts = next_level
        if len(artifacts) == 1 and _serialized_evidence_size(artifacts[0]) <= _FINAL_RENDER_EVIDENCE_CHARS:
            return artifacts[0]

    return artifacts[0] if artifacts else merged


def _fallback_title(evidence_lines: tuple[str, ...]) -> str | None:
    """Derive a conservative title from the first grounded evidence line."""
    for line in evidence_lines:
        candidate = re.sub(r"^(?:#{1,6}\s+|[-*+]\s+|\d+\.\s+)", "", line).strip()
        if not candidate:
            continue
        if len(candidate) <= 120:
            return candidate
        return candidate[:117].rstrip() + "..."
    return None


def _fallback_tidy_text(evidence_lines: tuple[str, ...]) -> str | None:
    """Render evidence lines as minimal markdown when the final tidy pass fails."""
    if not evidence_lines:
        return None
    rendered_lines: list[str] = []
    for line in evidence_lines:
        if re.match(r"^(?:#{1,6}\s+|[-*+]\s+|\d+\.\s+|>\s+)", line):
            rendered_lines.append(line)
        else:
            rendered_lines.append(f"- {line}")
    return "\n".join(rendered_lines)


async def _render_long_document(
    llm: LLMClient,
    chunk_results: list[_ChunkResult],
    variant: ExtractorPromptVariant,
    tidy_level: TidyLevel,
) -> ExtractionResult:
    """Render the final tidy output from a grounded merged artifact."""
    entities = _merge_entities(chunk_results)
    evidence_lines = await _compress_evidence_lines(llm, chunk_results, variant)
    if not evidence_lines:
        return ExtractionResult(entities=entities)

    render_input = json.dumps({"evidence_lines": list(evidence_lines)}, ensure_ascii=False)
    try:
        result = await llm.complete_json(
            render_input,
            system=_with_tidy_level(variant.reduce_system, tidy_level),
        )
        tidy_title = _clean_optional_str(result.get("tidy_title")) or _fallback_title(evidence_lines)
        tidy_text = _clean_optional_str(result.get("tidy_text")) or _fallback_tidy_text(evidence_lines)
    except ValueError:
        tidy_title = _fallback_title(evidence_lines)
        tidy_text = _fallback_tidy_text(evidence_lines)

    return ExtractionResult(
        entities=entities,
        tidy_title=tidy_title,
        tidy_text=tidy_text,
    )


async def _render_tidy_from_evidence(
    llm: LLMClient,
    evidence_lines: tuple[str, ...],
    variant: ExtractorPromptVariant,
    tidy_level: TidyLevel,
) -> ExtractionResult:
    """Render tidy-only output from grounded evidence lines."""
    if not evidence_lines:
        return ExtractionResult(entities=[])

    render_input = json.dumps({"evidence_lines": list(evidence_lines)}, ensure_ascii=False)
    try:
        result = await llm.complete_json(
            render_input,
            system=_with_tidy_level(variant.reduce_system, tidy_level),
        )
        tidy_title = _clean_optional_str(result.get("tidy_title")) or _fallback_title(evidence_lines)
        tidy_text = _clean_optional_str(result.get("tidy_text")) or _fallback_tidy_text(evidence_lines)
    except ValueError:
        tidy_title = _fallback_title(evidence_lines)
        tidy_text = _fallback_tidy_text(evidence_lines)

    return ExtractionResult(
        entities=[],
        tidy_title=tidy_title,
        tidy_text=tidy_text,
    )


async def extract_entities(
    llm: LLMClient,
    text: str,
    *,
    prompt_variant: str = DEFAULT_PROMPT_VARIANT,
    tidy_level: TidyLevel = DEFAULT_TIDY_LEVEL,
    trace: ExtractionTrace | None = None,
) -> ExtractionResult:
    """Extract conceptual entities and tidy memo from text using an LLM.

    Short documents (< 8000 chars) use a single LLM call.
    Long documents use a map-reduce pipeline: extract per chunk, then merge.

    Raises:
        ExtractionError: If LLM returns malformed/unparseable output.
    """
    stripped = text.strip()
    if not stripped:
        return ExtractionResult(entities=[])

    variant = get_prompt_variant(prompt_variant)
    if trace is not None:
        trace.prompt_variant = variant.name
        trace.tidy_level = tidy_level

    if len(stripped) < _CHUNK_THRESHOLD:
        if trace is not None:
            trace.strategy = "single"
            trace.chunk_count = 1
        return await _extract_single(llm, stripped, variant, tidy_level)

    # Long documents: map to grounded chunk artifacts, then render from the merged artifact.
    chunks = _split_chunks(stripped)
    if trace is not None:
        trace.strategy = "map_reduce"
        trace.chunk_count = len(chunks)
    chunk_results = list(await asyncio.gather(*(_extract_chunk(llm, c, variant) for c in chunks)))
    return await _render_long_document(llm, chunk_results, variant, tidy_level)


async def render_tidy_text(
    llm: LLMClient,
    text: str,
    *,
    prompt_variant: str = DEFAULT_PROMPT_VARIANT,
    tidy_level: TidyLevel = DEFAULT_TIDY_LEVEL,
    trace: ExtractionTrace | None = None,
) -> ExtractionResult:
    """Render tidy_title and tidy_text without running entity extraction."""
    stripped = text.strip()
    if not stripped:
        return ExtractionResult(entities=[])

    variant = get_prompt_variant(prompt_variant)
    if trace is not None:
        trace.prompt_variant = variant.name
        trace.tidy_level = tidy_level

    if len(stripped) < _CHUNK_THRESHOLD:
        if trace is not None:
            trace.strategy = "single"
            trace.chunk_count = 1
        return await _render_single_tidy(llm, stripped, tidy_level)

    chunks = _split_chunks(stripped)
    if trace is not None:
        trace.strategy = "map_reduce"
        trace.chunk_count = len(chunks)
    chunk_results = list(await asyncio.gather(*(_extract_tidy_chunk(llm, c) for c in chunks)))
    evidence_lines = await _compress_tidy_evidence_lines(llm, chunk_results, variant)
    return await _render_tidy_from_evidence(llm, evidence_lines, variant, tidy_level)


async def _extract_single(
    llm: LLMClient,
    text: str,
    variant: ExtractorPromptVariant,
    tidy_level: TidyLevel,
) -> ExtractionResult:
    """Extract from a short document with a single LLM call."""
    try:
        result = await llm.complete_json(
            text,
            system=_with_tidy_level(variant.extraction_system, tidy_level),
        )
    except ValueError as exc:
        raise ExtractionError(f"LLM returned malformed output: {exc}") from exc

    return _parse_extraction_result(result)


async def _render_single_tidy(
    llm: LLMClient,
    text: str,
    tidy_level: TidyLevel,
) -> ExtractionResult:
    """Render tidy output from a short document without entity extraction."""
    try:
        result = await llm.complete_json(
            text,
            system=_with_tidy_level(_TIDY_ONLY_SINGLE_SYSTEM, tidy_level),
        )
    except ValueError as exc:
        raise ExtractionError(f"LLM returned malformed tidy output: {exc}") from exc
    parsed = _parse_tidy_result(result)
    if parsed.tidy_text:
        return parsed

    source_lines = _summary_to_evidence_lines(text, limit=None) or tuple(line for line in text.splitlines() if line.strip())
    return ExtractionResult(
        entities=[],
        tidy_title=parsed.tidy_title or _fallback_title(source_lines),
        tidy_text=text.strip() or _fallback_tidy_text(source_lines),
    )


def _parse_extraction_result(data: dict[str, Any]) -> ExtractionResult:
    """Parse LLM JSON response into ExtractionResult."""
    raw_entities = data.get("entities", data.get("items", []))
    if not isinstance(raw_entities, list):
        raise ExtractionError("'entities' field is not a list")

    entities: list[ExtractedEntity] = []
    for item in raw_entities:
        if not isinstance(item, dict):
            continue
        name = item.get("name", "").strip()
        description = item.get("description", "").strip()
        if name:
            entities.append(ExtractedEntity(name=name, description=description))

    return ExtractionResult(
        entities=entities,
        tidy_title=_clean_optional_str(data.get("tidy_title")),
        tidy_text=_clean_optional_str(data.get("tidy_text")),
    )


def _parse_tidy_result(data: dict[str, Any]) -> ExtractionResult:
    """Parse a tidy-only LLM response into ExtractionResult."""
    return ExtractionResult(
        entities=[],
        tidy_title=_clean_optional_str(data.get("tidy_title")),
        tidy_text=_clean_optional_str(data.get("tidy_text")),
    )


def _clean_optional_str(value: Any) -> str | None:
    """Strip and normalize an optional string — empty/non-string becomes None."""
    if isinstance(value, str):
        return value.strip() or None
    return None
