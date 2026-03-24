function isStaticExportMode(): boolean {
  return (
    typeof process !== "undefined" &&
    process.env.NEXT_PUBLIC_STATIC_EXPORT === "1"
  );
}

export function documentHref(id: string): string {
  if (isStaticExportMode()) {
    return `/document?id=${encodeURIComponent(id)}`;
  }
  return `/documents/${id}`;
}

export function engramHref(id: string): string {
  if (isStaticExportMode()) {
    return `/engram?id=${encodeURIComponent(id)}`;
  }
  return `/engrams/${id}`;
}
