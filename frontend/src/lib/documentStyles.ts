import type { SourceType } from "./types";

export const SOURCE_STYLES: Record<
  SourceType,
  { label: string; className: string; borderColor: string }
> = {
  scribble: {
    label: "scribble",
    className:
      "text-[var(--source-scribble)] bg-[var(--source-scribble)]/10",
    borderColor: "var(--source-scribble)",
  },
  file: {
    label: "file",
    className:
      "text-[var(--source-file)] bg-[var(--source-file)]/10",
    borderColor: "var(--source-file)",
  },
  feed: {
    label: "feed",
    className:
      "text-[var(--source-feed)] bg-[var(--source-feed)]/10",
    borderColor: "var(--source-feed)",
  },
  url: {
    label: "url",
    className:
      "text-[var(--source-url)] bg-[var(--source-url)]/10",
    borderColor: "var(--source-url)",
  },
};

export const STATUS_COLOR: Record<number, string> = {
  0: "bg-amber-400",
  1: "bg-blue-400",
  2: "bg-green-400",
};

export const STATUS_ANIM: Record<number, string> = {
  0: "animate-pulse-dot",
  1: "animate-pulse-dot",
  2: "",
};

export const STATUS_LABEL: Record<number, string> = {
  0: "Queued",
  1: "Entities extracted",
  2: "Complete",
};
