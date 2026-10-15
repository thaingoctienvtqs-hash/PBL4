import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, setAccessToken } from '../api/client'
import type { User } from '../types'

interface AuthValue {
  user: User | null
  ready: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => Promise<void>
  hasRole: (...roles: string[]) => boolean
}

const AuthContext = createContext<AuthValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [ready, setReady] = useState(true)

  const clearSession = useCallback(() => {
    setAccessToken(null)
    setUser(null)
  }, [])

  useEffect(() => {
    window.addEventListener('artguard:session-expired', clearSession)
    return () => window.removeEventListener('artguard:session-expired', clearSession)
  }, [clearSession])

  const login = useCallback(async (username: string, password: string) => {
    setReady(false)
    try {
      const { data } = await api.post('/auth/login', { username, password })
      setAccessToken(data.access_token)
      setUser(data.user as User)
    } finally {
      setReady(true)
    }
  }, [])

  const logout = useCallback(async () => {
    try { if (user) await api.post('/auth/logout') } catch { /* Clear the in-memory session even if the API is unreachable. */ } finally { clearSession() }
  }, [clearSession, user])

  const value = useMemo<AuthValue>(() => ({ user, ready, login, logout, hasRole: (...roles) => !!user?.roles.some((role) => roles.includes(role)) }), [user, ready, login, logout])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used within AuthProvider')
  return context
}
