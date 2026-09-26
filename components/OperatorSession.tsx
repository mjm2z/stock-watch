'use client'
import {
  createContext,
  useContext,
  useEffect,
  useState,
  useCallback,
  type ReactNode,
  type FormEvent,
} from 'react'
type Session = { authenticated: boolean; configured: boolean; refresh: () => Promise<void> }
const Context = createContext<Session>({
  authenticated: false,
  configured: false,
  refresh: async () => {},
})
export function OperatorProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState({ authenticated: false, configured: false })
  const refresh = useCallback(async () => {
    try {
      const r = await fetch('/api/systems/session', { cache: 'no-store' })
      if (r.ok) setState(await r.json())
      else setState({ authenticated: false, configured: false })
    } catch {
      setState({ authenticated: false, configured: false })
    }
  }, [])
  useEffect(() => {
    void refresh()
    const t = setInterval(refresh, 30000)
    return () => clearInterval(t)
  }, [refresh])
  return <Context.Provider value={{ ...state, refresh }}>{children}</Context.Provider>
}
export const useOperator = () => useContext(Context)
export function OperatorControls() {
  const session = useOperator(),
    [token, setToken] = useState(''),
    [error, setError] = useState(''),
    [busy, setBusy] = useState(false)
  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    try {
      const r = await fetch('/api/systems/session', {
        method: session.authenticated ? 'DELETE' : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: session.authenticated ? undefined : JSON.stringify({ token }),
      })
      setToken('')
      const d = await r.json()
      if (!r.ok) throw Error(d.error)
      setError('')
      await session.refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Sign-in failed')
    } finally {
      setBusy(false)
    }
  }
  return (
    <details className="sw-operator">
      <summary>
        {session.authenticated ? 'Operator active' : 'Read-only'}
        <span aria-hidden="true"> ▾</span>
      </summary>
      <form onSubmit={submit}>
        <strong>{session.authenticated ? 'Operator session' : 'Operator access'}</strong>
        <p>
          {session.authenticated
            ? 'Your session lasts one hour. Drafts remain saved when it expires.'
            : session.configured
              ? 'Sign in to create systems and run research.'
              : 'Operator access has not been configured on this host.'}
        </p>
        {!session.authenticated && session.configured && (
          <label>
            Operator token
            <input
              type="password"
              autoComplete="current-password"
              value={token}
              onChange={(e) => setToken(e.target.value)}
            />
          </label>
        )}
        {(session.authenticated || session.configured) && (
          <button className="sw-button" disabled={busy}>
            {session.authenticated ? 'Sign out' : 'Sign in'}
          </button>
        )}
        {error && <p role="alert">{error}</p>}
      </form>
    </details>
  )
}
