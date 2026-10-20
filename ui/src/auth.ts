export type SessionUser = {
  token: string
  username: string
  roles: string[]
}

const STORAGE_KEY = 'support-ui-session'

export function loadSession(): SessionUser | null {
  const raw = localStorage.getItem(STORAGE_KEY)
  if (!raw) return null

  try {
    return JSON.parse(raw) as SessionUser
  } catch {
    localStorage.removeItem(STORAGE_KEY)
    return null
  }
}

export function saveSession(session: SessionUser) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(session))
}

export function clearSession() {
  localStorage.removeItem(STORAGE_KEY)
}
