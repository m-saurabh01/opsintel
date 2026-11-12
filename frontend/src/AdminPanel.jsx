import { useEffect, useRef, useState } from 'react'
import { api } from './api.js'

function RepositoryPicker({ repos, selected, onChange, label }) {
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)
  const pickerRef = useRef(null)
  const normalizedQuery = query.trim().toLowerCase()
  const visibleRepos = repos.filter((repo) => repo.name.toLowerCase().includes(normalizedQuery))
  const allVisibleSelected = visibleRepos.length > 0 && visibleRepos.every((repo) => selected.includes(repo.id))

  useEffect(() => {
    if (!open) return undefined
    const handlePointerDown = (event) => {
      if (!pickerRef.current?.contains(event.target)) setOpen(false)
    }
    const handleKeyDown = (event) => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('pointerdown', handlePointerDown)
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('pointerdown', handlePointerDown)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [open])

  const toggleVisible = () => {
    const visibleIds = new Set(visibleRepos.map((repo) => repo.id))
    onChange(allVisibleSelected
      ? selected.filter((id) => !visibleIds.has(id))
      : [...new Set([...selected, ...visibleIds])])
  }

  const toggleRepo = (repoId, checked) => {
    onChange(checked
      ? [...new Set([...selected, repoId])]
      : selected.filter((id) => id !== repoId))
  }

  return (
    <div className="repo-picker" ref={pickerRef}>
      <button type="button" className="repo-picker-trigger" disabled={!repos.length}
        aria-haspopup="true" aria-expanded={open} onClick={() => setOpen((value) => !value)}>
        <span>{selected.length ? `${selected.length} repositories selected` : 'Select repositories'}</span>
        <span className="repo-picker-chevron" aria-hidden="true">{open ? '−' : '+'}</span>
      </button>
      {open && <div className="repo-picker-menu">
        <div className="repo-picker-tools">
          <input autoFocus type="search" value={query} onChange={(event) => setQuery(event.target.value)}
            placeholder="Filter repositories" aria-label={`Filter ${label.toLowerCase()}`} />
          <button type="button" disabled={!visibleRepos.length} onClick={toggleVisible}>
            {allVisibleSelected ? 'Clear visible' : 'Select visible'}
          </button>
        </div>
        <div className="repo-picker-list" role="group" aria-label={label}>
          {visibleRepos.map((repo) => <label key={repo.id}>
            <input type="checkbox" checked={selected.includes(repo.id)}
              onChange={(event) => toggleRepo(repo.id, event.target.checked)} />
            <span title={repo.name}>{repo.name}</span>
          </label>)}
          {!visibleRepos.length && <span className="repo-picker-empty">
            No repositories match this filter.
          </span>}
        </div>
        <div className="repo-picker-footer">{selected.length} of {repos.length} selected</div>
      </div>}
    </div>
  )
}

function AIAccessPolicy({ enabled, limit, usage, onEnabledChange, onLimitChange }) {
  return (
    <div className="ai-user-policy">
      <div className="ai-policy-heading"><strong>AI Assistance</strong>{usage && <span>{usage}</span>}</div>
      <div className="ai-policy-controls">
        <label className="ai-access-toggle">
          <input type="checkbox" checked={enabled} onChange={(event) => onEnabledChange(event.target.checked)} />
          <span>Enable</span>
        </label>
        <label className="ai-limit-control"><span>Daily limit</span>
          <input type="number" min="0" max="10000" value={limit}
            onChange={(event) => onLimitChange(event.target.value)} />
        </label>
      </div>
      <small className="ai-policy-note">0 uses the workspace default</small>
    </div>
  )
}

