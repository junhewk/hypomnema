export type SourceType = "scribble" | "file" | "feed";
export type SearchMode = "documents" | "knowledge";
export type FeedType = "rss" | "scrape" | "youtube";
export type Predicate =
  | "contradicts"
  | "supports"
  | "extends"
  | "provides_methodology_for"
  | "is_example_of"
  | "is_prerequisite_for"
  | "generalizes"
  | "specializes"
  | "is_analogous_to"
  | "critiques"
  | "applies_to"
  | "derives_from";

export interface Document {
  id: string;
  source_type: SourceType;
  title: string | null;
  text: string;
  mime_type: string | null;
  source_uri: string | null;
  metadata: Record<string, unknown> | null;
  triaged: number;
  processed: number;
  tidy_title: string | null;
  tidy_text: string | null;
  created_at: string;
  updated_at: string;
}

export interface Engram {
  id: string;
  canonical_name: string;
  concept_hash: string;
  description: string | null;
  created_at: string;
}

export interface Edge {
  id: string;
  source_engram_id: string;
  target_engram_id: string;
  predicate: Predicate;
  confidence: number;
  source_document_id: string | null;
  created_at: string;
}

export interface FeedSource {
  id: string;
  name: string;
  feed_type: FeedType;
  url: string;
  schedule: string;
  active: boolean;
  last_fetched: string | null;
  created_at: string;
}

export interface Projection {
  engram_id: string;
  x: number;
  y: number;
  z: number;
  cluster_id: number | null;
  updated_at: string;
}

export interface DocumentDetail extends Document {
  engrams: Engram[];
}
export interface EngramDetail extends Engram {
  edges: Edge[];
  documents: Document[];
}
export interface ScoredDocument extends Document {
  score: number;
}
export interface PaginatedList<T> {
  items: T[];
  total: number;
  offset: number;
  limit: number;
}
export interface ProjectionPoint {
  engram_id: string;
  canonical_name: string;
  x: number;
  y: number;
  z: number;
  cluster_id: number | null;
}
export interface Cluster {
  cluster_id: number;
  label: string | null;
  engram_count: number;
  centroid_x: number;
  centroid_y: number;
  centroid_z: number;
}
export interface GapRegion {
  x: number;
  y: number;
  z: number;
  radius: number;
  neighboring_clusters: number[];
}
export type VizEdge = Pick<Edge, "source_engram_id" | "target_engram_id" | "predicate" | "confidence">;

export interface AppSettings {
  llm_provider: string;
  llm_model: string;
  anthropic_api_key: string;
  google_api_key: string;
  openai_api_key: string;
  ollama_base_url: string;
  openai_base_url: string;
  embedding_provider: string;
  embedding_model: string;
  embedding_dim: number;
}

export interface SettingsUpdatePayload {
  llm_provider?: string;
  llm_model?: string;
  anthropic_api_key?: string;
  google_api_key?: string;
  openai_api_key?: string;
  ollama_base_url?: string;
  openai_base_url?: string;
}

export interface ModelOption {
  id: string;
  name: string;
}

export interface ProviderInfo {
  id: string;
  name: string;
  requires_key: boolean;
  default_model: string;
  models: ModelOption[];
}

export interface EmbeddingProviderInfo {
  id: string;
  name: string;
  default_model: string;
  default_dimension: number;
  requires_key: boolean;
}

export interface ProvidersResponse {
  llm: ProviderInfo[];
  embedding: EmbeddingProviderInfo[];
}

export interface HealthStatus {
  status: string;
  needs_setup: boolean;
  mode: "local" | "server" | "desktop";
}

export interface ChangeEmbeddingPayload {
  embedding_provider: "local" | "openai" | "google";
  openai_api_key?: string;
  google_api_key?: string;
  openai_base_url?: string;
}

export interface ConnectivityCheckPayload {
  kind: "llm" | "embedding";
  provider: string;
  model?: string;
  anthropic_api_key?: string;
  google_api_key?: string;
  openai_api_key?: string;
  ollama_base_url?: string;
  openai_base_url?: string;
}

export interface ConnectivityCheckResponse {
  kind: "llm" | "embedding";
  provider: string;
  model: string;
  message: string;
  dimension?: number | null;
}

export interface EmbeddingChangeStatus {
  status: "idle" | "in_progress" | "complete" | "failed";
  total: number;
  processed: number;
  error?: string | null;
}

export interface SetupPayload {
  embedding_provider: "local" | "openai" | "google";
  llm_provider?: string;
  llm_model?: string;
  anthropic_api_key?: string;
  google_api_key?: string;
  openai_api_key?: string;
  ollama_base_url?: string;
  openai_base_url?: string;
}
