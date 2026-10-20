import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { Navigate, Route, Routes, useNavigate } from 'react-router-dom'
import './App.css'
import { createRcaRecord, getAdminActiveUsers, getAdminActivity, getAdminCacheHits, getAdminOpenEscalations, getAdminResolvedQueries, getAdminStats, getHistory, ingestKnowledge, login, logout, runDiagnostics, submitFeedback, submitQuery, syncDocuments } from './api'
import { clearSession, loadSession, saveSession, type SessionUser } from './auth'
import type { AdminActivityItem, AdminEscalationDetail, AdminQueryDetail, AdminStats, AdminUserDetail, AuthResponse, HistoryMessage, QueryResponse } from './types'

const DEFAULT_METADATA = {
  product: 'MyApp',
  version: '1.2.3',
  tier: 'pro',
  language: 'en',
  tags: ['billing', 'api'],
}

const ACTIVITY_PAGE_SIZE = 25

type DashboardRole = 'admin' | 'support' | 'user'

function getPreferredRole(roles: string[] = []): DashboardRole {
  if (roles.includes('admin')) return 'admin'
  if (roles.includes('support')) return 'support'
  return 'user'
}

function getDashboardPath(roles: string[] = []) {
  return `/dashboard/${getPreferredRole(roles)}`
}

function DashboardShell({
  session,
  title,
  subtitle,
  navItems,
  children,
}: {
  session: SessionUser
  title: string
  subtitle: string
  navItems: { href: string; label: string }[]
  children: React.ReactNode
}) {
  const navigate = useNavigate()

  return (
    <div className="workspace-shell">
      <aside className="sidebar">
        <div className="sidebar-header">
          <div className="brand-badge">AI</div>
          <div>
            <p className="eyebrow">Multi-agent</p>
            <h2>{title}</h2>
          </div>
        </div>

        <div className="user-box">
          <strong>{session.username}</strong>
          <span>{session.roles.join(', ')}</span>
        </div>

        <nav className="nav-stack">
          {navItems.map((item) => (
            <a key={item.href} href={item.href}>
              {item.label}
            </a>
          ))}
          <button
            type="button"
            className="logout-button"
            onClick={async () => {
              try {
                await logout(session.token)
              } catch {
                // Clear local credentials even if the server is unreachable.
              } finally {
                clearSession()
                navigate('/login')
              }
            }}
          >
            Sign out
          </button>
        </nav>
      </aside>

      <main className="main-panel">
        <section className="panel hero-panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow muted">{subtitle}</p>
              <h3>{title}</h3>
            </div>
            <span className="chip success">{getPreferredRole(session.roles)}</span>
          </div>
        </section>
        {children}
      </main>
    </div>
  )
}

function ProtectedRoute({ session, requiredRole }: { session: SessionUser | null; requiredRole?: DashboardRole }) {
  if (!session) {
    return <Navigate to="/login" replace />
  }

  if (requiredRole && getPreferredRole(session.roles) !== requiredRole) {
    return <Navigate to={getDashboardPath(session.roles)} replace />
  }

  return <Dashboard session={session} />
}

function renderInlineMarkdown(text: string): React.ReactNode[] {
  const pattern = /(`[^`]+`|\*\*[^*]+\*\*|__[^_]+__|\*[^*]+\*|_[^_]+_|\[[^\]]+\]\([^\)]+\)|https?:\/\/[^\s]+|\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b)/g
  const parts: React.ReactNode[] = []
  let lastIndex = 0

  for (const match of text.matchAll(pattern)) {
    const index = match.index ?? 0
    if (index > lastIndex) {
      parts.push(text.slice(lastIndex, index))
    }

    const token = match[0]
    if (token.startsWith('**') || token.startsWith('__')) {
      parts.push(<strong key={`${index}-bold`}>{token.slice(2, -2)}</strong>)
    } else if (token.startsWith('*') || token.startsWith('_')) {
      parts.push(<em key={`${index}-italic`}>{token.slice(1, -1)}</em>)
    } else if (token.startsWith('`')) {
      parts.push(<code key={`${index}-code`}>{token.slice(1, -1)}</code>)
    } else if (token.startsWith('[')) {
      const linkMatch = token.match(/^\[([^\]]+)\]\((https?:\/\/[^\)]+)\)$/)
      if (linkMatch) {
        parts.push(
          <a key={`${index}-link`} href={linkMatch[2]} target="_blank" rel="noreferrer">
            {linkMatch[1]}
          </a>,
        )
      } else {
        parts.push(token)
      }
    } else if (/^https?:\/\//.test(token)) {
      parts.push(
        <a key={`${index}-url`} href={token} target="_blank" rel="noreferrer">
          {token}
        </a>,
      )
    } else {
      parts.push(token)
    }

    lastIndex = index + token.length
  }

  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex))
  }

  return parts
}

