import { describe, it, expect, vi, afterEach } from "vitest";
import { timeAgo } from "@/lib/timeAgo";

describe("timeAgo", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  function at(date: string) {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(date));
  }

  it("returns 'just now' for <60 seconds ago", () => {
    at("2026-01-01T00:00:30Z");
    expect(timeAgo("2026-01-01T00:00:00Z")).toBe("just now");
  });

  it("returns minutes ago", () => {
    at("2026-01-01T00:05:00Z");
    expect(timeAgo("2026-01-01T00:00:00Z")).toBe("5m ago");
  });

  it("returns hours ago", () => {
    at("2026-01-01T03:00:00Z");
    expect(timeAgo("2026-01-01T00:00:00Z")).toBe("3h ago");
  });

  it("returns days ago", () => {
    at("2026-01-04T00:00:00Z");
    expect(timeAgo("2026-01-01T00:00:00Z")).toBe("3d ago");
  });

  it("returns weeks ago", () => {
    at("2026-01-22T00:00:00Z");
    expect(timeAgo("2026-01-01T00:00:00Z")).toBe("3w ago");
  });

  it("returns ISO date for >4 weeks", () => {
    at("2026-03-01T00:00:00Z");
    expect(timeAgo("2026-01-01T00:00:00Z")).toBe("2026-01-01");
  });
});
