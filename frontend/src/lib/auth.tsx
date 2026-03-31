import {
  createContext,
  startTransition,
  useContext,
  useEffect,
  useEffectEvent,
  useMemo,
  useState,
} from 'react'
import type { ReactNode } from 'react'

const AUTH_REQUIRED_EVENT = 'iris-auth-required'

type AuthStatus = {
  bypass_enabled: boolean
  authenticated: boolean
}

type LoginResult =
  | { ok: true }
  | { ok: false; error: 'auth.invalid_password' | 'auth.request_failed' }

type AuthContextValue = {
  ready: boolean
  loading: boolean
  authenticated: boolean
  bypassEnabled: boolean
  login: (password: string) => Promise<LoginResult>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export async function apiFetch(input: RequestInfo | URL, init?: RequestInit) {
  const response = await fetch(input, {
    ...init,
    credentials: init?.credentials ?? 'same-origin',
  })
  if (response.status === 401) {
    notifyAuthRequired()
  }
  return response
}

export function notifyAuthRequired() {
  window.dispatchEvent(new Event(AUTH_REQUIRED_EVENT))
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(false)
  const [loading, setLoading] = useState(false)
  const [authenticated, setAuthenticated] = useState(false)
  const [bypassEnabled, setBypassEnabled] = useState(false)

  const applyStatus = useEffectEvent((status: AuthStatus) => {
    startTransition(() => {
      setBypassEnabled(status.bypass_enabled)
      setAuthenticated(status.authenticated)
      setReady(true)
    })
  })

  const loadStatus = useEffectEvent(async () => {
    try {
      const response = await fetch('/api/auth/status', { credentials: 'same-origin' })
      if (!response.ok) {
        throw new Error(`Failed to load auth status: ${response.status}`)
      }
      applyStatus(await response.json())
    } catch {
      startTransition(() => {
        setBypassEnabled(false)
        setAuthenticated(false)
        setReady(true)
      })
    }
  })

  useEffect(() => {
    void loadStatus()
  }, [])

  useEffect(() => {
    const handleAuthRequired = () => {
      startTransition(() => {
        setAuthenticated(false)
        setBypassEnabled(false)
        setReady(true)
      })
    }
    window.addEventListener(AUTH_REQUIRED_EVENT, handleAuthRequired)
    return () => {
      window.removeEventListener(AUTH_REQUIRED_EVENT, handleAuthRequired)
    }
  }, [])

  const value = useMemo<AuthContextValue>(() => ({
    ready,
    loading,
    authenticated,
    bypassEnabled,
    login: async (password: string) => {
      setLoading(true)
      try {
        const response = await fetch('/api/auth/login', {
          method: 'POST',
          credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ password }),
        })
        const payload = await response.json()
        if (!response.ok) {
          return {
            ok: false,
            error: response.status === 401 ? 'auth.invalid_password' : 'auth.request_failed',
          }
        }
        applyStatus(payload)
        return { ok: true }
      } catch {
        return { ok: false, error: 'auth.request_failed' }
      } finally {
        setLoading(false)
      }
    },
    logout: async () => {
      setLoading(true)
      try {
        const response = await fetch('/api/auth/logout', {
          method: 'POST',
          credentials: 'same-origin',
        })
        if (response.ok) {
          applyStatus(await response.json())
          return
        }
      } finally {
        setLoading(false)
      }
      startTransition(() => {
        setAuthenticated(false)
        setBypassEnabled(false)
        setReady(true)
      })
    },
  }), [applyStatus, authenticated, bypassEnabled, loading, ready])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider')
  }
  return context
}