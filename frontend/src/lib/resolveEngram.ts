import type { EngramDetail } from "./types";

export function resolveEngram(
  id: string,
  engramDetails: Map<string, EngramDetail>,
): Pick<EngramDetail, "id" | "canonical_name"> {
  const detail = engramDetails.get(id);
  if (detail) return detail;
  return { id, canonical_name: id.slice(0, 8) + "\u2026" };
}
