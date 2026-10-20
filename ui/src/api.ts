import type { AdminActivityResponse, AdminEscalationDetailResponse, AdminQueryDetailResponse, AdminStats, AdminUserDetailResponse, AuthResponse, DiagnosticsResponse, FeedbackResponse, HistoryResponse, IngestionMetadata, IngestionResponse, QueryMetadata, QueryResponse, RcaRecordResponse } from './types'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'

async function request<T>(
  path: string,
  options: RequestInit = {},
  token?: string,
): Promise<T> {
  const headers = new Headers(options.headers ?? {})
  headers.set('Content-Type', 'application/json')

  if (token) {
    headers.set('Authorization', `Bearer ${token}`)
  }

  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
  })

  if (!response.ok) {
    const body = await response.text()
    let message = body
    try {
      const parsed = JSON.parse(body) as { detail?: string; message?: string }
      message = parsed.detail || parsed.message || body
    } catch {
      // Preserve non-JSON server errors as plain text.
    }
    throw new Error(message || `Request failed: ${response.status}`)
  }

  if (response.status === 204) {
    return undefined as T
  }

  return response.json() as Promise<T>
}

export async function login(username: string, password: string): Promise<AuthResponse> {
  return request<AuthResponse>('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  })
}

export async function logout(token: string): Promise<void> {
  await request<{ status: string }>('/auth/logout', { method: 'POST' }, token)
}

export async function submitQuery(
  token: string,
  question: string,
  metadata?: QueryMetadata,
  sessionId?: string,
): Promise<QueryResponse> {
  return request<QueryResponse>('/query', {
    method: 'POST',
    body: JSON.stringify({
      question,
      session_id: sessionId,
      metadata,
    }),
  }, token)
}

export async function submitFeedback(
  token: string,
  requestId: string,
  helpful: boolean,
  comment?: string,
): Promise<FeedbackResponse> {
  return request<FeedbackResponse>('/feedback', {
    method: 'POST',
    body: JSON.stringify({
      request_id: requestId,
      helpful,
      comment,
    }),
  }, token)
}

export function getHistory(token: string, sessionId?: string): Promise<HistoryResponse> {
  const query = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : ''
  return request<HistoryResponse>(`/history${query}`, {}, token)
}

export async function createRcaRecord(
  token: string,
  payload: {
    symptom: string
    root_cause: string
    resolution: string
    product?: string
    version?: string
    tags?: string[]
    tenant_id?: string
  },
): Promise<RcaRecordResponse> {
  return request<RcaRecordResponse>('/rca', {
    method: 'POST',
    body: JSON.stringify(payload),
  }, token)
}

export function getAdminStats(token: string): Promise<AdminStats> {
  return request<AdminStats>('/admin/stats', {}, token)
}

export function getAdminActiveUsers(token: string): Promise<AdminUserDetailResponse> {
  return request<AdminUserDetailResponse>('/admin/stats/active-users', {}, token)
}

export function getAdminResolvedQueries(token: string): Promise<AdminQueryDetailResponse> {
  return request<AdminQueryDetailResponse>('/admin/stats/resolved-queries', {}, token)
}

export function getAdminCacheHits(token: string): Promise<AdminQueryDetailResponse> {
  return request<AdminQueryDetailResponse>('/admin/stats/cache-hits', {}, token)
}

export function getAdminOpenEscalations(token: string): Promise<AdminEscalationDetailResponse> {
  return request<AdminEscalationDetailResponse>('/admin/stats/open-escalations', {}, token)
}

export function getAdminActivity(token: string, limit = 25, offset = 0): Promise<AdminActivityResponse> {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) })
  return request<AdminActivityResponse>(`/admin/activity?${params.toString()}`, {}, token)
}

export function ingestKnowledge(token: string, source: string, metadata?: IngestionMetadata): Promise<IngestionResponse> {
  return request<IngestionResponse>('/admin/ingest', {
    method: 'POST',
    body: JSON.stringify({ source, metadata }),
  }, token)
}

export function syncDocuments(token: string, source: string, metadata?: IngestionMetadata): Promise<IngestionResponse> {
  return request<IngestionResponse>('/admin/sync', {
    method: 'POST',
    body: JSON.stringify({ source, metadata }),
  }, token)
}

export function runDiagnostics(token: string): Promise<DiagnosticsResponse> {
  return request<DiagnosticsResponse>('/admin/diagnostics', {}, token)
}
