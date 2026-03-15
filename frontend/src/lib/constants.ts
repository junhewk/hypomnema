/** Single-letter icons used in provider cards. */
export const PROVIDER_ICONS: Record<string, string> = {
  local: "L",
  claude: "A",
  google: "G",
  openai: "O",
  ollama: "~",
};

export const BASE_LLM_PROVIDER = "google";
export const BASE_LLM_MODEL = "gemini-2.5-flash";
export const BASE_LLM_LABEL = "recommended from tidy eval";

export const TIDY_LEVEL_OPTIONS = [
  {
    id: "format_only",
    name: "Format only",
    description: "Whitespace and markdown only. No sentence edits.",
  },
  {
    id: "light_cleanup",
    name: "Light cleanup",
    description: "Minor typo and punctuation cleanup with very light structure.",
  },
  {
    id: "structured_notes",
    name: "Structured notes",
    description: "Clearer bullets and headings while keeping note-like phrasing.",
  },
  {
    id: "editorial_polish",
    name: "Editorial polish",
    description: "Moderate smoothing and sectioning without adding new claims.",
  },
  {
    id: "full_revision",
    name: "Full revision",
    description: "Full proofreading and reorganization with complete markdown.",
  },
] as const;
