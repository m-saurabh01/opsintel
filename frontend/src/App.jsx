import { Suspense, lazy, useCallback, useEffect, useRef, useState } from 'react'
import {
  Activity,
  ArrowDownRight,
  ArrowRight,
  Bot,
  Check,
  ChevronDown,
  Database,
  FileCode2,
  FileSearch,
  FileSpreadsheet,
  FileText,
  FolderGit2,
  Home,
  Layers3,
  Moon,
  Search,
  Server,
  ShieldCheck,
  Sparkles,
  Sun,
} from 'lucide-react'
import { api } from './api.js'
import AIAssistant from './AIAssistant.jsx'
import ChunkViewer from './ChunkViewer.jsx'
import Results from './Results.jsx'
import Viewer from './Viewer.jsx'

const PdfViewer = lazy(() => import('./PdfViewer.jsx'))

const MODES = [
  { value: 'fulltext', label: 'Full text' },
  { value: 'phrase', label: 'Phrase' },
  { value: 'exact', label: 'Exact substring' },
]
const PAGE_SIZE = 20

function readUrlState() {
  const p = new URLSearchParams(window.location.search)
  const q = p.get('q') || ''
  return {
    q,
    view: p.get('view') || (q ? 'search' : 'home'),
    mode: p.get('mode') || 'fulltext',
    repo: p.get('repo') || '',
    type: p.get('type') || '',
    path: p.get('path') || '',
    caseSensitive: p.get('cs') === '1',
    page: Number(p.get('page')) || 1,
    open: p.get('open')
      ? {
          fileId: Number(p.get('open')),
          ...(p.get('chunk')
            ? {
                chunk: Number(p.get('chunk')),
                mark: Number(p.get('mark')) || 0,
                ...(p.get('cell') ? { cell: p.get('cell') } : {}),
                ...(p.get('pdf') === '1' ? { pdf: true, page: Number(p.get('page')) || 1 } : {}),
              }
            : { line: Number(p.get('line')) || 1 }),
        }
      : null,
  }
}

function writeUrlState(s, replace = false) {
  const p = new URLSearchParams()
  if (s.q) p.set('q', s.q)
  if (s.view !== 'home') p.set('view', s.view)
  if (s.mode !== 'fulltext') p.set('mode', s.mode)
  if (s.repo) p.set('repo', s.repo)
  if (s.type) p.set('type', s.type)
  if (s.path) p.set('path', s.path)
  if (s.caseSensitive) p.set('cs', '1')
  if (s.page > 1) p.set('page', String(s.page))
  if (s.open) {
    p.set('open', String(s.open.fileId))
    if (s.open.chunk) {
      p.set('chunk', String(s.open.chunk))
      p.set('mark', String(s.open.mark || 0))
      if (s.open.cell) p.set('cell', s.open.cell)
      if (s.open.pdf) {
        p.set('pdf', '1')
        p.set('page', String(s.open.page || 1))
      }
    } else {
      p.set('line', String(s.open.line))
    }
  }
  const url = `${window.location.pathname}${p.toString() ? `?${p}` : ''}`
  if (url === `${window.location.pathname}${window.location.search}`) return
  window.history[replace ? 'replaceState' : 'pushState'](null, '', url)
}

