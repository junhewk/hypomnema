import type {
  Document,
  DocumentDetail,
  DocumentWithEngrams,
  Engram,
  EngramDetail,
  Edge,
  FeedSource,
  ScoredDocument,
  PaginatedList,
  ProjectionPoint,
  Cluster,
  GapRegion,
  VizEdge,
  AppSettings,
  SettingsUpdatePayload,
  ProvidersResponse,
  HealthStatus,
  SetupPayload,
  ChangeEmbeddingPayload,
  EmbeddingChangeStatus,
  ConnectivityCheckPayload,
  ConnectivityCheckResponse,
  RelatedDocument,
} from "./types";

const DEFAULT_BASE_URL = "http://localhost:8073";
const AUTO_BASE_URL = "auto";

function inferBaseUrl(): string {
  if (typeof window !== "undefined") {
    const port =
      (typeof process !== "undefined" && process.env.NEXT_PUBLIC_API_PORT) || "8073";
    return `${window.location.protocol}//${window.location.hostname}:${port}`;
  }
  return DEFAULT_BASE_URL;
}

function resolveBaseUrl(baseUrl?: string): string {
  if (baseUrl !== undefined) {
    return baseUrl;
  }
  if (typeof process !== "undefined" && process.env.NEXT_PUBLIC_API_URL !== undefined) {
    if (process.env.NEXT_PUBLIC_API_URL === AUTO_BASE_URL) {
      return inferBaseUrl();
    }
    // Empty string means same-origin (static serving / Docker mode)
    return process.env.NEXT_PUBLIC_API_URL;
  }
  return inferBaseUrl();
}

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
    this.baseUrl = resolveBaseUrl(baseUrl);
  }

  private async request<T>(
    path: string,
    options: RequestInit = {},
  ): Promise<T> {
    const url = `${this.baseUrl}${path}`;
    const isFormData = options.body instanceof FormData;
    const headers: HeadersInit = {
      ...(isFormData ? {} : { "Content-Type": "application/json" }),
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

  async createScribble(text: string, title?: string, draft?: boolean): Promise<Document> {
    return this.request("/api/documents/scribbles", {
      method: "POST",
      body: JSON.stringify({ text, title, ...(draft ? { draft: true } : {}) }),
    });
  }

  async uploadFile(file: File): Promise<Document> {
    const formData = new FormData();
    formData.append("file", file);
    return this.request("/api/documents/files", {
      method: "POST",
      body: formData,
    });
  }

  async listDocuments(days = 14): Promise<DocumentWithEngrams[]> {
    return this.request(`/api/documents?days=${days}`);
  }

  async listDrafts(): Promise<Document[]> {
    return this.request("/api/documents/drafts");
  }

  async getDocumentCount(): Promise<{ total: number }> {
    return this.request("/api/documents/count");
  }

  async getDocument(id: string): Promise<DocumentDetail> {
    return this.request(`/api/documents/${id}`);
  }

  async getRelatedDocuments(id: string): Promise<RelatedDocument[]> {
    return this.request(`/api/documents/${id}/related`);
  }

  async updateDocument(
    id: string,
    updates: { text?: string; title?: string },
  ): Promise<Document> {
    return this.request(`/api/documents/${id}`, {
      method: "PATCH",
      body: JSON.stringify(updates),
    });
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

  async getVizEdges(): Promise<VizEdge[]> {
    return this.request("/api/viz/edges");
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

  async getSettings(): Promise<AppSettings> {
    return this.request("/api/settings");
  }

  async updateSettings(updates: SettingsUpdatePayload): Promise<AppSettings> {
    return this.request("/api/settings", {
      method: "PUT",
      body: JSON.stringify(updates),
    });
  }

  async getProviders(): Promise<ProvidersResponse> {
    return this.request("/api/settings/providers");
  }

  async checkHealth(): Promise<HealthStatus> {
    return this.request("/api/health");
  }

  async completeSetup(payload: SetupPayload): Promise<AppSettings> {
    return this.request("/api/settings/setup", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  async checkConnection(payload: ConnectivityCheckPayload): Promise<ConnectivityCheckResponse> {
    return this.request("/api/settings/check-connection", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  async changeEmbeddingProvider(payload: ChangeEmbeddingPayload): Promise<EmbeddingChangeStatus> {
    return this.request("/api/settings/change-embedding", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  async getEmbeddingChangeStatus(): Promise<EmbeddingChangeStatus> {
    return this.request("/api/settings/embedding-status");
  }
}

export const api = new ApiClient();
