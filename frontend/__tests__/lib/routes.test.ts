import { afterEach, describe, expect, it, vi } from "vitest";
import { documentHref, engramHref } from "@/lib/routes";

describe("routes", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("uses dynamic app routes outside static export mode", () => {
    vi.stubEnv("NEXT_PUBLIC_STATIC_EXPORT", "");

    expect(documentHref("doc-42")).toBe("/documents/doc-42");
    expect(engramHref("eng-7")).toBe("/engrams/eng-7");
  });

  it("uses query routes during static export builds", () => {
    vi.stubEnv("NEXT_PUBLIC_STATIC_EXPORT", "1");

    expect(documentHref("doc-42")).toBe("/document?id=doc-42");
    expect(engramHref("eng-7")).toBe("/engram?id=eng-7");
  });
});
