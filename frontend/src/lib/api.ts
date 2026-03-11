import type {
  Document,
  DocumentDetail,
  Engram,
  EngramDetail,
  Edge,
  FeedSource,
  ScoredDocument,
  PaginatedList,
  ProjectionPoint,
  Cluster,
  GapRegion,
} from "./types";

const DEFAULT_BASE_URL = "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    public status: number,
    public statusText: string,
    public body: string,
  ) {
    super(`API Error ${status}: ${statusText}`);
    this.name = "ApiError";
  }
}

export class ApiClient {
  private baseUrl: string;

  constructor(baseUrl?: string) {
    this.baseUrl =
      baseUrl ??
      (typeof process !== "undefined"
        ? (process.env.NEXT_PUBLIC_API_URL ?? DEFAULT_BASE_URL)
        : DEFAULT_BASE_URL);
  }

  private async request<T>(
    path: string,
    options: RequestInit = {},
  ): Promise<T> {
    const url = `${this.baseUrl}${path}`;
    const headers: HeadersInit = {
      "Content-Type": "application/json",
      ...options.headers,
    };
    const response = await fetch(url, { ...options, headers });
    if (!response.ok) {
      const errorBody = await response.text().catch(() => "");
      throw new ApiError(response.status, response.statusText, errorBody);
    }
    if (response.status === 204) return undefined as T;
    return response.json() as Promise<T>;
  }

  async createScribble(text: string, title?: string): Promise<Document> {
    return this.request("/api/documents/scribbles", {
      method: "POST",
      body: JSON.stringify({ text, title }),
    });
  }

  async uploadFile(file: File): Promise<Document> {
    const formData = new FormData();
    formData.append("file", file);
    return this.request("/api/documents/files", {
      method: "POST",
      body: formData,
      headers: {},
    });
  }

  async listDocuments(
    offset = 0,
    limit = 20,
  ): Promise<PaginatedList<Document>> {
    return this.request(`/api/documents?offset=${offset}&limit=${limit}`);
  }

  async getDocument(id: string): Promise<DocumentDetail> {
    return this.request(`/api/documents/${id}`);
  }

  async listEngrams(
    offset = 0,
    limit = 20,
  ): Promise<PaginatedList<Engram>> {
    return this.request(`/api/engrams?offset=${offset}&limit=${limit}`);
  }

  async getEngram(id: string): Promise<EngramDetail> {
    return this.request(`/api/engrams/${id}`);
  }

  async getEngramCluster(id: string): Promise<Document[]> {
    return this.request(`/api/engrams/${id}/cluster`);
  }

  async searchDocuments(query: string): Promise<ScoredDocument[]> {
    return this.request(
      `/api/search/documents?q=${encodeURIComponent(query)}`,
    );
  }

  async searchKnowledge(query: string): Promise<Edge[]> {
    return this.request(
      `/api/search/knowledge?q=${encodeURIComponent(query)}`,
    );
  }

  async getProjections(): Promise<ProjectionPoint[]> {
    return this.request("/api/viz/projections");
  }

  async getClusters(): Promise<Cluster[]> {
    return this.request("/api/viz/clusters");
  }

  async getGaps(): Promise<GapRegion[]> {
    return this.request("/api/viz/gaps");
  }

  async createFeed(
    feed: Omit<FeedSource, "id" | "created_at" | "last_fetched">,
  ): Promise<FeedSource> {
    return this.request("/api/feeds", {
      method: "POST",
      body: JSON.stringify(feed),
    });
  }

  async listFeeds(): Promise<FeedSource[]> {
    return this.request("/api/feeds");
  }

  async updateFeed(
    id: string,
    updates: Partial<FeedSource>,
  ): Promise<FeedSource> {
    return this.request(`/api/feeds/${id}`, {
      method: "PATCH",
      body: JSON.stringify(updates),
    });
  }

  async deleteFeed(id: string): Promise<void> {
    return this.request(`/api/feeds/${id}`, { method: "DELETE" });
  }
}

export const api = new ApiClient();