export default function AdminPanel({ repos, onChanged }) {
  const [users, setUsers] = useState([])
  const [status, setStatus] = useState(null)
  const [removeRepoId, setRemoveRepoId] = useState(null)
  const [grants, setGrants] = useState({})
  const [localPath, setLocalPath] = useState('')
  const [localName, setLocalName] = useState('')
  const [giteaName, setGiteaName] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [newUserRepos, setNewUserRepos] = useState([])
  const [newUserAiEnabled, setNewUserAiEnabled] = useState(true)
  const [newUserAiLimit, setNewUserAiLimit] = useState(0)
  const [aiPolicies, setAiPolicies] = useState({})
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const refresh = async () => {
    const [nextUsers, nextStatus] = await Promise.all([api.adminUsers(), api.adminStatus()])
    setUsers(nextUsers)
    setStatus(nextStatus)
    setGrants(Object.fromEntries(nextUsers.map((user) => [
      user.id, (user.repo_ids || []),
    ])))
    setAiPolicies(Object.fromEntries(nextUsers.map((user) => [user.id, {
      enabled: user.ai_enabled,
      dailyLimit: user.ai_daily_limit,
    }])))
  }

  useEffect(() => {
    refresh().catch((requestError) => setError(requestError.message))
  }, [])

  const hasActiveIndexing = Object.values(status?.indexing || {}).some((jobs) => jobs.length > 0)
  useEffect(() => {
    if (!hasActiveIndexing) return undefined
    const timer = setInterval(() => {
      api.adminStatus().then(setStatus).catch(() => {})
    }, 1000)
    return () => clearInterval(timer)
  }, [hasActiveIndexing])

  const run = async (action, success) => {
    setBusy(true)
    setError('')
    setMessage('')
    try {
      await action()
      await refresh()
      await onChanged()
      setMessage(success)
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setBusy(false)
    }
  }

  const createUser = (event) => {
    event.preventDefault()
    run(async () => {
      await api.createUser({ username, password, role: 'user', repo_ids: newUserRepos,
        ai_enabled: newUserAiEnabled, ai_daily_limit: Number(newUserAiLimit) || 0 })
      setUsername('')
      setPassword('')
      setNewUserRepos([])
      setNewUserAiEnabled(true)
      setNewUserAiLimit(0)
    }, 'Account created.')
  }

  const saveUserSettings = (user) => {
    const policy = aiPolicies[user.id] || { enabled: user.ai_enabled, dailyLimit: user.ai_daily_limit }
    const updates = {
      ai_enabled: policy.enabled,
      ai_daily_limit: Number(policy.dailyLimit) || 0,
    }
    if (user.role === 'user') updates.repo_ids = grants[user.id] || []
    run(() => api.updateUser(user.id, updates), `Settings updated for ${user.username}.`)
  }

  const updateAiPolicy = (userId, patch) => {
    setAiPolicies((current) => ({ ...current, [userId]: { ...current[userId], ...patch } }))
  }

  return (
    <section className="management-view admin-view">
      <div className="search-view-heading">
        <div><span className="section-eyebrow">ADMINISTRATION</span><h1>Workspace access</h1>
          <p>Manage local indexes and decide which accounts can search each repository.</p></div>
      </div>
      {message && <div className="admin-message" role="status">{message}</div>}
      {error && <div className="auth-error" role="alert">{error}</div>}

      <section className="admin-section">
        <div className="section-heading compact-heading"><div><span className="section-eyebrow">SOURCES</span><h2>Repositories</h2></div>
          <span className="view-count">{repos.length} registered</span></div>
        <div className="admin-add-grid">
          <form className="admin-form" onSubmit={(event) => {
            event.preventDefault()
            run(async () => {
              await api.addLocalRepo({ path: localPath, name: localName || undefined })
              setLocalPath('')
              setLocalName('')
            }, 'Local repository added; indexing was queued.')
          }}>
            <h3>Add local checkout</h3>
            <label>Folder path<input required value={localPath} onChange={(event) => setLocalPath(event.target.value)}
              placeholder="/path/to/checkout" /></label>
            <label>Display name<input value={localName} onChange={(event) => setLocalName(event.target.value)}
              placeholder="Optional" /></label>
            <button disabled={busy}>Add and index</button>
          </form>
          <form className="admin-form" onSubmit={(event) => {
            event.preventDefault()
            run(async () => {
              await api.addGiteaRepo({ full_name: giteaName })
              setGiteaName('')
            }, 'Gitea repository registered; sync was queued.')
          }}>
            <h3>Register Gitea repository</h3>
            <label>Owner / repository<input required value={giteaName}
              onChange={(event) => setGiteaName(event.target.value)} placeholder="team/service" /></label>
            <button disabled={busy}>Register and sync</button>
          </form>
        </div>
        <div className="admin-repo-list">
          {repos.map((repo) => {
            const indexed = repo.indexed || 0
            const total = repo.files || 0
            const coverage = total ? Math.round(indexed * 100 / total) : 0
            const activeJob = status?.indexing?.[repo.id]?.[0]
            const progress = activeJob?.progress
            const progressPercent = Number.isFinite(progress?.percent) ? progress.percent : null
            const progressLabel = activeJob?.status === 'queued' ? 'Queued for indexing'
              : progress?.phase === 'counting' ? 'Counting files…'
                : progress?.phase === 'scanning' ? `Scanning ${progress.current.toLocaleString()} files…`
                  : progressPercent === null ? 'Starting index…'
                    : `${progress.current.toLocaleString()} of ${progress.total.toLocaleString()} files · ${progressPercent}%`
            return <div className="admin-repo-row" key={repo.id}>
            <div className="admin-repo-main">
              <strong>{repo.name}</strong>
              <div className="repo-index-meta"><small>{repo.kind} · {indexed}/{total} indexed</small>
                <small>{total ? `${coverage}%` : 'Not indexed'}</small></div>
              {total > 0 && <div className="repo-progress-track" role="progressbar" aria-label={`${repo.name} indexed coverage`}
                aria-valuemin={0} aria-valuemax={100} aria-valuenow={coverage}>
                <span style={{ width: `${coverage}%` }} />
              </div>}
              {repo.last_indexed_at && <small className="repo-index-time">Last indexed {repo.last_indexed_at}</small>}
              {activeJob && <div className="repo-live-progress">
                <div className={`repo-progress-track ${progressPercent === null ? 'indeterminate' : ''}`}
                  role="progressbar" aria-label={`${repo.name} indexing progress`}
                  aria-valuemin={0} aria-valuemax={100}
                  aria-valuenow={progressPercent === null ? undefined : progressPercent}>
                  <span style={progressPercent === null ? undefined : { width: `${progressPercent}%` }} />
                </div>
                <small>{progressLabel}{activeJob.branch ? ` · ${activeJob.branch}` : ''}</small>
              </div>}
            </div>
            <div className="admin-repo-actions">
              {removeRepoId === repo.id
                ? <div className="repo-remove-confirm" role="group" aria-label={`Confirm removal of ${repo.name}`}>
                  <span>Remove index and mirror? Gitea will be unchanged.</span>
                  <button disabled={busy} onClick={() => setRemoveRepoId(null)}>Cancel</button>
                  <button className="danger-action" disabled={busy} onClick={() => run(async () => {
                    await api.removeRepo(repo.id)
                    setRemoveRepoId(null)
                  }, 'Repository index removed.')}>Confirm remove</button>
                </div>
                : <>
                  <button disabled={busy} onClick={() => run(() => api.syncRepo(repo.id), 'Index job queued.')}>Sync</button>
                  <button disabled={busy} onClick={() => run(
                    () => api.setRepoEnabled(repo.id, !repo.enabled),
                    repo.enabled ? 'Repository disabled.' : 'Repository enabled.',
                  )}>{repo.enabled ? 'Disable' : 'Enable'}</button>
                  <button className="danger-action" disabled={busy} onClick={() => setRemoveRepoId(repo.id)}>
                    Remove index
                  </button>
                </>}
            </div>
          </div>})}
          {!repos.length && <p className="admin-empty">No repositories have been added.</p>}
        </div>
      </section>

      <section className="admin-section">
        <div className="section-heading compact-heading"><div><span className="section-eyebrow">ACCOUNTS</span><h2>Users and repository access</h2></div>
          <span className="view-count">{users.length} accounts</span></div>
        <form className="admin-user-form" onSubmit={createUser}>
          <label>Username<input required minLength={3} maxLength={64} value={username}
            onChange={(event) => setUsername(event.target.value)} /></label>
          <label>Temporary password<input required type="password" minLength={12} maxLength={1024}
            value={password} onChange={(event) => setPassword(event.target.value)} /></label>
          <RepositoryPicker repos={repos} selected={newUserRepos} onChange={setNewUserRepos}
            label="Repositories for new user" />
          <AIAccessPolicy enabled={newUserAiEnabled} limit={newUserAiLimit}
            onEnabledChange={setNewUserAiEnabled} onLimitChange={setNewUserAiLimit} />
          <button disabled={busy}>Create user</button>
        </form>
        <div className="admin-user-list">
          {users.map((user) => <div className={`admin-user-row ${user.role === 'user' ? 'with-repos' : 'admin-only'}`}
            key={user.id}>
            <div className="admin-user-title"><strong>{user.username}</strong><small>{user.role}{user.enabled ? '' : ' · disabled'}</small></div>
            <AIAccessPolicy enabled={aiPolicies[user.id]?.enabled ?? user.ai_enabled}
              limit={aiPolicies[user.id]?.dailyLimit ?? user.ai_daily_limit}
              usage={`${user.ai_requests_today}/${user.ai_effective_daily_limit} used today`}
              onEnabledChange={(enabled) => updateAiPolicy(user.id, { enabled })}
              onLimitChange={(dailyLimit) => updateAiPolicy(user.id, { dailyLimit })} />
            {user.role === 'user' && <>
              <RepositoryPicker repos={repos} selected={grants[user.id] || []}
                onChange={(next) => setGrants((current) => ({ ...current, [user.id]: next }))}
                label={`Repositories for ${user.username}`} />
            </>}
            <button disabled={busy} onClick={() => saveUserSettings(user)}>Save settings</button>
            <button disabled={busy || (user.id === users.find((item) => item.role === 'admin' && item.enabled)?.id && users.filter((item) => item.role === 'admin' && item.enabled).length === 1)}
              onClick={() => run(() => api.updateUser(user.id, { enabled: !user.enabled }), user.enabled ? 'Account disabled.' : 'Account enabled.')}
            >{user.enabled ? 'Disable account' : 'Enable account'}</button>
          </div>)}
        </div>
      </section>
      {status?.audit?.length > 0 && <section className="admin-section">
        <div className="section-heading compact-heading"><div><span className="section-eyebrow">AUDIT</span><h2>Recent administration</h2></div></div>
        <div className="admin-audit-list">
          {status.audit.map((event) => <div key={event.id}><strong>{event.action}</strong>
            <span>{event.actor || 'system'} · {event.target_type} {event.target_id || ''}</span><time>{event.created_at}</time></div>)}
        </div>
      </section>}
    </section>
  )
}