function renderAnswerContent(answer: string): React.ReactNode {
  const normalized = answer.replace(/\r\n/g, '\n').replace(/\n{3,}/g, '\n\n').trim()
  const lines = normalized.split('\n')
  const nodes: React.ReactNode[] = []
  let listType: 'ul' | 'ol' | null = null
  let listItems: string[] = []
  let paragraphLines: string[] = []

  const flushParagraph = () => {
    if (!paragraphLines.length) return
    nodes.push(<p key={`paragraph-${nodes.length}`} className="answer-paragraph">{renderInlineMarkdown(paragraphLines.join(' '))}</p>)
    paragraphLines = []
  }

  const flushList = () => {
    if (!listItems.length || !listType) return
    const ListTag = listType
    nodes.push(
      <ListTag key={`list-${nodes.length}`} className="answer-list">
        {listItems.map((item, index) => (
          <li key={`${listType}-${index}`}>{renderInlineMarkdown(item)}</li>
        ))}
      </ListTag>,
    )
    listItems = []
    listType = null
  }

  const pushTextBlock = (text: string) => {
    const trimmed = text.trim()
    if (!trimmed) return

    if (/^#{1,3}\s+/.test(trimmed)) {
      const level = Math.min(3, Math.max(1, trimmed.match(/^#+/)?.[0].length ?? 1))
      const headingText = trimmed.replace(/^#{1,3}\s+/, '')
      const headingMap = { 1: 'h1', 2: 'h2', 3: 'h3' } as const
      const HeadingTag = headingMap[level as keyof typeof headingMap]
      nodes.push(<HeadingTag key={`heading-${nodes.length}`} className="answer-heading">{renderInlineMarkdown(headingText)}</HeadingTag>)
      return
    }

    if (/^[-*]\s+/.test(trimmed)) {
      flushParagraph()
      const itemText = trimmed.replace(/^[-*]\s+/, '')
      if (listType !== 'ul') {
        listType = 'ul'
        listItems = []
      }
      listItems.push(itemText)
      return
    }

    if (/^\d+\.\s+/.test(trimmed)) {
      flushParagraph()
      const itemText = trimmed.replace(/^\d+\.\s+/, '')
      if (listType !== 'ol') {
        listType = 'ol'
        listItems = []
      }
      listItems.push(itemText)
      return
    }

    if (/^```/.test(trimmed)) {
      flushParagraph()
      flushList()
      const codeLines: string[] = []
      let index = lines.indexOf(trimmed)
      if (index >= 0) {
        for (let i = index + 1; i < lines.length; i++) {
          const line = lines[i]
          if (line.trim().startsWith('```')) {
            break
          }
          codeLines.push(line)
        }
      }
      nodes.push(<pre key={`code-${nodes.length}`} className="answer-code"><code>{codeLines.join('\n')}</code></pre>)
      return
    }

    paragraphLines.push(trimmed)
  }

  lines.forEach((line) => {
    if (!line.trim()) {
      flushParagraph()
      flushList()
      return
    }

    const trimmed = line.trim()
    if (listType && !(/^(?:[-*]|\d+\.)\s+/.test(trimmed))) {
      flushList()
    }

    pushTextBlock(trimmed)
  })

  flushParagraph()
  flushList()

  return nodes.length ? nodes : [<p key="empty-answer" className="answer-paragraph">{answer}</p>]
}

function Dashboard({ session }: { session: SessionUser }) {
  const role = getPreferredRole(session.roles)

  if (role === 'admin') {
    return <AdminDashboard session={session} />
  }

  if (role === 'support') {
    return <SupportDashboard session={session} />
  }

  return <UserDashboard session={session} />
}

function AdminDashboard({ session }: { session: SessionUser }) {
  const [stats, setStats] = useState<AdminStats | null>(null)
  const [statsError, setStatsError] = useState('')
  const [source, setSource] = useState('')
  const [ingestionMessage, setIngestionMessage] = useState('')
  const [isWorking, setIsWorking] = useState(false)
  const [selectedMetric, setSelectedMetric] = useState<'active-users' | 'resolved-queries' | 'cache-hits' | 'open-escalations' | null>(null)
  const [detailRows, setDetailRows] = useState<Array<AdminUserDetail | AdminQueryDetail | AdminEscalationDetail>>([])
  const [detailTotal, setDetailTotal] = useState(0)
  const [detailError, setDetailError] = useState('')
  const [isLoadingDetails, setIsLoadingDetails] = useState(false)
  const [activity, setActivity] = useState<AdminActivityItem[]>([])
  const [activityTotal, setActivityTotal] = useState(0)
  const [activityPage, setActivityPage] = useState(1)
  const [activityError, setActivityError] = useState('')

  useEffect(() => {
    getAdminStats(session.token)
      .then(setStats)
      .catch((error) => setStatsError(error instanceof Error ? error.message : 'Unable to load operational stats'))
  }, [session.token])

  useEffect(() => {
    let isCurrent = true
    getAdminActivity(session.token, ACTIVITY_PAGE_SIZE, (activityPage - 1) * ACTIVITY_PAGE_SIZE)
      .then((response) => {
        if (!isCurrent) return
        const lastActivityPage = Math.max(1, Math.ceil(response.total / ACTIVITY_PAGE_SIZE))
        if (activityPage > lastActivityPage) {
          setActivityPage(lastActivityPage)
          return
        }
        setActivity(response.items)
        setActivityTotal(response.total)
      })
      .catch((error) => {
        if (isCurrent) setActivityError(error instanceof Error ? error.message : 'Unable to load recent activity')
      })
    return () => {
      isCurrent = false
    }
  }, [activityPage, session.token])

  const goToActivityPage = (page: number) => {
    setActivityError('')
    setActivityPage(page)
  }

  const handleIngestion = async (action: 'ingest' | 'sync' | 'diagnostics') => {
    setIsWorking(true)
    setIngestionMessage('')
    try {
      if (action === 'diagnostics') {
        const result = await runDiagnostics(session.token)
        setIngestionMessage(`Diagnostics passed: database ${result.database}, ${result.knowledge_chunks} knowledge chunks across ${result.knowledge_documents} stored entries.`)
      } else {
        const result = action === 'ingest'
          ? await ingestKnowledge(session.token, source)
          : await syncDocuments(session.token, source)
        setIngestionMessage(`${result.status}: ${result.chunks} chunks stored from ${result.source}.`)
        setStats(await getAdminStats(session.token))
      }
      goToActivityPage(1)
      if (activityPage === 1) {
        const activityResponse = await getAdminActivity(session.token, ACTIVITY_PAGE_SIZE, 0)
        setActivity(activityResponse.items)
        setActivityTotal(activityResponse.total)
        setActivityError('')
      }
    } catch (error) {
      setIngestionMessage(error instanceof Error ? error.message : 'Admin operation failed')
    } finally {
      setIsWorking(false)
    }
  }

  const loadMetricDetails = async (metric: NonNullable<typeof selectedMetric>) => {
    setSelectedMetric(metric)
    setDetailRows([])
    setDetailTotal(0)
    setDetailError('')
    setIsLoadingDetails(true)
    try {
      const response = metric === 'active-users'
        ? await getAdminActiveUsers(session.token)
        : metric === 'resolved-queries'
          ? await getAdminResolvedQueries(session.token)
          : metric === 'cache-hits'
            ? await getAdminCacheHits(session.token)
            : await getAdminOpenEscalations(session.token)
      setDetailRows(response.items)
      setDetailTotal(response.total)
    } catch (error) {
      setDetailError(error instanceof Error ? error.message : 'Unable to load metric details')
    } finally {
      setIsLoadingDetails(false)
    }
  }

  const detailTitle = selectedMetric === 'active-users'
    ? 'Active users'
    : selectedMetric === 'resolved-queries'
      ? 'Resolved queries'
      : selectedMetric === 'cache-hits'
        ? 'Cache hits'
        : 'Open escalations'
    const activityPageCount = Math.max(1, Math.ceil(activityTotal / ACTIVITY_PAGE_SIZE))
    const activityPages = Array.from({ length: activityPageCount }, (_, index) => index + 1)
  return (
    <DashboardShell
      session={session}
      title="Admin Console"
      subtitle="Operations overview"
      navItems={[
        { href: '#overview', label: 'Overview' },
        { href: '#ingest', label: 'Ingest' },
        { href: '#activity', label: 'Activity' },
      ]}
    >
      <section id="overview" className="panel">
        <div className="panel-header">
          <h3>Operational stats</h3>
        </div>

        <div className="stat-grid">
          <button type="button" className={`stat-card stat-card-button accent ${selectedMetric === 'active-users' ? 'selected' : ''}`} onClick={() => loadMetricDetails('active-users')} aria-pressed={selectedMetric === 'active-users'}>
            <span>Active users</span>
            <strong>{stats ? stats.active_users : '—'}</strong>
          </button>
          <button type="button" className={`stat-card stat-card-button ${selectedMetric === 'resolved-queries' ? 'selected' : ''}`} onClick={() => loadMetricDetails('resolved-queries')} aria-pressed={selectedMetric === 'resolved-queries'}>
            <span>Resolved queries</span>
            <strong>{stats ? stats.resolved_queries : '—'}</strong>
          </button>
          <button type="button" className={`stat-card stat-card-button ${selectedMetric === 'cache-hits' ? 'selected' : ''}`} onClick={() => loadMetricDetails('cache-hits')} aria-pressed={selectedMetric === 'cache-hits'}>
            <span>Cache hits</span>
            <strong>{stats ? `${stats.cache_hit_rate}%` : '—'}</strong>
          </button>
          <button type="button" className={`stat-card stat-card-button ${selectedMetric === 'open-escalations' ? 'selected' : ''}`} onClick={() => loadMetricDetails('open-escalations')} aria-pressed={selectedMetric === 'open-escalations'}>
            <span>Open escalations</span>
            <strong>{stats ? stats.open_escalations : '—'}</strong>
          </button>
        </div>
        {statsError ? <div className="error-box" role="alert">{statsError}</div> : null}
        {selectedMetric ? (
          <div className="metric-detail" aria-live="polite">
            <div className="panel-header">
              <h4>{detailTitle}</h4>
              <span className="chip neutral">{detailTotal} total</span>
            </div>
            {isLoadingDetails ? <p className="detail-message">Loading details...</p> : null}
            {detailError ? <div className="error-box" role="alert">{detailError}</div> : null}
            {!isLoadingDetails && !detailError && detailRows.length === 0 ? <p className="detail-message">No records found.</p> : null}
            {!isLoadingDetails && !detailError && detailRows.length > 0 ? (
              <div className="detail-table-wrap">
                <table className="detail-table">
                  <thead>
                    <tr>
                      <th>Record</th>
                      <th>User</th>
                      <th>Status</th>
                      <th>Created</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detailRows.map((row) => {
                      const queryRow = 'request_id' in row && 'resolved' in row ? row : null
                      const escalationRow = 'request_id' in row && 'reason' in row ? row : null
                      return (
                        <tr key={'id' in row ? row.id : `${row.request_id}-${row.created_at}`}>
                          <td>{'id' in row ? `User #${row.id}` : row.request_id}</td>
                          <td>{row.username}</td>
                          <td>{'active' in row ? 'Active' : queryRow ? (queryRow.cache_hit ? 'Cache hit' : 'Resolved') : escalationRow?.status}</td>
                          <td>{'created_at' in row ? new Date(row.created_at).toLocaleString() : 'Current'}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            ) : null}
          </div>
        ) : null}
      </section>

      <section id="ingest" className="panel">
        <div className="panel-header">
          <h3>Knowledge ingestion</h3>
        </div>

        <input value={source} onChange={(event) => setSource(event.target.value)} placeholder="File path or URL" disabled={isWorking} />
        <div className="action-grid">
          <button type="button" onClick={() => handleIngestion('ingest')} disabled={isWorking || !source}>Ingest knowledge base</button>
          <button type="button" className="secondary-button" onClick={() => handleIngestion('sync')} disabled={isWorking || !source}>Sync documents</button>
          <button type="button" className="secondary-button" onClick={() => handleIngestion('diagnostics')} disabled={isWorking}>Run diagnostics</button>
        </div>
        {ingestionMessage ? <div className="success-box" role="status">{ingestionMessage}</div> : null}
      </section>

      <section id="activity" className="panel">
        <div className="panel-header">
          <h3>Recent activity</h3>
        </div>

        <div className="activity-list">
          {activityError ? <div className="error-box" role="alert">{activityError}</div> : null}
          {!activityError && activity.length === 0 ? <p className="detail-message">No recent activity.</p> : null}
          {activity.map((entry) => (
            <div key={entry.id} className="activity-row">
              <div>
                <strong>{entry.username}</strong>
                <span>{entry.description}</span>
              </div>
              <small>{new Date(entry.created_at).toLocaleString()}</small>
            </div>
          ))}
        </div>
        {activityPageCount > 1 ? (
          <nav className="activity-pagination" aria-label="Recent activity pages">
            <button
              type="button"
              className="pagination-link"
              onClick={() => goToActivityPage(Math.max(1, activityPage - 1))}
              disabled={activityPage === 1}
            >
              Previous
            </button>
            {activityPages.map((page) => (
              <button
                key={page}
                type="button"
                className={`pagination-link ${activityPage === page ? 'selected' : ''}`}
                onClick={() => goToActivityPage(page)}
                aria-current={activityPage === page ? 'page' : undefined}
              >
                {page}
              </button>
            ))}
            <button
              type="button"
              className="pagination-link"
              onClick={() => goToActivityPage(Math.min(activityPageCount, activityPage + 1))}
              disabled={activityPage === activityPageCount}
            >
              Next
            </button>
          </nav>
        ) : null}
      </section>
    </DashboardShell>
  )
}

function SupportDashboard({ session }: { session: SessionUser }) {
  const [question, setQuestion] = useState('How do I fix a database connection error?')
  const [metadata, setMetadata] = useState(DEFAULT_METADATA)
  const [isQuerying, setIsQuerying] = useState(false)
  const [queryError, setQueryError] = useState('')
  const [queryResult, setQueryResult] = useState<QueryResponse | null>(null)
  const [history, setHistory] = useState<HistoryMessage[]>([])
  const [historyError, setHistoryError] = useState('')
  const [isLoadingHistory, setIsLoadingHistory] = useState(false)
  const [conversationId, setConversationId] = useState<string | undefined>(() => (
    localStorage.getItem(`support-conversation:${session.username}`) ?? undefined
  ))
  const [feedbackComment, setFeedbackComment] = useState('This answer was helpful.')
  const [feedbackHelpful, setFeedbackHelpful] = useState(true)
  const [feedbackState, setFeedbackState] = useState('')
  const [rcaForm, setRcaForm] = useState({
    symptom: 'Database connection timeout',
    root_cause: 'Connection pool exhaustion due to slow queries',
    resolution: 'Optimize slow queries and increase pool size',
    product: 'MyApp',
    version: '1.2.3',
    tags: 'database,performance',
  })

  const canManageRca = useMemo(
    () => session.roles.includes('admin') || session.roles.includes('support'),
    [session.roles],
  )

  useEffect(() => {
    let isCurrent = true
    setHistoryError('')
    if (!conversationId) {
      setHistory([])
      return () => {
        isCurrent = false
      }
    }

    setIsLoadingHistory(true)
    getHistory(session.token, conversationId)
      .then((response) => {
        if (isCurrent) setHistory(response.items)
      })
      .catch((error) => {
        if (isCurrent) setHistoryError(error instanceof Error ? error.message : 'Unable to load history')
      })
      .finally(() => {
        if (isCurrent) setIsLoadingHistory(false)
      })

    return () => {
      isCurrent = false
    }
  }, [conversationId, session.token])

  const handleQuery = async () => {
    setIsQuerying(true)
    setQueryError('')

    try {
      const response = await submitQuery(session.token, question, metadata, conversationId)
      setConversationId(response.session_id)
      localStorage.setItem(`support-conversation:${session.username}`, response.session_id)
      setQueryResult(response)
    } catch (error) {
      setQueryError(error instanceof Error ? error.message : 'Unable to query support')
    } finally {
      setIsQuerying(false)
    }
  }

  const handleFeedback = async () => {
    if (!queryResult?.request_id) return

    try {
      await submitFeedback(session.token, queryResult.request_id, feedbackHelpful, feedbackComment)
      setFeedbackState('Feedback submitted successfully.')
    } catch (error) {
      setFeedbackState(error instanceof Error ? error.message : 'Unable to submit feedback')
    }
  }

  const handleRca = async () => {
    try {
      await createRcaRecord(session.token, {
        symptom: rcaForm.symptom,
        root_cause: rcaForm.root_cause,
        resolution: rcaForm.resolution,
        product: rcaForm.product,
        version: rcaForm.version,
        tags: rcaForm.tags.split(',').map((item) => item.trim()).filter(Boolean),
      })
      setFeedbackState('RCA record created successfully.')
    } catch (error) {
      setFeedbackState(error instanceof Error ? error.message : 'Unable to create RCA')
    }
  }

  const handleMetadataChange = (field: keyof typeof DEFAULT_METADATA, value: string) => {
    setMetadata((current) => ({
      ...current,
      [field]: field === 'tags' ? value.split(',').map((item) => item.trim()).filter(Boolean) : value,
    }))
  }

  return (
    <DashboardShell
      session={session}
      title="Support Console"
      subtitle="Operations center"
      navItems={[
        { href: '#query', label: 'Query' },
        { href: '#history', label: 'History' },
        { href: '#rca', label: 'RCA' },
      ]}
    >
      <section id="query" className="panel">
        <div className="panel-header">
          <h3>Ask support</h3>
          <span className="chip success">Authenticated</span>
        </div>

        <textarea value={question} onChange={(event) => setQuestion(event.target.value)} rows={5} placeholder="Describe the issue" />

        <div className="meta-grid">
          <input value={metadata.product ?? ''} onChange={(event) => handleMetadataChange('product', event.target.value)} placeholder="Product" />
          <input value={metadata.version ?? ''} onChange={(event) => handleMetadataChange('version', event.target.value)} placeholder="Version" />
          <input value={metadata.tier ?? ''} onChange={(event) => handleMetadataChange('tier', event.target.value)} placeholder="Tier" />
          <input value={metadata.language ?? ''} onChange={(event) => handleMetadataChange('language', event.target.value)} placeholder="Language" />
          <input value={metadata.tags?.join(', ') ?? ''} onChange={(event) => handleMetadataChange('tags', event.target.value)} placeholder="Tags" className="wide" />
        </div>

        {queryError ? <div className="error-box">{queryError}</div> : null}

        <button type="button" onClick={handleQuery} disabled={isQuerying}>
          {isQuerying ? 'Running support workflow...' : 'Ask support'}
        </button>
      </section>

      <section id="history" className="panel">
        <div className="panel-header">
          <h3>Conversation history</h3>
          {history.length ? <span className="chip neutral">{history.length} messages</span> : null}
        </div>
        {historyError ? <div className="error-box">{historyError}</div> : null}
        {isLoadingHistory ? <p className="muted-text">Loading conversation history...</p> : null}
        {!isLoadingHistory && !historyError && !history.length ? <p className="muted-text">No conversation history yet.</p> : null}
        <div className="source-list">
          {history.map((message) => (
            <div key={`${message.request_id}-${message.role}`} className="source-card">
              <div className="source-title-row">
                <strong>{message.role === 'user' ? 'You' : 'Support'}</strong>
                <span className="chip neutral">{new Date(message.created_at).toLocaleString()}</span>
              </div>
              <p>{message.content}</p>
            </div>
          ))}
        </div>
      </section>

      {queryResult ? (
        <section id="response" className="panel answer-panel">
          <div className="panel-header">
            <h3>Answer</h3>
            <div className="badge-row">
              <span className="chip neutral">Confidence {queryResult.confidence}</span>
              <span className="chip warning">Cache hit: {queryResult.cache_hit ? 'yes' : 'no'}</span>
            </div>
          </div>

          <div className="answer-content">{renderAnswerContent(queryResult.answer)}</div>

          <div className="source-list">
            {queryResult.sources.map((source, index) => (
              <div key={`${source}-${index}`} className="source-card">
                <div className="source-title-row">
                  <strong>Source {index + 1}</strong>
                  <span className="chip neutral">Citation</span>
                </div>
                <p>
                  {source.startsWith('http') ? (
                    <a href={source} target="_blank" rel="noreferrer">{source}</a>
                  ) : (
                    source
                  )}
                </p>
              </div>
            ))}
          </div>

          <div className="feedback-block">
            <div className="panel-header compact">
              <h4>Feedback</h4>
            </div>
            <div className="inline-row">
              <label>
                <input type="checkbox" checked={feedbackHelpful} onChange={(event) => setFeedbackHelpful(event.target.checked)} />
                Helpful
              </label>
            </div>

            <textarea value={feedbackComment} onChange={(event) => setFeedbackComment(event.target.value)} rows={3} placeholder="Tell us how useful this answer was" />

            <button type="button" onClick={handleFeedback}>Submit feedback</button>
            {feedbackState ? <div className="success-box">{feedbackState}</div> : null}
          </div>
        </section>
      ) : null}

      {canManageRca ? (
        <section id="rca" className="panel">
          <div className="panel-header">
            <h3>Create RCA record</h3>
          </div>

          <div className="meta-grid">
            <input value={rcaForm.symptom} onChange={(event) => setRcaForm({ ...rcaForm, symptom: event.target.value })} placeholder="Symptom" />
            <input value={rcaForm.product} onChange={(event) => setRcaForm({ ...rcaForm, product: event.target.value })} placeholder="Product" />
            <input value={rcaForm.version} onChange={(event) => setRcaForm({ ...rcaForm, version: event.target.value })} placeholder="Version" />
            <input value={rcaForm.tags} onChange={(event) => setRcaForm({ ...rcaForm, tags: event.target.value })} placeholder="Tags" className="wide" />
          </div>

          <textarea value={rcaForm.root_cause} onChange={(event) => setRcaForm({ ...rcaForm, root_cause: event.target.value })} rows={3} placeholder="Root cause" />
          <textarea value={rcaForm.resolution} onChange={(event) => setRcaForm({ ...rcaForm, resolution: event.target.value })} rows={3} placeholder="Resolution" />

          <button type="button" onClick={handleRca}>Save RCA</button>
        </section>
      ) : null}
    </DashboardShell>
  )
}

function UserDashboard({ session }: { session: SessionUser }) {
  const [question, setQuestion] = useState('I am unable to access my billing dashboard after a recent update.')
  const [metadata, setMetadata] = useState(DEFAULT_METADATA)
  const [isQuerying, setIsQuerying] = useState(false)
  const [queryError, setQueryError] = useState('')
  const [queryResult, setQueryResult] = useState<QueryResponse | null>(null)
  const [conversationId, setConversationId] = useState<string | undefined>(() => (
    localStorage.getItem(`support-conversation:${session.username}`) ?? undefined
  ))
  const [feedbackComment, setFeedbackComment] = useState('This answer was helpful.')
  const [feedbackHelpful, setFeedbackHelpful] = useState(true)
  const [feedbackState, setFeedbackState] = useState('')

  const handleQuery = async () => {
    setIsQuerying(true)
    setQueryError('')

    try {
      const response = await submitQuery(session.token, question, metadata, conversationId)
      setConversationId(response.session_id)
      localStorage.setItem(`support-conversation:${session.username}`, response.session_id)
      setQueryResult(response)
    } catch (error) {
      setQueryError(error instanceof Error ? error.message : 'Unable to query support')
    } finally {
      setIsQuerying(false)
    }
  }

  const handleFeedback = async () => {
    if (!queryResult?.request_id) return

    try {
      await submitFeedback(session.token, queryResult.request_id, feedbackHelpful, feedbackComment)
      setFeedbackState('Feedback submitted successfully.')
    } catch (error) {
      setFeedbackState(error instanceof Error ? error.message : 'Unable to submit feedback')
    }
  }

  return (
    <DashboardShell
      session={session}
      title="Customer Portal"
      subtitle="Ask the support team"
      navItems={[
        { href: '#query', label: 'New request' },
        { href: '#response', label: 'Response' },
      ]}
    >
      <section id="query" className="panel">
        <div className="panel-header">
          <h3>Ask a question</h3>
          <span className="chip neutral">User access</span>
        </div>

        <textarea value={question} onChange={(event) => setQuestion(event.target.value)} rows={5} placeholder="Describe the issue" />

        <div className="meta-grid compact-grid">
          <input value={metadata.product ?? ''} onChange={(event) => setMetadata((current) => ({ ...current, product: event.target.value }))} placeholder="Product" />
          <input value={metadata.version ?? ''} onChange={(event) => setMetadata((current) => ({ ...current, version: event.target.value }))} placeholder="Version" />
          <input value={metadata.language ?? ''} onChange={(event) => setMetadata((current) => ({ ...current, language: event.target.value }))} placeholder="Language" />
        </div>

        {queryError ? <div className="error-box">{queryError}</div> : null}

        <button type="button" onClick={handleQuery} disabled={isQuerying}>
          {isQuerying ? 'Searching for help...' : 'Ask support'}
        </button>
      </section>

      {queryResult ? (
        <section id="response" className="panel answer-panel">
          <div className="panel-header">
            <h3>Suggested answer</h3>
            <span className="chip warning">Cache hit: {queryResult.cache_hit ? 'yes' : 'no'}</span>
          </div>

          <div className="answer-content">{renderAnswerContent(queryResult.answer)}</div>

          <div className="source-list">
            {queryResult.sources.map((source, index) => (
              <div key={`${source}-${index}`} className="source-card">
                <div className="source-title-row">
                  <strong>Source {index + 1}</strong>
                  <span className="chip neutral">Citation</span>
                </div>
                <p>
                  {source.startsWith('http') ? (
                    <a href={source} target="_blank" rel="noreferrer">{source}</a>
                  ) : (
                    source
                  )}
                </p>
              </div>
            ))}
          </div>

          <div className="feedback-block">
            <div className="panel-header compact">
              <h4>Was this helpful?</h4>
            </div>
            <div className="inline-row">
              <label>
                <input type="checkbox" checked={feedbackHelpful} onChange={(event) => setFeedbackHelpful(event.target.checked)} />
                Helpful
              </label>
            </div>

            <textarea value={feedbackComment} onChange={(event) => setFeedbackComment(event.target.value)} rows={3} placeholder="Tell us how useful this answer was" />

            <button type="button" onClick={handleFeedback}>Submit feedback</button>
            {feedbackState ? <div className="success-box">{feedbackState}</div> : null}
          </div>
        </section>
      ) : null}
    </DashboardShell>
  )
}

function LoginPage({ onLoginSuccess }: { onLoginSuccess: (session: SessionUser) => void }) {
  const navigate = useNavigate()
  const [username, setUsername] = useState('support')
  const [password, setPassword] = useState('support123')
  const [loginError, setLoginError] = useState('')
  const [isLoggingIn, setIsLoggingIn] = useState(false)

  const handleLogin = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setIsLoggingIn(true)
    setLoginError('')

    try {
      const result: AuthResponse = await login(username, password)
      const session: SessionUser = {
        token: result.access_token,
        username: result.username,
        roles: result.roles,
      }
      saveSession(session)
      onLoginSuccess(session)
      navigate(getDashboardPath(result.roles))
    } catch (error) {
      setLoginError(error instanceof Error ? error.message : 'Login failed')
    } finally {
      setIsLoggingIn(false)
    }
  }

  return (
    <div className="page-shell">
      <div className="auth-card">
        <div className="brand-row">
          <div className="brand-badge">AI</div>
          <div>
            <p className="eyebrow">Support portal</p>
            <h1>Sign in</h1>
          </div>
        </div>

        <form onSubmit={handleLogin} className="form-stack">
          <label>
            Username
            <input value={username} onChange={(event) => setUsername(event.target.value)} style={{ color: 'white' }} />
          </label>

          <label>
            Password
            <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} style={{ color: 'white' }} />
          </label>

          {loginError ? <div className="error-box">{loginError}</div> : null}

          <button type="submit" disabled={isLoggingIn}>
            {isLoggingIn ? 'Signing in...' : 'Sign in'}
          </button>
        </form>

        <div className="demo-credentials">
          <strong>Demo users</strong>
          <span>support / support123</span>
          <span>admin / admin123</span>
          <span>user / user123</span>
        </div>
      </div>
    </div>
  )
}

function App() {
  const [session, setSession] = useState<SessionUser | null>(() => loadSession())

  return (
    <Routes>
      <Route path="/login" element={<LoginPage onLoginSuccess={setSession} />} />
      <Route path="/dashboard" element={<ProtectedRoute session={session} />} />
      <Route path="/dashboard/admin" element={<ProtectedRoute session={session} requiredRole="admin" />} />
      <Route path="/dashboard/support" element={<ProtectedRoute session={session} requiredRole="support" />} />
      <Route path="/dashboard/user" element={<ProtectedRoute session={session} requiredRole="user" />} />
      <Route path="*" element={<Navigate to={session ? getDashboardPath(session.roles) : '/login'} replace />} />
    </Routes>
  )
}

export default App