export default function App() {
  const [state, setState] = useState(readUrlState)
  const [draft, setDraft] = useState(state.q)
  const [repos, setRepos] = useState([])
  const [facets, setFacets] = useState({ file_types: [] })
  const [health, setHealth] = useState(undefined)
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const topSearchRef = useRef(null)
  const [theme, setTheme] = useState(() => localStorage.getItem('opsintel-theme') === 'light' ? 'light' : 'dark')

  useEffect(() => {
    api.repos().then(setRepos).catch(() => {})
    api.facets().then(setFacets).catch(() => {})
    api.health().then(setHealth).catch(() => setHealth(null))
    const onPop = () => {
      const s = readUrlState()
      setState(s)
      setDraft(s.q)
    }
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])

  useEffect(() => {
    localStorage.setItem('opsintel-theme', theme)
  }, [theme])

  useEffect(() => {
    const handleShortcut = (event) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        topSearchRef.current?.focus()
        topSearchRef.current?.select()
      } else if (event.key === 'Escape' && document.activeElement === topSearchRef.current) {
        topSearchRef.current.blur()
      }
    }
    window.addEventListener('keydown', handleShortcut)
    return () => window.removeEventListener('keydown', handleShortcut)
  }, [])

  useEffect(() => {
    if (!state.q) {
      setResult(null)
      setError('')
      return
    }
    let cancelled = false
    setLoading(true)
    setError('')
    api
      .search({
        q: state.q,
        mode: state.mode,
        repo: state.repo,
        type: state.type,
        path: state.path,
        case_sensitive: state.caseSensitive ? 'true' : undefined,
        page: state.page,
        page_size: PAGE_SIZE,
      })
      .then((r) => !cancelled && setResult(r))
      .catch((e) => {
        if (!cancelled) {
          setResult(null)
          setError(e.message)
        }
      })
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [state.q, state.mode, state.repo, state.type, state.path, state.caseSensitive, state.page])

  const update = useCallback((patch, { replace = false } = {}) => {
    setState((prev) => {
      const next = { ...prev, ...patch }
      writeUrlState(next, replace)
      return next
    })
  }, [])

  const submit = (e) => {
    e.preventDefault()
    update({ view: 'search', q: draft.trim(), page: 1, open: null })
  }

  const open = useCallback((target) => update({ open: target }), [update])
  const close = useCallback(() => update({ open: null }), [update])

  const ai = health?.ai
  const ThemeIcon = theme === 'dark' ? Sun : Moon
  const aiLabel = health === undefined ? 'Checking…' : !health ? 'API unreachable' : !ai?.enabled ? 'AI disabled'
    : ai.reachable && ai.model_present ? `AI ready (${ai.model})` : 'AI unavailable'

  const navigate = (view, patch = {}) => {
    setSidebarOpen(false)
    update({ view, ...patch })
  }
  const totalFiles = repos.reduce((sum, repo) => sum + (repo.files || 0), 0)
  const indexedFiles = repos.reduce((sum, repo) => sum + (repo.indexed || 0), 0)
  const types = Object.fromEntries(facets.file_types.map((f) => [f.file_type, f.n]))
  const navItems = [
    { id: 'home', label: 'Home', icon: Home },
    { id: 'search', label: 'Global Search', icon: Search },
    { id: 'assistant', label: 'AI Assistant', icon: Bot },
    { id: 'repositories', label: 'Repositories', icon: FolderGit2 },
    { id: 'health', label: 'Index Health', icon: Activity },
  ]
  const categories = [
    { label: 'Code & source', type: 'code', icon: FileCode2, tint: 'blue', count: types.code || 0 },
    { label: 'Configuration', type: 'structured', icon: Database, tint: 'violet', count: types.structured || 0 },
    { label: 'Documents', type: 'document', icon: FileText, tint: 'teal', count: types.document || 0 },
    { label: 'Spreadsheets', type: 'spreadsheet', icon: FileSpreadsheet, tint: 'green', count: types.spreadsheet || 0 },
  ]

  const searchFor = (query) => {
    setDraft(query)
    navigate('search', { q: query, page: 1, open: null })
  }

  const openCategory = (type) => {
    setDraft('')
    navigate('search', { type, q: '', open: null })
  }

  const openRepository = (id) => {
    setDraft('')
    navigate('search', { repo: String(id), q: '', type: '', open: null })
  }

  const goHome = () => {
    setDraft('')
    navigate('home', { q: '', repo: '', type: '', path: '', page: 1, open: null })
  }

  const openCitation = (citation) => {
    const loc = citation.location
    const mark = citation.preview?.find((line) => line.highlights?.length)?.index ?? 0
    let target
    if (loc.kind === 'line') target = { fileId: citation.file_id, line: loc.line }
    else if (loc.kind === 'page') {
      target = { fileId: citation.file_id, chunk: citation.chunk_id, mark, page: loc.page, pdf: true }
    } else {
      target = { fileId: citation.file_id, chunk: citation.chunk_id, mark,
        ...(loc.kind === 'cell' ? { cell: loc.cell } : {}) }
    }
    setDraft('')
    navigate('search', { q: '', open: target })
  }

  const filters = (
    <div className="search-filters" aria-label="Search filters">
      <label className="filter-select">
        <FolderGit2 size={14} />
        <select value={state.repo} onChange={(e) => update({ view: 'search', repo: e.target.value, page: 1 })} aria-label="Repository">
          <option value="">All repositories</option>
          {repos.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
        </select>
        <ChevronDown size={13} />
      </label>
      <label className="filter-select">
        <Layers3 size={14} />
        <select value={state.type} onChange={(e) => update({ view: 'search', type: e.target.value, page: 1 })} aria-label="File type">
          <option value="">All file types</option>
          {facets.file_types.map((f) => <option key={f.file_type} value={f.file_type}>{f.file_type} ({f.n})</option>)}
        </select>
        <ChevronDown size={13} />
      </label>
      <label className="path-filter">
        <input
          type="text"
          defaultValue={state.path}
          key={state.path}
          placeholder="Path prefix"
          aria-label="Path prefix"
          onBlur={(e) => e.target.value !== state.path && update({ path: e.target.value.trim(), page: 1 })}
          onKeyDown={(e) => e.key === 'Enter' && e.currentTarget.blur()}
        />
      </label>
      {state.mode === 'exact' && (
        <label className="case-filter">
          <input type="checkbox" checked={state.caseSensitive}
            onChange={(e) => update({ caseSensitive: e.target.checked, page: 1 })} />
          Case sensitive
        </label>
      )}
    </div>
  )

  return (
    <div className="app-shell" data-theme={theme}>
      <aside className={`sidebar ${sidebarOpen ? 'sidebar-open' : ''}`}>
        <button className="brand-lockup" onClick={goHome} aria-label="OpsIntel home">
          <span className="brand-emblem"><ShieldCheck size={24} strokeWidth={2.2} /></span>
          <span className="brand-copy"><strong>OpsIntel</strong><small>SEARCH · ANALYZE · BUILD</small></span>
        </button>
        <div className="nav-caption">WORKSPACE</div>
        <nav className="primary-nav" aria-label="Main navigation">
          {navItems.map(({ id, label, icon: Icon }) => (
            <button key={id} className={`nav-item ${state.view === id ? 'active' : ''}`}
              onClick={() => id === 'home' ? goHome() : navigate(id)}>
              <Icon size={17} strokeWidth={1.8} /><span>{label}</span>
              {id === 'search' && result?.total > 0 && <span className="nav-count">{result.total}</span>}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="offline-card">
            <span className={`health-dot ${health?.search_available ? 'healthy' : ''}`} />
            <div><strong>{health?.search_available ? 'Local search ready' : 'Connecting'}</strong><small>{aiLabel}</small></div>
          </div>
          <div className="sidebar-user"><span className="user-avatar"><ShieldCheck size={15} /></span>
            <span><strong>Local workspace</strong><small>No cloud connection</small></span></div>
        </div>
      </aside>

      <div className="shell-main">
        <header className="topbar">
          <button className="mobile-menu" onClick={() => setSidebarOpen((open) => !open)} aria-label="Toggle navigation">
            <span /><span /><span />
          </button>
          <form className="top-search" onSubmit={submit} role="search">
            <Search size={16} />
            <input ref={topSearchRef} type="search" value={draft} onChange={(e) => setDraft(e.target.value)}
              placeholder="Search files, documents, code, logs, spreadsheets…" aria-label="Search query" maxLength={500} />
            {draft && <button className="clear-search" type="button" aria-label="Clear search" onClick={() => setDraft('')}>×</button>}
            <span className="top-search-shortcut">⌘ K</span>
          </form>
          <button className="icon-button" title="Local search status" aria-label={aiLabel}><Activity size={17} /></button>
          <button className="theme-toggle" aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}
            aria-pressed={theme === 'light'} title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}
            onClick={() => setTheme((current) => current === 'dark' ? 'light' : 'dark')}>
            <ThemeIcon size={16} /><span>{theme === 'dark' ? 'Light theme' : 'Dark theme'}</span>
          </button>
        </header>

        <div className="shell-content">
          {state.view === 'home' && (
            <section className="home-view">
              <div className="home-hero">
                <div className="hero-image" />
                <div className="hero-content">
                  <div className="hero-kicker"><span className="hero-kicker-line" /> LOCAL KNOWLEDGE WORKSPACE</div>
                  <h1>Find knowledge.<br /><span>Build with context.</span></h1>
                  <p>Search across your repositories, documents, configurations and operational data without sending content outside your network.</p>
                  <form className="hero-search" onSubmit={submit} role="search">
                    <Search size={19} />
                    <input type="search" value={draft} onChange={(e) => setDraft(e.target.value)}
                      placeholder="Search across files, repositories and documents…" aria-label="Search workspace" />
                    <select value={state.mode} onChange={(e) => update({ mode: e.target.value })} aria-label="Search mode">
                      {MODES.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
                    </select>
                    <button type="submit"><Search size={15} /> Search</button>
                  </form>
                  <div className="hero-hints"><span>Try</span>
                    {['authentication token', 'connection timeout', 'handle_logout'].map((q) => (
                      <button key={q} onClick={() => searchFor(q)}>{q}<ArrowDownRight size={12} /></button>
                    ))}
                  </div>
                  <div className="hero-credit">NASA/JPL-Caltech · Deep Space Network, Goldstone</div>
                </div>
                <div className="hero-side-label">LOCAL<br />INTELLIGENCE<br /><span>PRIVATE BY DESIGN</span></div>
              </div>

              <div className="section-heading">
                <div><span className="section-eyebrow">YOUR INDEX</span><h2>Workspace overview</h2></div>
                <button className="subtle-link" onClick={() => navigate('repositories')}>
                  View repositories <ArrowRight size={14} />
                </button>
              </div>
              <div className="overview-strip">
                <div className="overview-stat"><span className="stat-icon blue"><FolderGit2 size={17} /></span>
                  <div><strong>{repos.length}</strong><span>Repositories</span></div></div>
                <div className="overview-stat"><span className="stat-icon cyan"><FileSearch size={17} /></span>
                  <div><strong>{indexedFiles.toLocaleString()}</strong><span>Indexed files</span></div></div>
                <div className="overview-stat"><span className="stat-icon green"><Check size={17} /></span>
                  <div><strong>{Math.max(0, totalFiles - indexedFiles).toLocaleString()}</strong><span>Pending / skipped</span></div></div>
                <div className="overview-stat"><span className="stat-icon violet"><Server size={17} /></span>
                  <div><strong>{health?.worker?.alive ? 'Online' : 'Idle'}</strong><span>Index worker</span></div></div>
              </div>

              <div className="section-heading domains-heading">
                <div><span className="section-eyebrow">SEARCH DOMAINS</span><h2>Go straight to the source</h2></div>
                <span className="section-note">Filter the index by content type</span>
              </div>
              <div className="domain-grid">
                {categories.map(({ label, type, icon: Icon, tint, count }) => (
                  <button key={type} className="domain-card" onClick={() => openCategory(type)}>
                    <span className={`domain-icon ${tint}`}><Icon size={20} strokeWidth={1.8} /></span>
                    <span className="domain-copy"><strong>{label}</strong><small>{count.toLocaleString()} indexed files</small></span>
                    <ArrowRight className="domain-arrow" size={15} />
                  </button>
                ))}
              </div>

              <div className="home-bottom-grid">
                <section className="repo-section">
                  <div className="section-heading compact-heading"><div><span className="section-eyebrow">CONNECTED</span><h2>Repositories</h2></div>
                    <button className="subtle-link" onClick={() => navigate('repositories')}>All <ArrowRight size={14} /></button></div>
                  {repos.length ? <div className="repo-list">
                    {repos.slice(0, 4).map((repo) => <button key={repo.id} className="repo-row"
                      onClick={() => openRepository(repo.id)}>
                      <span className="repo-mark"><FolderGit2 size={16} /></span>
                      <span className="repo-name"><strong>{repo.name}</strong><small>{repo.kind} repository · {repo.indexed || 0} indexed</small></span>
                      <span className="repo-branch">{repo.default_branch || '—'}</span><ArrowRight size={14} />
                    </button>)}
                  </div> : <div className="home-empty"><FolderGit2 size={18} /><span>No repositories indexed yet</span></div>}
                </section>
                <section className="local-panel">
                  <div className="local-panel-icon"><ShieldCheck size={20} /></div>
                  <span className="section-eyebrow">LOCAL-FIRST</span>
                  <h3>Your repository stays on this machine.</h3>
                  <p>Search works independently of AI. Optional answers use your local Ollama model.</p>
                  <div className="local-status-line"><span className={`health-dot ${health?.search_available ? 'healthy' : ''}`} />
                    {health?.search_available ? 'Search engine operational' : 'Waiting for API'}<span className="status-divider" />
                    {ai?.enabled && ai?.reachable && ai.model_present ? 'Ollama connected' : 'AI unavailable'}</div>
                  <button className="assistant-link" onClick={() => navigate('assistant')} disabled={!ai?.enabled}>
                    Ask with AI <ArrowRight size={13} />
                  </button>
                </section>
              </div>
            </section>
          )}

          {state.view === 'search' && (
            <section className="search-view">
              <div className="search-view-heading">
                <div><span className="section-eyebrow">WORKSPACE</span><h1>Global Search</h1>
                  <p>Search source code, configurations and documents across indexed repositories.</p></div>
                <div className="search-mode-control">
                  <label htmlFor="mode-select">Search mode</label>
                  <select id="mode-select" value={state.mode} onChange={(e) => update({ mode: e.target.value, page: 1 })}>
                    {MODES.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
                  </select>
                </div>
              </div>
              {filters}
              {error && <div className="error" role="alert">{error}</div>}
              <main className={`search-workspace ${state.open ? 'with-viewer' : ''}`}>
                <section className="results-pane">
                  {!state.q ? (
                    <div className="search-empty">
                      <span className="empty-search-icon"><Search size={22} /></span>
                      <h2>Search your workspace</h2>
                      <p>Try a class name, function, configuration key or phrase.</p>
                      <div className="mode-help"><span><b>Full text</b> All terms, any order</span><span><b>Phrase</b> Exact word order</span>
                        <span><b>Exact substring</b> Match inside identifiers</span></div>
                    </div>
                  ) : <>
                    <div className="results-heading">
                      <div><span className="section-eyebrow">QUERY RESULTS</span><h2>{loading ? 'Searching…' : 'Search Results'}</h2></div>
                      {!loading && result && <span className="results-total">{result.total.toLocaleString()}{result.total_is_lower_bound ? '+' : ''} matches</span>}
                    </div>
                    {loading && <div className="search-loading"><span className="loading-line" /><span className="loading-line short" /></div>}
                    {result && !loading && <Results result={result} selected={state.open} onOpen={open}
                      onPage={(page) => update({ page })} pageSize={PAGE_SIZE} />}
                  </>}
                </section>
                {state.open && !state.open.chunk && <Viewer fileId={state.open.fileId} line={state.open.line} onClose={close} />}
                {state.open?.pdf && <Suspense fallback={<div className="viewer-message">Loading PDF viewer…</div>}>
                  <PdfViewer fileId={state.open.fileId} page={state.open.page} onClose={close}
                    onTextView={() => update({ open: { ...state.open, pdf: false } })} />
                </Suspense>}
                {state.open?.chunk && !state.open.pdf && <ChunkViewer fileId={state.open.fileId} chunkId={state.open.chunk}
                  mark={state.open.mark} cell={state.open.cell} onClose={close} />}
              </main>
            </section>
          )}

          {state.view === 'repositories' && <section className="management-view">
            <div className="search-view-heading"><div><span className="section-eyebrow">WORKSPACE</span><h1>Repositories</h1>
              <p>Browse indexed repositories and search within a selected source.</p></div>
              <span className="view-count">{repos.length} connected</span></div>
            <div className="repo-table">
              <div className="repo-table-head"><span>Repository</span><span>Source</span><span>Files indexed</span><span>Last indexed</span><span /></div>
              {repos.map((repo) => <button key={repo.id} className="repo-table-row"
                onClick={() => openRepository(repo.id)}>
                <span className="table-repo"><i><FolderGit2 size={16} /></i><span><strong>{repo.name}</strong><small>{repo.default_branch || 'No default branch'}</small></span></span>
                <span className="repo-kind"><span className="source-dot" />{repo.kind}</span>
                <span className="repo-file-count">{(repo.indexed || 0).toLocaleString()} <small>/ {(repo.files || 0).toLocaleString()}</small></span>
                <span className="repo-updated">{repo.last_indexed_at || 'Not indexed'}</span><ArrowRight size={15} />
              </button>)}
              {!repos.length && <div className="home-empty">No repositories have been added to the index.</div>}
            </div>
          </section>}

          {state.view === 'assistant' && <AIAssistant repos={repos} health={health} onOpenCitation={openCitation} />}

          {state.view === 'health' && <section className="management-view">
            <div className="search-view-heading"><div><span className="section-eyebrow">SYSTEM</span><h1>Index Health</h1>
              <p>Search and local AI status for this workspace.</p></div><span className="health-updated">Live status</span></div>
            <div className="health-grid">
              <div className="health-card"><span className={`health-icon ${health?.search_available ? 'good' : 'warn'}`}><Search size={19} /></span>
                <div><strong>Full-text search</strong><span>{health?.search_available ? 'Operational' : 'Unavailable'}</span></div><span className={`health-pill ${health?.search_available ? 'good' : 'warn'}`}>{health?.search_available ? 'READY' : 'CHECK'}</span></div>
              <div className="health-card"><span className={`health-icon ${health?.worker?.alive ? 'good' : 'warn'}`}><Activity size={19} /></span>
                <div><strong>Index worker</strong><span>{health?.worker?.alive ? `Online · seen ${health.worker.last_seen_s_ago}s ago` : 'Not responding'}</span></div><span className={`health-pill ${health?.worker?.alive ? 'good' : 'warn'}`}>{health?.worker?.paused ? 'PAUSED' : health?.worker?.alive ? 'ONLINE' : 'OFFLINE'}</span></div>
              <div className="health-card"><span className={`health-icon ${ai?.reachable && ai?.model_present ? 'good' : 'neutral'}`}><Sparkles size={19} /></span>
                <div><strong>Ollama</strong><span>{ai?.enabled ? ai?.reachable ? `${ai.version || 'Connected'} · ${ai.model || 'model'}` : 'Unavailable' : 'AI disabled'}</span></div><span className={`health-pill ${ai?.reachable && ai?.model_present ? 'good' : 'neutral'}`}>{ai?.reachable && ai?.model_present ? 'READY' : 'OPTIONAL'}</span></div>
            </div>
            <div className="health-note"><ShieldCheck size={18} /><div><strong>Search does not depend on AI</strong><p>Full-text and exact substring search continue to work when Ollama is unavailable or disabled.</p></div></div>
          </section>}
        </div>
      </div>
    </div>
  )
}
