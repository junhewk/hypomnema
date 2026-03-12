import type { Predicate } from "./types";

export function formatPredicate(predicate: Predicate): string {
  const words = predicate.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}
