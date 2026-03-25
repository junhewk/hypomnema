"""Shared tidy-level definitions and prompt metadata."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

TidyLevel = Literal[
    "format_only",
    "light_cleanup",
    "structured_notes",
    "editorial_polish",
    "full_revision",
]

DEFAULT_TIDY_LEVEL: TidyLevel = "structured_notes"
ALL_TIDY_LEVELS: tuple[TidyLevel, ...] = (
    "format_only",
    "light_cleanup",
    "structured_notes",
    "editorial_polish",
    "full_revision",
)


@dataclass(frozen=True)
class TidyLevelSpec:
    id: TidyLevel
    name: str
    summary: str
    prompt_directive: str


_TIDY_LEVEL_SPECS: dict[TidyLevel, TidyLevelSpec] = {
    "format_only": TidyLevelSpec(
        id="format_only",
        name="Format only",
        summary="No text editing; only whitespace and Markdown normalization.",
        prompt_directive=(
            "Tidy level: format_only.\n"
            "- Do not rewrite, paraphrase, proofread, translate, "
            "or reorder source content.\n"
            "- Preserve sentence wording, note fragments, line "
            "order, ordered-list numbering, and block order "
            "as written.\n"
            "- Preserve URLs, markdown links, inline code, HTML "
            "tags and attributes, quoted spans, numbers, dates, "
            "acronyms, and mixed-language spans exactly.\n"
            "- Only normalize whitespace, indentation, list "
            "markers, and obvious markdown fencing.\n"
            "- If the source already contains markdown, HTML, or "
            "docs-like structure, edit it in place. Do not "
            "replace it with summary bullets, new headings, "
            "or prose.\n"
            "- If markdown structure is missing, add only the "
            "minimum bullets or blank lines needed to mirror "
            "the existing line breaks.\n"
            "- Keep rough notes rough. Do not smooth grammar "
            "or punctuation."
        ),
    ),
    "light_cleanup": TidyLevelSpec(
        id="light_cleanup",
        name="Light cleanup",
        summary=(
            "Minor cleanup with minimal markdown structure "
            "and no material rewrites."
        ),
        prompt_directive=(
            "Tidy level: light_cleanup.\n"
            "- Allow only minor fixes to spacing, punctuation, "
            "casing, and obvious typos when token identity "
            "stays the same.\n"
            "- Keep wording, order, and note granularity very "
            "close to the source.\n"
            "- Preserve source casing for technical terms and "
            "note fragments. Do not sentence-case lower-case "
            "source lines, capitalize fragment starts, or add "
            "terminal punctuation unless the source already "
            "supports it or the original is an obvious typo.\n"
            "- Preserve URLs, markdown links, inline code, HTML, "
            "quoted spans, numbers, dates, acronyms, "
            "ordered-list numbering, and mixed-language "
            "spans exactly.\n"
            "- Use minimal markdown structure such as preserved "
            "headings or bullets when it clarifies the source.\n"
            "- If the source is already markdown, HTML, README, "
            "or docs-like, edit in place instead of "
            "reorganizing it.\n"
            "- Do not merge fragments into polished summary "
            "prose."
        ),
    ),
    "structured_notes": TidyLevelSpec(
        id="structured_notes",
        name="Structured notes",
        summary=(
            "Clearer bullets and headings while preserving "
            "note tone and source order."
        ),
        prompt_directive=(
            "Tidy level: structured_notes.\n"
            "- You may regroup nearby lines into clearer "
            "bullets and short headings, but only within "
            "adjacent local blocks.\n"
            "- Preserve note-like tone, original sequencing, "
            "existing headings, ordered-list numbering, and "
            "source phrasing whenever possible.\n"
            "- If the source already uses markdown headings or "
            "bullet markers, preserve the original heading "
            "levels and list-marker style exactly unless "
            "whitespace cleanup is the only change.\n"
            "- Preserve source casing for key terms and "
            "fragment lines. Do not convert lower-case notes "
            "into sentence case or add finishing punctuation "
            "just to make them look polished.\n"
            "- Preserve mixed-language shorthand, "
            "abbreviations, and note tokens exactly, "
            "including short markers such as V, N, and "
            "compact spans like from F.\n"
            "- If the source is already markdown, HTML, "
            "README, or docs-like, prefer edit-in-place "
            "cleanup over reorganization.\n"
            "- Preserve URLs, markdown links, quoted spans, "
            "numbers, dates, acronyms, speaker labels, and "
            "mixed-language spans exactly.\n"
            "- Allow minimal paraphrase only when needed to "
            "remove exact duplication or broken formatting.\n"
            "- Prefer bullet lists over prose paragraphs, but "
            "do not collapse technical docs into generic "
            "summary bullets.\n"
            "- For mixed-language or shorthand-heavy notes, "
            "keep one output bullet close to each source "
            "line instead of compressing several lines into "
            "a rewritten summary."
        ),
    ),
    "editorial_polish": TidyLevelSpec(
        id="editorial_polish",
        name="Editorial polish",
        summary=(
            "Moderate sentence smoothing and sectioning "
            "while preserving all facts."
        ),
        prompt_directive=(
            "Tidy level: editorial_polish.\n"
            "- You may smooth grammar, combine closely related "
            "fragments, and lightly reorder within an existing "
            "section for clarity.\n"
            "- Preserve all facts, quotes, dates, numbers, "
            "URLs, code spans, speaker labels, names, "
            "acronyms, and mixed-language spans exactly.\n"
            "- Preserve mixed-language shorthand and cryptic "
            "note tokens exactly, including compact spans "
            "such as from F, N, V, ARPA-H, LLM, and "
            "parenthetical prompts.\n"
            "- If the source already uses markdown headings or "
            "speaker sections, preserve the section boundaries "
            "and heading levels instead of converting them "
            "into prose exposition.\n"
            "- Keep the output grounded in the source; do not "
            "add framing metadata, new conclusions, or "
            "inferred claims.\n"
            "- Preserve existing section anchors and README or "
            "docs structure when present; do not rewrite docs "
            "into memo framing or generic summary bullets.\n"
            "- Use clear markdown sections and bullets, but "
            "only add headings that are directly grounded "
            "in source wording.\n"
            "- For discussion notes, transcripts, or "
            "bullet-heavy source text, keep the result in "
            "bullets rather than converting it into "
            "explanatory paragraphs."
        ),
    ),
    "full_revision": TidyLevelSpec(
        id="full_revision",
        name="Full revision",
        summary=(
            "Full proofreading and reorganization with "
            "complete markdown structure."
        ),
        prompt_directive=(
            "Tidy level: full_revision.\n"
            "- You may fully proofread, deduplicate, and "
            "reorganize the source into coherent markdown "
            "sections.\n"
            "- Before rewriting, preserve every quote, URL, "
            "code span, numbered sequence, date, number, "
            "name, acronym, and mixed-language span.\n"
            "- Preserve mixed-language shorthand and compact "
            "note tokens exactly, including spans such as "
            "from F, N, V, ARPA-H, and parenthetical "
            "note prompts.\n"
            "- If the source already uses markdown headings, "
            "lists, or speaker sections, preserve the "
            "original section boundaries and heading levels "
            "unless a directly grounded reordering clearly "
            "improves clarity.\n"
            "- Rewriting for clarity is allowed, but every "
            "claim and heading must remain directly "
            "supported by the source.\n"
            "- For bullet-heavy or discussion-note inputs, "
            "keep source bullets one-to-one whenever "
            "possible. Do not replace a concrete source "
            "bullet with an abstract topic label plus "
            "nested explanatory bullets.\n"
            "- Each rewritten bullet must retain a verbatim "
            "anchor phrase from its source bullet, "
            "especially concrete noun-verb spans and object "
            "phrases such as \uc2a4\ud53c\ucee4\ub97c, "
            "\ub2e4\uc591\uc131\uc744 \uace0\ubbfc\ud558\uace0, or other "
            "distinctive wording.\n"
            "- For short or fragmentary note inputs, do not "
            "add umbrella introductions, thesis sentences, "
            "or meta framing such as 'this note outlines'. "
            "Prefer one grounded bullet per source idea.\n"
            "- Avoid unnecessary expansion. Keep the output "
            "close to the source information density and "
            "do not add explanatory padding or nested "
            "sub-bullets unless the source already "
            "warrants them.\n"
            "- For markdown, HTML, README, or docs-like "
            "inputs, retain the original section hierarchy "
            "unless a directly grounded reordering clearly "
            "improves clarity.\n"
            "- For discussion notes, transcripts, and "
            "bullet-heavy source text, keep the result in "
            "concise bullets or preserved speaker sections "
            "instead of converting them into "
            "multi-paragraph exposition.\n"
            "- Do not invent addressees, metadata, "
            "conclusions, or context that is not explicit "
            "in the source."
        ),
    ),
}


def get_tidy_level_spec(level: TidyLevel = DEFAULT_TIDY_LEVEL) -> TidyLevelSpec:
    """Return metadata for a tidy level."""
    return _TIDY_LEVEL_SPECS[level]


def list_tidy_levels() -> tuple[TidyLevelSpec, ...]:
    """Return tidy levels in UI/eval order."""
    return tuple(_TIDY_LEVEL_SPECS[level] for level in ALL_TIDY_LEVELS)


def coerce_tidy_level(value: str | TidyLevel) -> TidyLevel:
    """Validate and normalize a tidy level string."""
    if value in _TIDY_LEVEL_SPECS:
        return cast("TidyLevel", value)
    available = ", ".join(ALL_TIDY_LEVELS)
    raise ValueError(f"Unknown tidy level {value!r}. Available: {available}")
