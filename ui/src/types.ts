export type RoleName = 'admin' | 'support' | 'user' | string

export interface AuthResponse {
  access_token: string
  token_type: string
  username: string
  roles: string[]
}

export interface QueryMetadata {
  product?: string
  version?: string
  tier?: string
  language?: string
  tags?: string[]
  tenant_id?: string
}

export interface QueryResponse {
  answer: string
  sources: string[]
  confidence: number
  cache_hit: boolean
  request_id?: string
  session_id: string
}

export interface HistoryMessage {
  session_id: string
  request_id: string
  role: 'user' | 'assistant' | string
  content: string
  created_at: string
}

export interface HistoryResponse {
  items: HistoryMessage[]
  total: number
}

export interface FeedbackResponse {
  status: string
  updated: boolean
}

export interface AdminStats {
  active_users: number
  resolved_queries: number
  cache_hit_rate: number
  open_escalations: number
}

export interface AdminUserDetail {
  id: number
  username: string
  active: boolean
  tenant_id?: number
}

export interface AdminQueryDetail {
  request_id: string
  session_id?: string
  username: string
  resolved: boolean
  cache_hit: boolean
  created_at: string
}

export interface AdminEscalationDetail {
  request_id: string
  username: string
  reason?: string
  status: string
  created_at: string
}

export interface AdminUserDetailResponse {
  items: AdminUserDetail[]
  total: number
}

export interface AdminQueryDetailResponse {
  items: AdminQueryDetail[]
  total: number
}

export interface AdminEscalationDetailResponse {
  items: AdminEscalationDetail[]
  total: number
}

export interface AdminActivityItem {
  id: number
  username: string
  event_type: string
  description: string
  created_at: string
}

export interface AdminActivityResponse {
  items: AdminActivityItem[]
  total: number
}

export interface IngestionResponse {
  source: string
  chunks: number
  status: string
}

export type IngestionMetadata = Record<string, string | number | boolean | string[]>

export interface DiagnosticsResponse {
  database: string
  knowledge_documents: number
  knowledge_chunks: number
}

export interface RcaRecordResponse {
  id: number
  symptom: string
  root_cause: string
  resolution: string
  product?: string
  version?: string
  tags?: string[]
  tenant_id?: string
  created_at: string
}
