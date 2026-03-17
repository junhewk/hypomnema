"""LLM entity extraction from document text."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import math
import random
import re
from collections.abc import Callable, Iterable
from inspect import isawaitable
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from hypomnema.llm.base import LLMClient

from hypomnema.ontology.normalizer import normalize
from hypomnema.token_utils import estimate_text_tokens
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
    failed_chunk_count: int = 0
    retry_count: int = 0
    fallback_used: bool = False
    source_profile: str = "default"
    pdf_debug: dict[str, Any] = dataclasses.field(default_factory=dict)


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
_PDF_NUMERIC_TOKEN_RE = re.compile(r"[0-9][0-9,./:-]*(?:%|st|nd|rd|th)?")
_PDF_ACRONYM_TOKEN_RE = re.compile(r"\b[A-Z][A-Z0-9/-]{1,}\b")
_PDF_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9“\"'(\[])")
_PDF_WORD_RE = re.compile(r"[A-Za-z]{3,}|[A-Z]{2,}|[가-힣]{2,}")
_CHUNK_END_MARKERS = ("\n\n", "\n", ". ", "? ", "! ", "; ", ": ", ", ", " ")
_CHUNK_BOUNDARY_WINDOW = 600
_CHUNK_START_WINDOW = 120
_LONG_DOC_MAX_CONCURRENCY = 6
_PDF_MAX_CONCURRENCY = 4
_LONG_DOC_MAP_TIMEOUT_SECONDS = 45.0
_PDF_MAP_TIMEOUT_SECONDS = 25.0
_LONG_DOC_REDUCE_TIMEOUT_SECONDS = 45.0
_PDF_REDUCE_TIMEOUT_SECONDS = 30.0
_LONG_DOC_MAX_RETRIES = 1
_PDF_MAX_RETRIES = 1
_RETRY_BASE_DELAY_SECONDS = 1.0
_PDF_CHUNK_SIZE = 12000
_PDF_CHUNK_OVERLAP = 300
_ENTITY_FINGERPRINT_NOISE = {
    "a", "an", "and", "for", "of", "or", "the", "vs",
    "구분", "문제", "필요",
}
_PDF_TOPIC_STOPWORDS = {
    "also", "among", "and", "are", "but", "can", "for", "from", "have", "into", "its",
    "more", "not", "our", "that", "the", "their", "there", "these", "this", "those",
    "through", "under", "with", "within", "would",
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
    "source is already structured documentation, prefer structural fidelity over compression.\n"
    "6. For PDF-derived text, preserve numbered section headings, figure/table captions, citation "
    "markers, DOI/reference lines, and equation or symbol-heavy lines when they appear in the chunk.\n\n"
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
    "13. Do not collapse documentation or README material into generic summary bullets or memo framing.\n"
    "14. For PDF-derived evidence, preserve source section order, numbered headings, figure/table captions, citation markers, DOI/reference lines, and equation or symbol-heavy tokens when present.\n"
    "15. Do not synthesize umbrella section headers that combine evidence from separate chunks unless the header wording already exists in the evidence_lines.\n\n"
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
    "compressed notes. For PDF-derived text, preserve numbered section headings, figure/table captions, "
    "citation markers, DOI/reference lines, and equation or symbol-heavy lines when they appear. "
    "Do not add conclusions, memo framing, or inferred structure.\n\n"
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


def _find_chunk_end(text: str, start: int, hard_end: int) -> int:
    """Prefer a natural boundary near the hard chunk limit without exceeding it."""
    if hard_end >= len(text):
        return len(text)

    window = min(_CHUNK_BOUNDARY_WINDOW, max(80, (hard_end - start) // 3))
    search_start = max(start + 1, hard_end - window)
    window_text = text[search_start:hard_end]
    for marker in _CHUNK_END_MARKERS:
        index = window_text.rfind(marker)
        if index == -1:
            continue
        boundary = search_start + index + len(marker.rstrip())
        if boundary > start:
            return boundary
    return hard_end


def _align_chunk_start(text: str, proposed_start: int) -> int:
    """Avoid starting a chunk inside a token when overlap lands mid-word."""
    start = max(0, proposed_start)
    if start >= len(text):
        return len(text)
    if start == 0:
        return 0

    if text[start - 1].isspace():
        while start < len(text) and text[start].isspace():
            start += 1
        return start

    search_end = min(len(text), start + _CHUNK_START_WINDOW)
    while start < search_end and not text[start].isspace():
        start += 1
    while start < len(text) and text[start].isspace():
        start += 1
    return start


def _split_chunks(text: str, chunk_size: int = 4000, overlap: int = 200) -> list[str]:
    """Split text into overlapping chunks, preferring natural boundaries when available."""
    if len(text) <= chunk_size:
        return [text]
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")

    overlap = max(0, min(overlap, chunk_size - 1))
    chunks: list[str] = []
    start = 0
    text_len = len(text)

    while start < text_len:
        hard_end = min(start + chunk_size, text_len)
        end = _find_chunk_end(text, start, hard_end)
        if end <= start:
            end = hard_end

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        if end >= text_len:
            break

        raw_next_start = max(end - overlap, start + 1)
        next_start = _align_chunk_start(text, raw_next_start)
        if next_start >= end:
            next_start = raw_next_start
        start = next_start

    return chunks


@dataclasses.dataclass(frozen=True)
class _ChunkResult:
    entities: list[ExtractedEntity]
    evidence_lines: tuple[str, ...]
    pdf_artifact: _PdfChunkArtifact | None = None


@dataclasses.dataclass(frozen=True)
class _TidyChunkResult:
    evidence_lines: tuple[str, ...]
    pdf_artifact: _PdfChunkArtifact | None = None


@dataclasses.dataclass(frozen=True)
class _LongDocumentProfile:
    name: Literal["default", "pdf"]
    chunk_size: int
    overlap: int
    max_concurrency: int
    map_timeout_seconds: float
    reduce_timeout_seconds: float
    max_retries: int
    retry_base_delay_seconds: float


@dataclasses.dataclass(frozen=True)
class _PdfTidyStrategy:
    render_mode: Literal["deterministic", "llm"]
    chunk_evidence_limit: int
    evidence_budget_tokens: int
    output_budget_tokens: int
    abstraction: Literal["extractive", "light", "polished"]
    heading_cap: int
    topic_cap: int
    quote_cap: int
    numeric_cap: int
    support_cap: int
    allow_polished_block: bool
    polished_block_token_cap: int
    max_heading_count: int
    min_topic_count: int
    min_quote_count: int
    min_numeric_count: int
    max_support_count: int


@dataclasses.dataclass(frozen=True)
class _PdfChunkArtifact:
    title_candidates: tuple[str, ...] = ()
    section_headings: tuple[str, ...] = ()
    topic_lines: tuple[str, ...] = ()
    quote_lines: tuple[str, ...] = ()
    numeric_lines: tuple[str, ...] = ()
    support_lines: tuple[str, ...] = ()
    polished_block: str | None = None


@dataclasses.dataclass(frozen=True)
class _PdfCandidate:
    text: str
    category: Literal["heading", "topic", "quote", "numeric", "support"]
    chunk_index: int
    section_index: int
    section_title: str | None
    order: int


@dataclasses.dataclass(frozen=True)
class _PdfChunkSelection:
    chunk_index: int
    section_index: int
    section_title: str | None
    headings: tuple[str, ...]
    topic_lines: tuple[str, ...]
    quote_lines: tuple[str, ...]
    numeric_lines: tuple[str, ...]
    support_lines: tuple[str, ...]
    polished_block: str | None
    polished_block_used: bool
    polished_block_rejected_reason: str | None


@dataclasses.dataclass(frozen=True)
class _PdfRenderPlan:
    title: str | None
    chunk_selections: tuple[_PdfChunkSelection, ...]
    selected_counts: dict[str, int]
    dropped_counts: dict[str, int]
    accepted_polished_blocks: int
    rejected_polished_blocks: int
    rejected_polished_reasons: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class _ChunkOutcome:
    index: int
    result: _ChunkResult | _TidyChunkResult | None
    retries: int
    error: str | None = None


ProgressCallback = Callable[[dict[str, Any]], Any]


_DEFAULT_LONG_DOCUMENT_PROFILE = _LongDocumentProfile(
    name="default",
    chunk_size=4000,
    overlap=200,
    max_concurrency=_LONG_DOC_MAX_CONCURRENCY,
    map_timeout_seconds=_LONG_DOC_MAP_TIMEOUT_SECONDS,
    reduce_timeout_seconds=_LONG_DOC_REDUCE_TIMEOUT_SECONDS,
    max_retries=_LONG_DOC_MAX_RETRIES,
    retry_base_delay_seconds=_RETRY_BASE_DELAY_SECONDS,
)

_PDF_LONG_DOCUMENT_PROFILE = _LongDocumentProfile(
    name="pdf",
    chunk_size=_PDF_CHUNK_SIZE,
    overlap=_PDF_CHUNK_OVERLAP,
    max_concurrency=_PDF_MAX_CONCURRENCY,
    map_timeout_seconds=_PDF_MAP_TIMEOUT_SECONDS,
    reduce_timeout_seconds=_PDF_REDUCE_TIMEOUT_SECONDS,
    max_retries=_PDF_MAX_RETRIES,
    retry_base_delay_seconds=_RETRY_BASE_DELAY_SECONDS,
)


def _resolve_long_document_profile(source_mime_type: str | None) -> _LongDocumentProfile:
    if source_mime_type == "application/pdf":
        return _PDF_LONG_DOCUMENT_PROFILE
    return _DEFAULT_LONG_DOCUMENT_PROFILE


def _resolve_pdf_tidy_strategy(tidy_level: TidyLevel) -> _PdfTidyStrategy:
    match tidy_level:
        case "format_only" | "light_cleanup":
            return _PdfTidyStrategy(
                render_mode="deterministic",
                chunk_evidence_limit=6,
                evidence_budget_tokens=700,
                output_budget_tokens=560,
                abstraction="extractive",
                heading_cap=1,
                topic_cap=2,
                quote_cap=1,
                numeric_cap=2,
                support_cap=0,
                allow_polished_block=False,
                polished_block_token_cap=0,
                max_heading_count=4,
                min_topic_count=4,
                min_quote_count=2,
                min_numeric_count=3,
                max_support_count=0,
            )
        case "structured_notes":
            return _PdfTidyStrategy(
                render_mode="deterministic",
                chunk_evidence_limit=8,
                evidence_budget_tokens=1300,
                output_budget_tokens=980,
                abstraction="light",
                heading_cap=1,
                topic_cap=2,
                quote_cap=2,
                numeric_cap=2,
                support_cap=1,
                allow_polished_block=True,
                polished_block_token_cap=120,
                max_heading_count=5,
                min_topic_count=5,
                min_quote_count=3,
                min_numeric_count=4,
                max_support_count=2,
            )
        case _:
            return _PdfTidyStrategy(
                render_mode="deterministic",
                chunk_evidence_limit=10,
                evidence_budget_tokens=2100,
                output_budget_tokens=1500,
                abstraction="polished",
                heading_cap=1,
                topic_cap=3,
                quote_cap=2,
                numeric_cap=3,
                support_cap=1,
                allow_polished_block=True,
                polished_block_token_cap=180,
                max_heading_count=6,
                min_topic_count=6,
                min_quote_count=4,
                min_numeric_count=5,
                max_support_count=3,
            )


def _with_pdf_chunk_budget(system: str, strategy: _PdfTidyStrategy, *, include_entities: bool) -> str:
    abstraction_instruction = {
        "extractive": (
            "Prefer exact copied source lines. Do not paraphrase if copying the line preserves the "
            "same content."
        ),
        "light": (
            "Allow only light local cleanup when needed, but keep wording very close to the source. "
            "When choosing between smoother prose and exact figures or labeled findings, keep the exact figures."
        ),
        "polished": (
            "You may merge adjacent lines into a short grounded note for readability, but preserve all "
            "numbers, citations, quotes, figure/table anchors, and specialized terms exactly. Prefer retaining "
            "exact metrics, enumerated values, and named alignments even if that makes the prose denser."
        ),
    }[strategy.abstraction]
    json_prefix = '{"entities": [{"name": "...", "description": "..."}], ' if include_entities else "{"
    polished_instruction = (
        f'- Also return "polished_block": a short grounded markdown block no longer than '
        f'{strategy.polished_block_token_cap} tokens. It must not add new headings or new numeric tokens.\n'
        if strategy.allow_polished_block else
        '- Return "polished_block" as an empty string.\n'
    )
    return (
        f"{system.rstrip()}\n\n"
        "PDF chunk extraction instructions:\n"
        "- Ignore the generic evidence_lines schema above for PDF-derived chunks.\n"
        "- Return ONLY valid JSON in this exact shape:\n"
        f'{json_prefix}"title_candidates": ["..."], "section_headings": ["..."], '
        '"topic_lines": ["..."], "quote_lines": ["..."], "numeric_lines": ["..."], '
        '"support_lines": ["..."], "polished_block": "..."}\n'
        "- title_candidates: at most 1 semantic title line from this chunk, never an affiliation or address line.\n"
        f"- section_headings: at most {strategy.heading_cap} numbered or explicit headings.\n"
        f"- topic_lines: at most {strategy.topic_cap} source-grounded substantive lines that carry the main claims or definitions.\n"
        f"- quote_lines: at most {strategy.quote_cap} quoted spans or lines with quoted wording.\n"
        f"- numeric_lines: at most {strategy.numeric_cap} lines with metrics, numbered findings, figure/table anchors, citation markers, DOI lines, or acronym-heavy factual claims.\n"
        f"- support_lines: at most {strategy.support_cap} additional source-grounded lines only if they materially improve coherence.\n"
        f"{polished_instruction}"
        "- Copy source wording whenever possible. Preserve quotes, numbers, acronyms, citations, figure/table anchors, and specialized terms exactly.\n"
        "- Do not invent section headers, transitions, or summary claims.\n"
        f"- {abstraction_instruction}"
    )


async def _emit_progress(
    progress_callback: ProgressCallback | None,
    payload: dict[str, Any],
) -> None:
    if progress_callback is None:
        return
    result = progress_callback(payload)
    if isawaitable(result):
        await result


async def _complete_json_with_timeout(
    llm: LLMClient,
    prompt: str,
    *,
    system: str = "",
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    timeout_ms = None if timeout_seconds is None else max(1, int(timeout_seconds * 1000))
    if timeout_ms is not None:
        try:
            return await llm.complete_json(prompt, system=system, timeout_ms=timeout_ms)  # type: ignore[call-arg]
        except TypeError as exc:
            if "timeout_ms" not in str(exc):
                raise
    return await llm.complete_json(prompt, system=system)


async def _call_with_retry(
    operation: Callable[[], Any],
    *,
    timeout_seconds: float,
    max_retries: int,
    retry_base_delay_seconds: float,
) -> tuple[Any, int]:
    retries = 0
    while True:
        try:
            return await asyncio.wait_for(operation(), timeout=timeout_seconds), retries
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if isinstance(exc, TimeoutError) or "timeout" in type(exc).__name__.casefold():
                raise
            if retries >= max_retries:
                raise
            retries += 1
            await asyncio.sleep((retry_base_delay_seconds * (2 ** (retries - 1))) + random.uniform(0.0, 0.25))


async def _run_chunk_with_retry(
    *,
    index: int,
    chunk: str,
    worker: Callable[[str], Any],
    profile: _LongDocumentProfile,
) -> _ChunkOutcome:
    try:
        result, retries = await _call_with_retry(
            lambda: worker(chunk),
            timeout_seconds=profile.map_timeout_seconds,
            max_retries=profile.max_retries,
            retry_base_delay_seconds=profile.retry_base_delay_seconds,
        )
    except Exception as exc:
        return _ChunkOutcome(
            index=index,
            result=None,
            retries=profile.max_retries,
            error=f"{type(exc).__name__}: {exc}",
        )
    return _ChunkOutcome(index=index, result=result, retries=retries)


async def _run_chunk_stage(
    *,
    chunks: list[str],
    worker: Callable[[str], Any],
    profile: _LongDocumentProfile,
    progress_callback: ProgressCallback | None,
    stage: Literal["map", "tidy_map"],
) -> tuple[list[_ChunkResult] | list[_TidyChunkResult], int, int]:
    total = len(chunks)
    await _emit_progress(
        progress_callback,
        {
            "status": "running",
            "stage": stage,
            "chunk_total": total,
            "chunk_completed": 0,
            "chunk_failed": 0,
            "retry_count": 0,
            "source_profile": profile.name,
        },
    )

    semaphore = asyncio.Semaphore(profile.max_concurrency)

    async def run_one(index: int, chunk: str) -> _ChunkOutcome:
        async with semaphore:
            return await _run_chunk_with_retry(
                index=index,
                chunk=chunk,
                worker=worker,
                profile=profile,
            )

    tasks = [asyncio.create_task(run_one(index, chunk)) for index, chunk in enumerate(chunks)]
    completed = 0
    failed = 0
    retries = 0
    outcomes: list[_ChunkOutcome] = []
    for task in asyncio.as_completed(tasks):
        outcome = await task
        completed += 1
        failed += int(outcome.result is None)
        retries += outcome.retries
        outcomes.append(outcome)
        await _emit_progress(
            progress_callback,
            {
                "status": "running",
                "stage": stage,
                "chunk_total": total,
                "chunk_completed": completed,
                "chunk_failed": failed,
                "retry_count": retries,
                "last_error": outcome.error,
                "source_profile": profile.name,
            },
        )

    ordered = [outcome.result for outcome in sorted(outcomes, key=lambda item: item.index) if outcome.result is not None]
    return ordered, failed, retries


def _fallback_evidence_from_text(text: str) -> tuple[str, ...]:
    source_lines = tuple(line.strip() for line in text.splitlines() if line.strip())
    if len(source_lines) >= 4:
        return _dedupe_evidence_lines(source_lines, limit=80)
    return _dedupe_evidence_lines(_split_chunks(text, chunk_size=1200, overlap=0), limit=80)


def _fallback_result_from_text(text: str) -> ExtractionResult:
    evidence_lines = _fallback_evidence_from_text(text)
    return ExtractionResult(
        entities=[],
        tidy_title=_fallback_title(evidence_lines),
        tidy_text=_fallback_tidy_text(evidence_lines) or text.strip(),
    )


def _ensure_pdf_artifact_coverage(
    artifact: _PdfChunkArtifact,
    *,
    chunk: str,
    strategy: _PdfTidyStrategy,
) -> _PdfChunkArtifact:
    """Fill in missing quote/numeric lines from the raw chunk text."""
    if artifact.quote_lines and artifact.numeric_lines:
        return artifact
    fallback = _fallback_pdf_artifact(
        _dedupe_evidence_lines(
            [*_flatten_pdf_artifact_lines(artifact), *_select_pdf_preservation_lines(chunk, limit=3)],
            limit=None,
        ),
        strategy=strategy,
    )
    return _PdfChunkArtifact(
        title_candidates=artifact.title_candidates or fallback.title_candidates,
        section_headings=artifact.section_headings or fallback.section_headings,
        topic_lines=artifact.topic_lines or fallback.topic_lines,
        quote_lines=artifact.quote_lines or fallback.quote_lines,
        numeric_lines=artifact.numeric_lines or fallback.numeric_lines,
        support_lines=artifact.support_lines or fallback.support_lines,
        polished_block=artifact.polished_block,
    )


async def _extract_chunk(
    llm: LLMClient,
    chunk: str,
    variant: ExtractorPromptVariant,
    *,
    system: str | None = None,
    timeout_seconds: float | None = None,
    pdf_strategy: _PdfTidyStrategy | None = None,
) -> _ChunkResult:
    """Extract entities and summary from a single chunk."""
    try:
        result = await _complete_json_with_timeout(
            llm,
            chunk,
            system=system or variant.map_system,
            timeout_seconds=timeout_seconds,
        )
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

    if pdf_strategy is not None:
        artifact = _ensure_pdf_artifact_coverage(
            _extract_pdf_chunk_artifact(result, strategy=pdf_strategy),
            chunk=chunk,
            strategy=pdf_strategy,
        )
        return _ChunkResult(entities=entities, evidence_lines=_flatten_pdf_artifact_lines(artifact), pdf_artifact=artifact)

    evidence_lines = _extract_evidence_lines(result, limit=None)
    return _ChunkResult(entities=entities, evidence_lines=evidence_lines)


async def _extract_tidy_chunk(
    llm: LLMClient,
    chunk: str,
    *,
    system: str = _TIDY_ONLY_MAP_SYSTEM,
    timeout_seconds: float | None = None,
    pdf_strategy: _PdfTidyStrategy | None = None,
) -> _TidyChunkResult:
    """Extract evidence lines for tidy-only rendering."""
    try:
        result = await _complete_json_with_timeout(
            llm,
            chunk,
            system=system,
            timeout_seconds=timeout_seconds,
        )
    except ValueError as exc:
        raise ExtractionError(f"LLM returned malformed tidy chunk output: {exc}") from exc
    if pdf_strategy is not None:
        artifact = _ensure_pdf_artifact_coverage(
            _extract_pdf_chunk_artifact(result, strategy=pdf_strategy),
            chunk=chunk,
            strategy=pdf_strategy,
        )
        return _TidyChunkResult(evidence_lines=_flatten_pdf_artifact_lines(artifact), pdf_artifact=artifact)

    evidence_lines = _extract_evidence_lines(result, limit=None)
    return _TidyChunkResult(evidence_lines=evidence_lines)


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


def _extract_pdf_line_list(
    data: dict[str, Any],
    key: str,
    *,
    limit: int,
) -> tuple[str, ...]:
    raw = data.get(key, [])
    if isinstance(raw, list):
        return _dedupe_evidence_lines((item for item in raw if isinstance(item, str)), limit=limit)
    return ()


def _is_pdf_topic_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if _is_pdf_heading_line(stripped) or _is_pdf_reference_or_caption_line(stripped):
        return False
    if _is_pdf_affiliation_line(stripped):
        return False
    if len(stripped) < 40 or len(stripped) > 260:
        return False
    words = _PDF_WORD_RE.findall(stripped)
    if len(words) < 4:
        return False
    if len(re.findall(r"\[[0-9,\s]+\]", stripped)) >= 2:
        return False
    letter_count = sum(char.isalpha() for char in stripped)
    alnum_count = sum(char.isalnum() for char in stripped)
    if alnum_count == 0:
        return False
    if (letter_count / alnum_count) < 0.6:
        return False
    return True


def _fallback_pdf_artifact(
    evidence_lines: tuple[str, ...],
    *,
    strategy: _PdfTidyStrategy,
) -> _PdfChunkArtifact:
    title_candidates: list[str] = []
    section_headings: list[str] = []
    topic_lines: list[str] = []
    quote_lines: list[str] = []
    numeric_lines: list[str] = []
    support_lines: list[str] = []

    for index, line in enumerate(evidence_lines):
        if (
            index < 2
            and not title_candidates
            and not _is_pdf_affiliation_line(line)
            and not _is_pdf_heading_line(line)
            and not _is_pdf_reference_or_caption_line(line)
            and len(line) <= 180
        ):
            title_candidates.append(line)
            continue
        if _is_pdf_heading_line(line):
            section_headings.append(line)
            continue
        if _contains_pdf_quote(line):
            quote_lines.append(line)
            continue
        if _is_pdf_reference_or_caption_line(line) or _count_pdf_protected_tokens(line) >= 2:
            numeric_lines.append(line)
            continue
        if _is_pdf_topic_line(line):
            topic_lines.append(line)
            continue
        support_lines.append(line)

    return _PdfChunkArtifact(
        title_candidates=_dedupe_evidence_lines(title_candidates, limit=1),
        section_headings=_dedupe_evidence_lines(section_headings, limit=strategy.heading_cap),
        topic_lines=_dedupe_evidence_lines(topic_lines, limit=strategy.topic_cap),
        quote_lines=_dedupe_evidence_lines(quote_lines, limit=strategy.quote_cap),
        numeric_lines=_dedupe_evidence_lines(numeric_lines, limit=strategy.numeric_cap),
        support_lines=_dedupe_evidence_lines(support_lines, limit=strategy.support_cap),
        polished_block=None,
    )


def _extract_pdf_chunk_artifact(
    data: dict[str, Any],
    *,
    strategy: _PdfTidyStrategy,
) -> _PdfChunkArtifact:
    artifact = _PdfChunkArtifact(
        title_candidates=_extract_pdf_line_list(data, "title_candidates", limit=1),
        section_headings=_extract_pdf_line_list(data, "section_headings", limit=strategy.heading_cap),
        topic_lines=_extract_pdf_line_list(data, "topic_lines", limit=strategy.topic_cap),
        quote_lines=_extract_pdf_line_list(data, "quote_lines", limit=strategy.quote_cap),
        numeric_lines=_extract_pdf_line_list(data, "numeric_lines", limit=strategy.numeric_cap),
        support_lines=_extract_pdf_line_list(data, "support_lines", limit=strategy.support_cap),
        polished_block=_clean_optional_str(data.get("polished_block")) if strategy.allow_polished_block else None,
    )
    if any((
        artifact.title_candidates,
        artifact.section_headings,
        artifact.topic_lines,
        artifact.quote_lines,
        artifact.numeric_lines,
        artifact.support_lines,
        artifact.polished_block,
    )):
        return artifact
    return _fallback_pdf_artifact(_extract_evidence_lines(data, limit=None), strategy=strategy)


def _flatten_pdf_artifact_lines(artifact: _PdfChunkArtifact) -> tuple[str, ...]:
    return _dedupe_evidence_lines(
        (
            *artifact.title_candidates,
            *artifact.section_headings,
            *artifact.topic_lines,
            *artifact.quote_lines,
            *artifact.numeric_lines,
            *artifact.support_lines,
        ),
        limit=None,
    )


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


def _serialized_evidence_token_count(evidence_lines: tuple[str, ...]) -> int:
    """Estimate the payload token count for final tidy rendering."""
    return estimate_text_tokens(json.dumps({"evidence_lines": list(evidence_lines)}, ensure_ascii=False))


def _is_markdown_structural_line(line: str) -> bool:
    return bool(re.match(r"^(?:#{1,6}\s+|[-*+]\s+|\d+[.)]\s+|>\s+)", line))


def _is_pdf_heading_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if stripped.startswith("#"):
        return True
    if re.match(r"^\d+(?:\.\d+)*(?:\s+|$)", stripped) and not re.match(r"^\d+[.)]\s+", stripped):
        return True
    return stripped.isupper() and len(stripped) <= 120 and len(stripped.split()) <= 12


def _is_pdf_reference_or_caption_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if re.match(r"^(?:figure|table)\s+\d+[.:]?\s+", stripped, re.IGNORECASE):
        return True
    if re.match(r"^\[\d+\]", stripped):
        return True
    if stripped.lower().startswith("doi:"):
        return True
    return False


def _is_pdf_affiliation_line(line: str) -> bool:
    lowered = line.strip().lower()
    if not lowered:
        return False
    affiliation_markers = (
        "university", "institute", "department", "school of", "hospital", "centre",
        "center", "faculty", "college", "st ", "road", "avenue", "street", "email",
    )
    if "@" in lowered:
        return True
    return any(marker in lowered for marker in affiliation_markers)


def _contains_pdf_quote(line: str) -> bool:
    return any(marker in line for marker in ('"', "“", "”", "'", "‘", "’"))


def _count_pdf_protected_tokens(line: str) -> int:
    return len(_PDF_NUMERIC_TOKEN_RE.findall(line)) + len(_PDF_ACRONYM_TOKEN_RE.findall(line))


def _is_pdf_preservation_block(line: str) -> bool:
    return _contains_pdf_quote(line) or _count_pdf_protected_tokens(line) >= 2


def _split_pdf_candidate_segments(text: str) -> tuple[str, ...]:
    segments: list[str] = []
    for paragraph in (part.strip() for part in re.split(r"\n{2,}", text) if part.strip()):
        if _is_pdf_heading_line(paragraph) or _is_pdf_reference_or_caption_line(paragraph):
            segments.append(paragraph)
            continue
        for sentence in _PDF_SENTENCE_SPLIT_RE.split(paragraph):
            cleaned = sentence.strip()
            if cleaned:
                segments.append(cleaned)
    return tuple(segments)


def _select_pdf_preservation_lines(text: str, *, limit: int) -> tuple[str, ...]:
    if limit <= 0:
        return ()
    quote_lines: list[str] = []
    numeric_lines: list[str] = []
    for segment in _split_pdf_candidate_segments(text):
        if len(segment) > 240:
            continue
        if _is_pdf_heading_line(segment) or _is_pdf_reference_or_caption_line(segment):
            continue
        if _contains_pdf_quote(segment):
            quote_lines.append(segment)
            continue
        if _count_pdf_protected_tokens(segment) >= 2:
            numeric_lines.append(segment)
    return _dedupe_evidence_lines([*quote_lines, *numeric_lines], limit=limit)


def _pdf_evidence_line_score(index: int, line: str) -> int:
    score = 0
    if index == 0:
        score += 25
    if _is_pdf_heading_line(line):
        score += 100
    if _is_pdf_reference_or_caption_line(line):
        score += 80
    if _contains_pdf_quote(line):
        score += 45
    protected_token_count = _count_pdf_protected_tokens(line)
    if protected_token_count:
        score += 35
        score += min(60, protected_token_count * 12)
    if re.search(r"\b[A-Z]{2,}\b", line):
        score += 15
    if 40 <= len(line) <= 180:
        score += 10
    return score


def _trim_pdf_evidence_lines(lines: tuple[str, ...], *, limit: int) -> tuple[str, ...]:
    if len(lines) <= limit:
        return lines
    selected_indexes: list[int] = []

    def add_best(predicate: Callable[[str], bool]) -> None:
        candidates = [
            index
            for index, line in enumerate(lines)
            if index not in selected_indexes and predicate(line)
        ]
        if not candidates:
            return
        best = min(
            candidates,
            key=lambda index: (-_pdf_evidence_line_score(index, lines[index]), index),
        )
        selected_indexes.append(best)

    add_best(_is_pdf_heading_line)
    add_best(_contains_pdf_quote)
    add_best(lambda line: _count_pdf_protected_tokens(line) >= 2)

    ranked_indexes = sorted(
        range(len(lines)),
        key=lambda index: (-_pdf_evidence_line_score(index, lines[index]), index),
    )
    for index in ranked_indexes:
        if index in selected_indexes:
            continue
        selected_indexes.append(index)
        if len(selected_indexes) >= limit:
            break

    selected = sorted(selected_indexes[:limit])
    return tuple(lines[index] for index in selected)


def _is_pdf_frontmatter_noise(line: str) -> bool:
    stripped = line.strip()
    lowered = stripped.lower()
    if not stripped:
        return True
    if _is_pdf_affiliation_line(stripped):
        return True
    if lowered.startswith(("copyright", "correspondence", "supplementary", "received ", "accepted ")):
        return True
    if lowered.startswith("doi:") and len(stripped.split()) <= 6:
        return True
    return False


def _pdf_anchor_tokens(line: str, *, limit: int = 2) -> tuple[str, ...]:
    seen: set[str] = set()
    anchors: list[str] = []
    for token in sorted(_PDF_WORD_RE.findall(line), key=lambda item: (-len(item), item.casefold())):
        normalized = token.casefold()
        if normalized in seen or normalized in _PDF_TOPIC_STOPWORDS:
            continue
        seen.add(normalized)
        anchors.append(token)
        if len(anchors) >= limit:
            break
    return tuple(anchors)


def _pdf_numeric_tokens(text: str) -> tuple[str, ...]:
    raw = [*_PDF_NUMERIC_TOKEN_RE.findall(text), *_PDF_ACRONYM_TOKEN_RE.findall(text)]
    return tuple(dict.fromkeys(tok.rstrip(".,;:") or tok for tok in raw))


def _choose_pdf_title(
    artifacts: tuple[_PdfChunkArtifact, ...],
    entities: Iterable[ExtractedEntity],
) -> str | None:
    candidates = _dedupe_evidence_lines(
        line
        for artifact in artifacts
        for line in artifact.title_candidates
        if not _is_pdf_frontmatter_noise(line)
    )
    if candidates:
        return _deterministic_pdf_title(candidates, entities)
    flat = tuple(
        line
        for artifact in artifacts
        for line in _flatten_pdf_artifact_lines(artifact)
        if not _is_pdf_frontmatter_noise(line)
    )
    return _deterministic_pdf_title(flat, entities)


def _build_pdf_candidates(
    artifacts: tuple[_PdfChunkArtifact, ...],
) -> tuple[_PdfCandidate, ...]:
    candidates: list[_PdfCandidate] = []
    section_index = 0
    current_section_title: str | None = None
    order = 0
    for chunk_index, artifact in enumerate(artifacts):
        heading_lines = tuple(
            line for line in artifact.section_headings
            if not _is_pdf_frontmatter_noise(line)
        )
        if heading_lines:
            current_section_title = heading_lines[0]
            section_index += 1
        chunk_section_index = section_index
        chunk_section_title = current_section_title
        for category, lines in (
            ("heading", heading_lines),
            ("topic", artifact.topic_lines),
            ("quote", artifact.quote_lines),
            ("numeric", artifact.numeric_lines),
            ("support", artifact.support_lines),
        ):
            for line in lines:
                if _is_pdf_frontmatter_noise(line):
                    continue
                candidates.append(
                    _PdfCandidate(
                        text=line,
                        category=category,
                        chunk_index=chunk_index,
                        section_index=chunk_section_index,
                        section_title=chunk_section_title,
                        order=order,
                    )
                )
                order += 1
    return tuple(candidates)


def _group_candidates_by_category(
    candidates: tuple[_PdfCandidate, ...],
    category: Literal["heading", "topic", "quote", "numeric", "support"],
) -> list[_PdfCandidate]:
    return [candidate for candidate in candidates if candidate.category == category]


def _select_minimum_by_section(
    candidates: list[_PdfCandidate],
    *,
    minimum: int,
    selected_orders: set[int],
    selected_keys: set[str],
    selected_lines: list[str],
    budget_tokens: int,
) -> list[_PdfCandidate]:
    selected: list[_PdfCandidate] = []
    grouped: dict[int, list[_PdfCandidate]] = {}
    for candidate in candidates:
        grouped.setdefault(candidate.section_index, []).append(candidate)
    section_indexes = sorted(grouped)
    cursor = {section_index: 0 for section_index in section_indexes}
    while len(selected) < minimum:
        advanced = False
        for section_index in section_indexes:
            group = grouped[section_index]
            while cursor[section_index] < len(group):
                candidate = group[cursor[section_index]]
                cursor[section_index] += 1
                if candidate.order in selected_orders:
                    continue
                key = _normalize_evidence_line(candidate.text)
                if key in selected_keys:
                    continue
                prospective = "\n\n".join([*selected_lines, candidate.text])
                if estimate_text_tokens(prospective) > budget_tokens:
                    continue
                selected.append(candidate)
                selected_orders.add(candidate.order)
                selected_keys.add(key)
                selected_lines.append(candidate.text)
                advanced = True
                break
            if len(selected) >= minimum:
                break
        if not advanced:
            break
    return selected


def _select_pdf_render_plan(
    artifacts: tuple[_PdfChunkArtifact, ...],
    *,
    strategy: _PdfTidyStrategy,
    entities: Iterable[ExtractedEntity],
) -> _PdfRenderPlan:
    title = _choose_pdf_title(artifacts, entities)
    candidates = _build_pdf_candidates(artifacts)
    selected_orders: set[int] = set()
    selected_keys: set[str] = set()
    selected_lines: list[str] = [title] if title else []
    selected_by_chunk: dict[int, list[_PdfCandidate]] = {}
    selected_counts = {"heading": 0, "topic": 0, "quote": 0, "numeric": 0, "support": 0}
    total_counts = {category: 0 for category in selected_counts}
    for candidate in candidates:
        total_counts[candidate.category] += 1

    def record(candidate: _PdfCandidate) -> None:
        selected_by_chunk.setdefault(candidate.chunk_index, []).append(candidate)
        selected_counts[candidate.category] += 1

    def try_add(candidate: _PdfCandidate) -> bool:
        if candidate.order in selected_orders:
            return False
        key = _normalize_evidence_line(candidate.text)
        if key in selected_keys:
            return False
        prospective = "\n\n".join([*selected_lines, candidate.text])
        if estimate_text_tokens(prospective) > strategy.evidence_budget_tokens:
            return False
        selected_orders.add(candidate.order)
        selected_keys.add(key)
        selected_lines.append(candidate.text)
        record(candidate)
        return True

    for heading in _group_candidates_by_category(candidates, "heading"):
        if selected_counts["heading"] >= strategy.max_heading_count:
            break
        try_add(heading)

    for candidate in _select_minimum_by_section(
        _group_candidates_by_category(candidates, "topic"),
        minimum=strategy.min_topic_count,
        selected_orders=selected_orders,
        selected_keys=selected_keys,
        selected_lines=selected_lines,
        budget_tokens=strategy.evidence_budget_tokens,
    ):
        record(candidate)

    for candidate in _select_minimum_by_section(
        _group_candidates_by_category(candidates, "quote"),
        minimum=strategy.min_quote_count,
        selected_orders=selected_orders,
        selected_keys=selected_keys,
        selected_lines=selected_lines,
        budget_tokens=strategy.evidence_budget_tokens,
    ):
        record(candidate)

    for candidate in _select_minimum_by_section(
        _group_candidates_by_category(candidates, "numeric"),
        minimum=strategy.min_numeric_count,
        selected_orders=selected_orders,
        selected_keys=selected_keys,
        selected_lines=selected_lines,
        budget_tokens=strategy.evidence_budget_tokens,
    ):
        record(candidate)

    for category, limit in (
        ("topic", None),
        ("quote", None),
        ("numeric", None),
        ("support", strategy.max_support_count),
    ):
        for candidate in _group_candidates_by_category(candidates, category):
            if limit is not None and selected_counts[category] >= limit:
                break
            try_add(candidate)

    chunk_selections: list[_PdfChunkSelection] = []
    rejected_reasons: list[str] = []
    accepted_polished_blocks = 0
    rejected_polished_blocks = 0

    for chunk_index, artifact in enumerate(artifacts):
        chunk_candidates = sorted(selected_by_chunk.get(chunk_index, []), key=lambda item: item.order)
        if not chunk_candidates and not artifact.polished_block:
            continue
        headings = tuple(candidate.text for candidate in chunk_candidates if candidate.category == "heading")
        topic_lines = tuple(candidate.text for candidate in chunk_candidates if candidate.category == "topic")
        quote_lines = tuple(candidate.text for candidate in chunk_candidates if candidate.category == "quote")
        numeric_lines = tuple(candidate.text for candidate in chunk_candidates if candidate.category == "numeric")
        support_lines = tuple(candidate.text for candidate in chunk_candidates if candidate.category == "support")
        section_index = chunk_candidates[0].section_index if chunk_candidates else 0
        section_title = chunk_candidates[0].section_title if chunk_candidates else None
        polished_block_used = False
        polished_block_rejected_reason: str | None = None
        polished_block = artifact.polished_block if strategy.allow_polished_block else None
        if polished_block and (topic_lines or quote_lines or numeric_lines or support_lines):
            accepted, reason = _validate_pdf_polished_block(
                polished_block,
                topic_lines=topic_lines,
                quote_lines=quote_lines,
                numeric_lines=numeric_lines,
                support_lines=support_lines,
                token_cap=strategy.polished_block_token_cap,
            )
            if accepted:
                polished_block_used = True
                accepted_polished_blocks += 1
            else:
                polished_block = None
                polished_block_rejected_reason = reason
                rejected_polished_blocks += 1
                if reason:
                    rejected_reasons.append(reason)

        chunk_selections.append(
            _PdfChunkSelection(
                chunk_index=chunk_index,
                section_index=section_index,
                section_title=section_title,
                headings=headings,
                topic_lines=topic_lines,
                quote_lines=quote_lines,
                numeric_lines=numeric_lines,
                support_lines=support_lines,
                polished_block=polished_block,
                polished_block_used=polished_block_used,
                polished_block_rejected_reason=polished_block_rejected_reason,
            )
        )

    dropped_counts = {
        category: max(total_counts[category] - selected_counts[category], 0)
        for category in selected_counts
    }
    return _PdfRenderPlan(
        title=title,
        chunk_selections=tuple(chunk_selections),
        selected_counts=selected_counts,
        dropped_counts=dropped_counts,
        accepted_polished_blocks=accepted_polished_blocks,
        rejected_polished_blocks=rejected_polished_blocks,
        rejected_polished_reasons=tuple(dict.fromkeys(rejected_reasons)),
    )


def _validate_pdf_polished_block(
    polished_block: str,
    *,
    topic_lines: tuple[str, ...],
    quote_lines: tuple[str, ...],
    numeric_lines: tuple[str, ...],
    support_lines: tuple[str, ...],
    token_cap: int,
) -> tuple[bool, str | None]:
    block = polished_block.strip()
    if not block:
        return False, "empty_polished_block"
    if estimate_text_tokens(block) > token_cap:
        return False, "polished_block_over_cap"
    block_casefold = block.casefold()

    for quote_line in quote_lines:
        quote_spans = [match for match in re.findall(r'"([^"\n]+)"|“([^”\n]+)”|‘([^’\n]+)’|\'([^\'\n]+)\'', quote_line)]
        normalized_spans = [next((part for part in match if part), "").strip() for match in quote_spans]
        normalized_spans = [span for span in normalized_spans if span]
        if normalized_spans:
            if not all(span in block for span in normalized_spans):
                return False, "missing_quote_span"
        elif quote_line not in block:
            return False, "missing_quote_line"

    required_numeric_tokens = set(_pdf_numeric_tokens("\n".join([*quote_lines, *numeric_lines])))
    block_numeric_tokens = set(_pdf_numeric_tokens(block))
    if not required_numeric_tokens.issubset(block_numeric_tokens):
        return False, "missing_numeric_token"
    if any(token not in required_numeric_tokens for token in block_numeric_tokens):
        return False, "added_numeric_token"

    for topic_line in (*topic_lines, *support_lines):
        anchors = _pdf_anchor_tokens(topic_line)
        if anchors and not any(anchor.casefold() in block_casefold for anchor in anchors):
            return False, "missing_topic_anchor"

    if re.match(r"^#{1,6}\s+", block):
        return False, "unexpected_heading"
    return True, None


def _render_pdf_chunk_selection(selection: _PdfChunkSelection, *, tidy_level: TidyLevel) -> list[str]:
    blocks: list[str] = []
    for heading in selection.headings:
        blocks.append(_format_pdf_heading(heading))
    if selection.polished_block_used and selection.polished_block:
        blocks.append(selection.polished_block)
        return blocks

    body_lines = [*selection.topic_lines, *selection.support_lines]
    preserved_lines = [*selection.quote_lines, *selection.numeric_lines]
    if tidy_level == "light_cleanup":
        for line in [*body_lines, *preserved_lines]:
            if _is_pdf_reference_or_caption_line(line) or _is_markdown_structural_line(line):
                blocks.append(line)
            else:
                blocks.append(f"- {line}")
        return blocks

    if body_lines:
        if tidy_level in {"structured_notes", "editorial_polish", "full_revision"} and len(body_lines) > 1:
            blocks.append(" ".join(body_lines))
        else:
            blocks.extend(body_lines)
    for line in preserved_lines:
        if line in blocks:
            continue
        if _is_pdf_reference_or_caption_line(line) or _is_markdown_structural_line(line):
            blocks.append(line)
        else:
            blocks.append(f"- {line}")
    return blocks


def _render_pdf_plan(
    plan: _PdfRenderPlan,
    *,
    tidy_level: TidyLevel,
    output_budget_tokens: int,
) -> tuple[str | None, dict[str, Any]]:
    blocks: list[str] = []
    if plan.title:
        blocks.append(_format_pdf_heading(plan.title, level="#"))

    seen_headings: set[str] = set()
    for selection in plan.chunk_selections:
        chunk_blocks = _render_pdf_chunk_selection(selection, tidy_level=tidy_level)
        for block in chunk_blocks:
            normalized = _normalize_evidence_line(block)
            if block.startswith("## "):
                if normalized in seen_headings:
                    continue
                seen_headings.add(normalized)
            candidate = "\n\n".join([*blocks, block])
            if blocks and estimate_text_tokens(candidate) > output_budget_tokens:
                continue
            blocks.append(block)

    rendered = "\n\n".join(blocks).strip() or None
    debug = {
        "title": plan.title,
        "selected_counts": dict(plan.selected_counts),
        "dropped_counts": dict(plan.dropped_counts),
        "accepted_polished_blocks": plan.accepted_polished_blocks,
        "rejected_polished_blocks": plan.rejected_polished_blocks,
        "rejected_polished_reasons": list(plan.rejected_polished_reasons),
        "chunks": [
            {
                "chunk_index": selection.chunk_index,
                "section_index": selection.section_index,
                "section_title": selection.section_title,
                "heading_count": len(selection.headings),
                "topic_count": len(selection.topic_lines),
                "quote_count": len(selection.quote_lines),
                "numeric_count": len(selection.numeric_lines),
                "support_count": len(selection.support_lines),
                "polished_block_used": selection.polished_block_used,
                "polished_block_rejected_reason": selection.polished_block_rejected_reason,
            }
            for selection in plan.chunk_selections
        ],
    }
    return rendered, debug


def _compress_pdf_artifacts(
    artifacts: list[tuple[str, ...]],
    *,
    budget_tokens: int,
) -> tuple[str, ...]:
    """Keep exact PDF evidence lines within budget without another model pass."""
    if not artifacts:
        return ()

    selected_counts = [0] * len(artifacts)
    best: tuple[str, ...] = ()

    while True:
        advanced = False
        for index, artifact in enumerate(artifacts):
            if selected_counts[index] >= len(artifact):
                continue
            candidate_counts = selected_counts.copy()
            candidate_counts[index] += 1
            candidate = _dedupe_evidence_lines(
                line
                for artifact_lines, line_count in zip(artifacts, candidate_counts, strict=True)
                for line in artifact_lines[:line_count]
            )
            if _serialized_evidence_token_count(candidate) > budget_tokens:
                continue
            selected_counts[index] += 1
            best = candidate
            advanced = True
        if not advanced:
            break

    if best:
        return best
    return _dedupe_evidence_lines(
        line
        for artifact in artifacts
        for line in artifact[:1]
    )


def _format_pdf_heading(line: str, *, level: str = "##") -> str:
    stripped = re.sub(r"^#{1,6}\s+", "", line).strip()
    return f"{level} {stripped}" if stripped else level


def _render_pdf_stitched_text(
    evidence_lines: tuple[str, ...],
    *,
    tidy_level: TidyLevel,
    output_budget_tokens: int,
) -> str | None:
    if not evidence_lines:
        return None

    blocks: list[str] = []
    paragraph_buffer: list[str] = []

    def flush_paragraph() -> None:
        if not paragraph_buffer:
            return
        if tidy_level in {"structured_notes", "editorial_polish", "full_revision"} and len(paragraph_buffer) > 1:
            blocks.append(" ".join(paragraph_buffer))
        elif tidy_level in {"editorial_polish", "full_revision"}:
            blocks.append(paragraph_buffer[0])
        else:
            for line in paragraph_buffer:
                blocks.append(f"- {line}")
        paragraph_buffer.clear()

    for index, raw_line in enumerate(evidence_lines):
        line = raw_line.strip()
        if not line:
            continue
        if index == 0 and not _is_markdown_structural_line(line) and len(line) <= 180:
            flush_paragraph()
            blocks.append(_format_pdf_heading(line, level="#"))
            continue
        if _is_pdf_heading_line(line):
            flush_paragraph()
            blocks.append(_format_pdf_heading(line))
            continue
        if _is_markdown_structural_line(line) or _is_pdf_reference_or_caption_line(line):
            flush_paragraph()
            blocks.append(line)
            continue
        paragraph_buffer.append(line)
        if tidy_level in {"structured_notes", "editorial_polish", "full_revision"}:
            joined = " ".join(paragraph_buffer)
            char_threshold = 240 if tidy_level == "structured_notes" else 360
            if len(joined) >= char_threshold or re.search(r'[.!?]["”’)\]]?$', line):
                flush_paragraph()
        else:
            flush_paragraph()

    flush_paragraph()
    if not blocks:
        return None

    selected_blocks: list[str] = []
    for block in blocks:
        candidate = "\n\n".join(selected_blocks + [block])
        if selected_blocks and estimate_text_tokens(candidate) > output_budget_tokens:
            break
        selected_blocks.append(block)

    preservation_heading = "## Preserved Source Spans"
    preservation_blocks = [
        block
        for block in blocks[len(selected_blocks):]
        if _is_pdf_preservation_block(block)
    ]
    if preservation_blocks:
        candidate_blocks = selected_blocks.copy()
        for preservation_block in preservation_blocks:
            addition = preservation_block
            next_blocks = (
                candidate_blocks + [preservation_heading, addition]
                if preservation_heading not in candidate_blocks
                else candidate_blocks + [addition]
            )
            candidate = "\n\n".join(next_blocks)
            if estimate_text_tokens(candidate) > output_budget_tokens:
                break
            candidate_blocks = next_blocks
        selected_blocks = candidate_blocks

    rendered = "\n\n".join(selected_blocks).strip()
    if not rendered:
        return None
    return rendered


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
    profile: _LongDocumentProfile,
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
        result, _retries = await _call_with_retry(
            lambda: _complete_json_with_timeout(
                llm,
                json.dumps(merged_input, ensure_ascii=False),
                system=variant.merge_system,
                timeout_seconds=profile.reduce_timeout_seconds,
            ),
            timeout_seconds=profile.reduce_timeout_seconds,
            max_retries=1,
            retry_base_delay_seconds=profile.retry_base_delay_seconds,
        )
    except ValueError:
        return _dedupe_evidence_lines(source_lines)
    except Exception:
        return _dedupe_evidence_lines(source_lines)

    merged_lines = _extract_evidence_lines(result, limit=None)
    if not _is_grounded_merge(merged_lines, source_lines):
        return _dedupe_evidence_lines(source_lines)
    return merged_lines


async def _compress_evidence_lines(
    llm: LLMClient,
    chunk_results: list[_ChunkResult],
    variant: ExtractorPromptVariant,
    profile: _LongDocumentProfile,
    *,
    budget_chars: int = _FINAL_RENDER_EVIDENCE_CHARS,
    budget_tokens: int | None = None,
) -> tuple[str, ...]:
    """Use deterministic dedupe first, then hierarchical merge only when still too large."""
    merged = _merge_evidence_from_chunks(chunk_results)
    if profile.name == "pdf":
        effective_budget_tokens = budget_tokens or budget_chars
        if _serialized_evidence_token_count(merged) <= effective_budget_tokens:
            return merged
    elif _serialized_evidence_size(merged) <= budget_chars:
        return merged

    artifacts = [chunk_result.evidence_lines for chunk_result in chunk_results if chunk_result.evidence_lines]
    if not artifacts:
        return merged
    if profile.name == "pdf":
        return _compress_pdf_artifacts(artifacts, budget_tokens=effective_budget_tokens)

    while len(artifacts) > 1:
        next_level: list[tuple[str, ...]] = []
        for index in range(0, len(artifacts), _MERGE_GROUP_SIZE):
            group = artifacts[index:index + _MERGE_GROUP_SIZE]
            next_level.append(await _merge_evidence_group(llm, group, variant, profile))
        artifacts = next_level
        if len(artifacts) == 1 and _serialized_evidence_size(artifacts[0]) <= budget_chars:
            return artifacts[0]

    return artifacts[0] if artifacts else merged


async def _compress_tidy_evidence_lines(
    llm: LLMClient,
    chunk_results: list[_TidyChunkResult],
    variant: ExtractorPromptVariant,
    profile: _LongDocumentProfile,
    *,
    budget_chars: int = _FINAL_RENDER_EVIDENCE_CHARS,
    budget_tokens: int | None = None,
) -> tuple[str, ...]:
    """Compress evidence lines for tidy-only rendering."""
    merged = _dedupe_evidence_lines(
        line
        for chunk_result in chunk_results
        for line in chunk_result.evidence_lines
    )
    if profile.name == "pdf":
        effective_budget_tokens = budget_tokens or budget_chars
        if _serialized_evidence_token_count(merged) <= effective_budget_tokens:
            return merged
    elif _serialized_evidence_size(merged) <= budget_chars:
        return merged

    artifacts = [chunk_result.evidence_lines for chunk_result in chunk_results if chunk_result.evidence_lines]
    if not artifacts:
        return merged
    if profile.name == "pdf":
        return _compress_pdf_artifacts(artifacts, budget_tokens=effective_budget_tokens)

    while len(artifacts) > 1:
        next_level: list[tuple[str, ...]] = []
        for index in range(0, len(artifacts), _MERGE_GROUP_SIZE):
            group = artifacts[index:index + _MERGE_GROUP_SIZE]
            next_level.append(await _merge_evidence_group(llm, group, variant, profile))
        artifacts = next_level
        if len(artifacts) == 1 and _serialized_evidence_size(artifacts[0]) <= budget_chars:
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


def _deterministic_pdf_title(
    evidence_lines: tuple[str, ...],
    entities: Iterable[ExtractedEntity] = (),
) -> str | None:
    fallback_candidate: str | None = None
    for line in evidence_lines:
        candidate = re.sub(r"^(?:#{1,6}\s+|[-*+]\s+|\d+\.\s+)", "", line).strip()
        if not candidate:
            continue
        if re.match(r"^(?:\d|figure\b|table\b|doi:)", candidate, re.IGNORECASE):
            continue
        if _is_pdf_affiliation_line(candidate):
            continue
        if fallback_candidate is None:
            fallback_candidate = candidate[:117].rstrip() + "..." if len(candidate) > 120 else candidate
        if _is_pdf_heading_line(line):
            return fallback_candidate
    for entity in entities:
        name = entity.name.strip()
        if 4 <= len(name) <= 120:
            return name
    return fallback_candidate or _fallback_title(evidence_lines)


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
    profile: _LongDocumentProfile,
    trace: ExtractionTrace | None = None,
) -> tuple[ExtractionResult, bool]:
    """Render the final tidy output from a grounded merged artifact."""
    entities = _merge_entities(chunk_results)
    pdf_strategy = _resolve_pdf_tidy_strategy(tidy_level) if profile.name == "pdf" else None
    if pdf_strategy is not None:
        pdf_artifacts = tuple(chunk_result.pdf_artifact for chunk_result in chunk_results if chunk_result.pdf_artifact is not None)
        if pdf_artifacts:
            plan = _select_pdf_render_plan(pdf_artifacts, strategy=pdf_strategy, entities=entities)
            tidy_text, debug = _render_pdf_plan(
                plan,
                tidy_level=tidy_level,
                output_budget_tokens=pdf_strategy.output_budget_tokens,
            )
            if trace is not None:
                trace.pdf_debug = debug
            return (
                ExtractionResult(
                    entities=entities,
                    tidy_title=plan.title,
                    tidy_text=tidy_text or _fallback_tidy_text(
                        _dedupe_evidence_lines(
                            line
                            for artifact in pdf_artifacts
                            for line in _flatten_pdf_artifact_lines(artifact)
                        )
                    ),
                ),
                False,
            )

    evidence_lines = await _compress_evidence_lines(
        llm,
        chunk_results,
        variant,
        profile,
        budget_chars=_FINAL_RENDER_EVIDENCE_CHARS,
        budget_tokens=pdf_strategy.evidence_budget_tokens if pdf_strategy else None,
    )
    if not evidence_lines:
        return ExtractionResult(entities=entities), True
    if pdf_strategy is not None and pdf_strategy.render_mode == "deterministic":
        tidy_title = _deterministic_pdf_title(evidence_lines, entities)
        tidy_text = _render_pdf_stitched_text(
            evidence_lines,
            tidy_level=tidy_level,
            output_budget_tokens=pdf_strategy.output_budget_tokens,
        ) or _fallback_tidy_text(evidence_lines)
        return (
            ExtractionResult(
                entities=entities,
                tidy_title=tidy_title,
                tidy_text=tidy_text,
            ),
            False,
        )

    render_input = json.dumps({"evidence_lines": list(evidence_lines)}, ensure_ascii=False)
    fallback_used = False
    try:
        result, _retries = await _call_with_retry(
            lambda: _complete_json_with_timeout(
                llm,
                render_input,
                system=_with_tidy_level(variant.reduce_system, tidy_level),
                timeout_seconds=profile.reduce_timeout_seconds,
            ),
            timeout_seconds=profile.reduce_timeout_seconds,
            max_retries=1,
            retry_base_delay_seconds=profile.retry_base_delay_seconds,
        )
        tidy_title = _clean_optional_str(result.get("tidy_title")) or _fallback_title(evidence_lines)
        tidy_text = _clean_optional_str(result.get("tidy_text")) or _fallback_tidy_text(evidence_lines)
        fallback_used = tidy_title == _fallback_title(evidence_lines) or tidy_text == _fallback_tidy_text(evidence_lines)
    except Exception:
        tidy_title = _fallback_title(evidence_lines)
        tidy_text = _fallback_tidy_text(evidence_lines)
        fallback_used = True

    return (
        ExtractionResult(
            entities=entities,
            tidy_title=tidy_title,
            tidy_text=tidy_text,
        ),
        fallback_used,
    )


async def _render_tidy_from_evidence(
    llm: LLMClient,
    evidence_lines: tuple[str, ...],
    variant: ExtractorPromptVariant,
    tidy_level: TidyLevel,
    profile: _LongDocumentProfile,
    chunk_results: list[_TidyChunkResult] | None = None,
    trace: ExtractionTrace | None = None,
) -> tuple[ExtractionResult, bool]:
    """Render tidy-only output from grounded evidence lines."""
    if not evidence_lines:
        return ExtractionResult(entities=[]), True
    pdf_strategy = _resolve_pdf_tidy_strategy(tidy_level) if profile.name == "pdf" else None
    if pdf_strategy is not None and chunk_results:
        pdf_artifacts = tuple(chunk_result.pdf_artifact for chunk_result in chunk_results if chunk_result.pdf_artifact is not None)
        if pdf_artifacts:
            plan = _select_pdf_render_plan(pdf_artifacts, strategy=pdf_strategy, entities=())
            tidy_text, debug = _render_pdf_plan(
                plan,
                tidy_level=tidy_level,
                output_budget_tokens=pdf_strategy.output_budget_tokens,
            )
            if trace is not None:
                trace.pdf_debug = debug
            return (
                ExtractionResult(
                    entities=[],
                    tidy_title=plan.title or _fallback_title(evidence_lines),
                    tidy_text=tidy_text or _fallback_tidy_text(evidence_lines),
                ),
                False,
            )
    if pdf_strategy is not None and pdf_strategy.render_mode == "deterministic":
        return (
            ExtractionResult(
                entities=[],
                tidy_title=_fallback_title(evidence_lines),
                tidy_text=_render_pdf_stitched_text(
                    evidence_lines,
                    tidy_level=tidy_level,
                    output_budget_tokens=pdf_strategy.output_budget_tokens,
                ) or _fallback_tidy_text(evidence_lines),
            ),
            False,
        )

    render_input = json.dumps({"evidence_lines": list(evidence_lines)}, ensure_ascii=False)
    fallback_used = False
    try:
        result, _retries = await _call_with_retry(
            lambda: _complete_json_with_timeout(
                llm,
                render_input,
                system=_with_tidy_level(variant.reduce_system, tidy_level),
                timeout_seconds=profile.reduce_timeout_seconds,
            ),
            timeout_seconds=profile.reduce_timeout_seconds,
            max_retries=1,
            retry_base_delay_seconds=profile.retry_base_delay_seconds,
        )
        tidy_title = _clean_optional_str(result.get("tidy_title")) or _fallback_title(evidence_lines)
        tidy_text = _clean_optional_str(result.get("tidy_text")) or _fallback_tidy_text(evidence_lines)
        fallback_used = tidy_title == _fallback_title(evidence_lines) or tidy_text == _fallback_tidy_text(evidence_lines)
    except Exception:
        tidy_title = _fallback_title(evidence_lines)
        tidy_text = _fallback_tidy_text(evidence_lines)
        fallback_used = True

    return (
        ExtractionResult(
            entities=[],
            tidy_title=tidy_title,
            tidy_text=tidy_text,
        ),
        fallback_used,
    )


async def extract_entities(
    llm: LLMClient,
    text: str,
    *,
    prompt_variant: str = DEFAULT_PROMPT_VARIANT,
    tidy_level: TidyLevel = DEFAULT_TIDY_LEVEL,
    trace: ExtractionTrace | None = None,
    source_mime_type: str | None = None,
    progress_callback: ProgressCallback | None = None,
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
    profile = _resolve_long_document_profile(source_mime_type)
    pdf_strategy = _resolve_pdf_tidy_strategy(tidy_level) if profile.name == "pdf" else None
    map_system = (
        _with_pdf_chunk_budget(variant.map_system, pdf_strategy, include_entities=True)
        if pdf_strategy else variant.map_system
    )
    if trace is not None:
        trace.prompt_variant = variant.name
        trace.tidy_level = tidy_level
        trace.source_profile = profile.name

    if len(stripped) < _CHUNK_THRESHOLD:
        if trace is not None:
            trace.strategy = "single"
            trace.chunk_count = 1
        return await _extract_single(llm, stripped, variant, tidy_level)

    # Long documents: map to grounded chunk artifacts, then render from the merged artifact.
    chunks = _split_chunks(stripped, chunk_size=profile.chunk_size, overlap=profile.overlap)
    if trace is not None:
        trace.strategy = "map_reduce"
        trace.chunk_count = len(chunks)
    chunk_results, failed_chunks, retry_count = await _run_chunk_stage(
        chunks=chunks,
        worker=lambda chunk: _extract_chunk(
            llm,
            chunk,
            variant,
            system=map_system,
            timeout_seconds=profile.map_timeout_seconds,
            pdf_strategy=pdf_strategy,
        ),
        profile=profile,
        progress_callback=progress_callback,
        stage="map",
    )
    if trace is not None:
        trace.failed_chunk_count = failed_chunks
        trace.retry_count = retry_count
    if not chunk_results:
        fallback_result = _fallback_result_from_text(stripped)
        if trace is not None:
            trace.fallback_used = True
        await _emit_progress(
            progress_callback,
            {
                "status": "partial",
                "stage": "done",
                "chunk_total": len(chunks),
                "chunk_completed": len(chunks),
                "chunk_failed": failed_chunks or len(chunks),
                "retry_count": retry_count,
                "fallback_used": True,
                "source_profile": profile.name,
            },
        )
        return fallback_result

    await _emit_progress(
        progress_callback,
        {
            "status": "running",
            "stage": "stitch" if pdf_strategy is not None and pdf_strategy.render_mode == "deterministic" else "reduce",
            "chunk_total": len(chunks),
            "chunk_completed": len(chunks),
            "chunk_failed": failed_chunks,
            "retry_count": retry_count,
            "source_profile": profile.name,
        },
    )
    rendered_result, reduce_fallback_used = await _render_long_document(
        llm,
        chunk_results,
        variant,
        tidy_level,
        profile,
        trace,
    )
    if trace is not None:
        trace.fallback_used = failed_chunks > 0 or reduce_fallback_used
    await _emit_progress(
        progress_callback,
        {
            "status": "partial" if failed_chunks > 0 or reduce_fallback_used else "completed",
            "stage": "done",
            "chunk_total": len(chunks),
            "chunk_completed": len(chunks),
            "chunk_failed": failed_chunks,
            "retry_count": retry_count,
            "fallback_used": failed_chunks > 0 or reduce_fallback_used,
            "source_profile": profile.name,
        },
    )
    return rendered_result


async def render_tidy_text(
    llm: LLMClient,
    text: str,
    *,
    prompt_variant: str = DEFAULT_PROMPT_VARIANT,
    tidy_level: TidyLevel = DEFAULT_TIDY_LEVEL,
    trace: ExtractionTrace | None = None,
    source_mime_type: str | None = None,
    progress_callback: ProgressCallback | None = None,
) -> ExtractionResult:
    """Render tidy_title and tidy_text without running entity extraction."""
    stripped = text.strip()
    if not stripped:
        return ExtractionResult(entities=[])

    variant = get_prompt_variant(prompt_variant)
    profile = _resolve_long_document_profile(source_mime_type)
    pdf_strategy = _resolve_pdf_tidy_strategy(tidy_level) if profile.name == "pdf" else None
    map_system = (
        _with_pdf_chunk_budget(_TIDY_ONLY_MAP_SYSTEM, pdf_strategy, include_entities=False)
        if pdf_strategy else _TIDY_ONLY_MAP_SYSTEM
    )
    if trace is not None:
        trace.prompt_variant = variant.name
        trace.tidy_level = tidy_level
        trace.source_profile = profile.name

    if len(stripped) < _CHUNK_THRESHOLD:
        if trace is not None:
            trace.strategy = "single"
            trace.chunk_count = 1
        return await _render_single_tidy(llm, stripped, tidy_level)

    chunks = _split_chunks(stripped, chunk_size=profile.chunk_size, overlap=profile.overlap)
    if trace is not None:
        trace.strategy = "map_reduce"
        trace.chunk_count = len(chunks)
    chunk_results, failed_chunks, retry_count = await _run_chunk_stage(
        chunks=chunks,
        worker=lambda chunk: _extract_tidy_chunk(
            llm,
            chunk,
            system=map_system,
            timeout_seconds=profile.map_timeout_seconds,
            pdf_strategy=pdf_strategy,
        ),
        profile=profile,
        progress_callback=progress_callback,
        stage="tidy_map",
    )
    if trace is not None:
        trace.failed_chunk_count = failed_chunks
        trace.retry_count = retry_count
    if not chunk_results:
        fallback_result = _fallback_result_from_text(stripped)
        if trace is not None:
            trace.fallback_used = True
        await _emit_progress(
            progress_callback,
            {
                "status": "partial",
                "stage": "done",
                "chunk_total": len(chunks),
                "chunk_completed": len(chunks),
                "chunk_failed": failed_chunks or len(chunks),
                "retry_count": retry_count,
                "fallback_used": True,
                "source_profile": profile.name,
            },
        )
        return fallback_result
    evidence_lines = await _compress_tidy_evidence_lines(
        llm,
        chunk_results,
        variant,
        profile,
        budget_chars=_FINAL_RENDER_EVIDENCE_CHARS,
        budget_tokens=pdf_strategy.evidence_budget_tokens if pdf_strategy else None,
    )
    await _emit_progress(
        progress_callback,
        {
            "status": "running",
            "stage": "stitch" if pdf_strategy is not None and pdf_strategy.render_mode == "deterministic" else "reduce",
            "chunk_total": len(chunks),
            "chunk_completed": len(chunks),
            "chunk_failed": failed_chunks,
            "retry_count": retry_count,
            "source_profile": profile.name,
        },
    )
    rendered_result, reduce_fallback_used = await _render_tidy_from_evidence(
        llm,
        evidence_lines,
        variant,
        tidy_level,
        profile,
        chunk_results=chunk_results,
        trace=trace,
    )
    if trace is not None:
        trace.fallback_used = failed_chunks > 0 or reduce_fallback_used
    await _emit_progress(
        progress_callback,
        {
            "status": "partial" if failed_chunks > 0 or reduce_fallback_used else "completed",
            "stage": "done",
            "chunk_total": len(chunks),
            "chunk_completed": len(chunks),
            "chunk_failed": failed_chunks,
            "retry_count": retry_count,
            "fallback_used": failed_chunks > 0 or reduce_fallback_used,
            "source_profile": profile.name,
        },
    )
    return rendered_result


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
