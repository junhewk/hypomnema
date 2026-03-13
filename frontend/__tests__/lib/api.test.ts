import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { ApiClient, ApiError } from "@/lib/api";

const mockFetch = vi.fn();
global.fetch = mockFetch;

describe("ApiClient", () => {
  let client: ApiClient;
  const originalApiUrl = process.env.NEXT_PUBLIC_API_URL;
  const originalApiPort = process.env.NEXT_PUBLIC_API_PORT;
  const originalLocation = window.location;

  beforeEach(() => {
    delete process.env.NEXT_PUBLIC_API_URL;
    delete process.env.NEXT_PUBLIC_API_PORT;
    Object.defineProperty(window, "location", {
      configurable: true,
      value: new URL("http://localhost:3073/settings"),
    });
    client = new ApiClient("http://localhost:8073");
    mockFetch.mockReset();
  });

  afterEach(() => {
    if (originalApiUrl === undefined) {
      delete process.env.NEXT_PUBLIC_API_URL;
    } else {
      process.env.NEXT_PUBLIC_API_URL = originalApiUrl;
    }
    if (originalApiPort === undefined) {
      delete process.env.NEXT_PUBLIC_API_PORT;
    } else {
      process.env.NEXT_PUBLIC_API_PORT = originalApiPort;
    }
    Object.defineProperty(window, "location", {
      configurable: true,
      value: originalLocation,
    });
  });

  describe("constructor", () => {
    it("defaults to localhost:8073", () => {
      const c = new ApiClient();
      mockFetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ items: [], total: 0, offset: 0, limit: 20 }),
      });
      c.listDocuments();
      expect(mockFetch).toHaveBeenCalledWith(
        "http://localhost:8073/api/documents?offset=0&limit=20",
        expect.any(Object),
      );
    });

    it("derives the backend host from the browser location in auto mode", () => {
      process.env.NEXT_PUBLIC_API_URL = "auto";
      process.env.NEXT_PUBLIC_API_PORT = "9000";
      Object.defineProperty(window, "location", {
        configurable: true,
        value: new URL("http://100.122.169.13:3073/settings"),
      });

      const c = new ApiClient();
      mockFetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ items: [], total: 0, offset: 0, limit: 20 }),
      });

      c.listDocuments();

      expect(mockFetch).toHaveBeenCalledWith(
        "http://100.122.169.13:9000/api/documents?offset=0&limit=20",
        expect.any(Object),
      );
    });

    it("preserves same-origin mode when the env override is empty", () => {
      process.env.NEXT_PUBLIC_API_URL = "";

      const c = new ApiClient();
      mockFetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ items: [], total: 0, offset: 0, limit: 20 }),
      });

      c.listDocuments();

      expect(mockFetch).toHaveBeenCalledWith(
        "/api/documents?offset=0&limit=20",
        expect.any(Object),
      );
    });

    it("accepts custom base URL", () => {
      const c = new ApiClient("http://192.168.1.50:9000");
      mockFetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ items: [], total: 0, offset: 0, limit: 20 }),
      });
      c.listDocuments();
      expect(mockFetch).toHaveBeenCalledWith(
        "http://192.168.1.50:9000/api/documents?offset=0&limit=20",
        expect.any(Object),
      );
    });
  });

  describe("createScribble", () => {
    it("sends POST with text and title", async () => {
      const mockDoc = {
        id: "abc123",
        source_type: "scribble",
        title: "Test",
        text: "Hello world",
        created_at: "2026-01-01T00:00:00.000Z",
        updated_at: "2026-01-01T00:00:00.000Z",
        mime_type: null,
        source_uri: null,
        metadata: null,
        triaged: 0,
        processed: 0,
      };
      mockFetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => mockDoc,
      });
      const result = await client.createScribble("Hello world", "Test");
      expect(mockFetch).toHaveBeenCalledWith(
        "http://localhost:8073/api/documents/scribbles",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ text: "Hello world", title: "Test" }),
        }),
      );
      expect(result.id).toBe("abc123");
    });
  });

  describe("listDocuments", () => {
    it("sends GET with default pagination", async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ items: [], total: 0, offset: 0, limit: 20 }),
      });
      const result = await client.listDocuments();
      expect(mockFetch).toHaveBeenCalledWith(
        "http://localhost:8073/api/documents?offset=0&limit=20",
        expect.any(Object),
      );
      expect(result.items).toEqual([]);
    });
  });

  describe("searchDocuments", () => {
    it("encodes query parameter", async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => [],
      });
      await client.searchDocuments("AI ethics & bias");
      expect(mockFetch).toHaveBeenCalledWith(
        "http://localhost:8073/api/search/documents?q=AI%20ethics%20%26%20bias",
        expect.any(Object),
      );
    });
  });

  describe("deleteFeed", () => {
    it("handles 204 no content", async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, status: 204 });
      const result = await client.deleteFeed("feed1");
      expect(result).toBeUndefined();
    });
  });

  describe("checkConnection", () => {
    it("posts the selected provider and model", async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({
          kind: "llm",
          provider: "openai",
          model: "gpt-5-mini",
          message: "gpt-5-mini is wired and reachable.",
        }),
      });

      const result = await client.checkConnection({
        kind: "llm",
        provider: "openai",
        model: "gpt-5-mini",
        openai_api_key: "sk-test",
      });

      expect(mockFetch).toHaveBeenCalledWith(
        "http://localhost:8073/api/settings/check-connection",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({
            kind: "llm",
            provider: "openai",
            model: "gpt-5-mini",
            openai_api_key: "sk-test",
          }),
        }),
      );
      expect(result.model).toBe("gpt-5-mini");
    });
  });

  describe("error handling", () => {
    it("throws ApiError on 404", async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 404,
        statusText: "Not Found",
        text: async () => '{"detail":"Not found"}',
      });
      try {
        await client.getDocument("nonexistent");
        expect.fail("Should have thrown");
      } catch (e) {
        expect(e).toBeInstanceOf(ApiError);
        expect((e as ApiError).status).toBe(404);
      }
    });

    it("throws ApiError on 500", async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 500,
        statusText: "Internal Server Error",
        text: async () => "crash",
      });
      await expect(client.listDocuments()).rejects.toThrow(ApiError);
    });
  });
});
