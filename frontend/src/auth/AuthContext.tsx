import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, onUnauthorized, tokens, type Scope } from '../api/client'
import type { User } from '../api/types'

interface AuthState {
  user: User | null
  loading: boolean
  login: (email: string, password: string) => Promise<User>
  logout: () => void
  refresh: () => Promise<void>
  setUser: (u: User) => void
}

function makeAuth(scope: Scope) {
  const Ctx = createContext<AuthState | null>(null)
  const loginPath = scope === 'admin' ? '/auth/admin/login' : '/auth/login'
  const mePath = scope === 'admin' ? '/auth/admin/me' : '/auth/me'

  function Provider({ children }: { children: ReactNode }) {
    const [user, setUser] = useState<User | null>(null)
    const [loading, setLoading] = useState<boolean>(!!tokens.get(scope))

    const refresh = useCallback(async () => {
      if (!tokens.get(scope)) {
        setUser(null)
        setLoading(false)
        return
      }
      try {
        setUser(await api<User>(mePath, { scope }))
      } catch {
        setUser(null)
      } finally {
        setLoading(false)
      }
    }, [])

    useEffect(() => {
      refresh()
      return onUnauthorized(scope, () => setUser(null))
    }, [refresh])

    const login = useCallback(async (email: string, password: string) => {
      const res = await api<{ access_token: string; user: User }>(loginPath, { body: { email, password }, scope })
      tokens.set(scope, res.access_token)
      setUser(res.user)
      return res.user
    }, [])

    const logout = useCallback(() => {
      tokens.clear(scope)
      setUser(null)
    }, [])

    const value = useMemo(() => ({ user, loading, login, logout, refresh, setUser }), [user, loading, login, logout, refresh])
    return <Ctx.Provider value={value}>{children}</Ctx.Provider>
  }

  function useAuthHook() {
    const v = useContext(Ctx)
    if (!v) throw new Error('Auth provider missing')
    return v
  }

  return { Provider, useAuthHook }
}

const appAuth = makeAuth('app')
const adminAuth = makeAuth('admin')

export const AuthProvider = appAuth.Provider
export const useAuth = appAuth.useAuthHook
export const AdminAuthProvider = adminAuth.Provider
export const useAdminAuth = adminAuth.useAuthHook

export const canEdit = (u: User | null) => !!u && (u.role === 'admin' || u.role === 'analyst')
