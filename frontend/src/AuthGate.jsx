import { useEffect, useState } from 'react'
import { ShieldCheck } from 'lucide-react'
import { api } from './api.js'

export default function AuthGate({ children }) {
  const [setupRequired, setSetupRequired] = useState(false)
  const [user, setUser] = useState(null)
  const [mode, setMode] = useState('login')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(true)

  const refresh = async () => {
    try {
      const status = await api.authStatus()
      setSetupRequired(status.setup_required)
      if (status.setup_required) {
        setMode('setup')
        return
      }
      try {
        setUser((await api.me()).user)
      } catch (requestError) {
        if (requestError.status !== 401) throw requestError
        setUser(null)
      }
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => { refresh() }, [])

  const submit = async (event) => {
    event.preventDefault()
    setError('')
    setBusy(true)
    try {
      const credentials = { username, password }
      if (mode === 'setup') {
        const result = await api.bootstrap(credentials)
        setUser(result.user)
      } else if (mode === 'register') {
        await api.register(credentials)
        const result = await api.login(credentials)
        setUser(result.user)
      } else {
        const result = await api.login(credentials)
        setUser(result.user)
      }
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setBusy(false)
      setPassword('')
    }
  }

  const logout = async () => {
    await api.logout()
    setUser(null)
    setMode('login')
  }

  if (busy && !user) return <div className="auth-loading">Connecting to OpsIntel…</div>
  if (user) return children({ user, onLogout: logout })

  const heading = setupRequired ? 'Create the administrator account'
    : mode === 'register' ? 'Create a local account' : 'Sign in to OpsIntel'
  const submitLabel = setupRequired ? 'Set up administrator' : mode === 'register' ? 'Create account' : 'Sign in'

  return (
    <main className="auth-screen">
      <section className="auth-panel">
        <div className="auth-brand"><ShieldCheck size={23} /><span>OpsIntel</span></div>
        <span className="section-eyebrow">LOCAL WORKSPACE</span>
        <h1>{heading}</h1>
        <p>{setupRequired
          ? 'This first account will administer repositories and user access.'
          : mode === 'register' ? 'New accounts need an administrator to grant repository access.'
            : 'Sign in with your OpsIntel account to continue.'}</p>
        <form className="auth-form" onSubmit={submit}>
          <label>Username<input autoComplete="username" required minLength={3} maxLength={64}
            value={username} onChange={(event) => setUsername(event.target.value)} /></label>
          <label>Password<input type="password" autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
            required minLength={12} maxLength={1024} value={password}
            onChange={(event) => setPassword(event.target.value)} /></label>
          {error && <div className="auth-error" role="alert">{error}</div>}
          <button className="primary-button" disabled={busy}>{busy ? 'Working…' : submitLabel}</button>
        </form>
        {!setupRequired && <button className="auth-switch" onClick={() => {
          setMode((current) => current === 'register' ? 'login' : 'register')
          setError('')
        }}>
          {mode === 'register' ? 'Already have an account? Sign in' : 'Create a local account'}
        </button>}
      </section>
    </main>
  )
}