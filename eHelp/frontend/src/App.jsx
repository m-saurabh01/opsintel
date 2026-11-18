import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { Link, NavLink, Route, Routes, useNavigate } from 'react-router-dom'
import { Home as HomeIcon, Layers, Menu, Search, Settings as SettingsIcon } from 'lucide-react'
import { api } from './api.js'
import { CategoryIcon } from './icons.jsx'
import Admin from './pages/Admin.jsx'
import Category from './pages/Category.jsx'
import DocumentPage from './pages/DocumentPage.jsx'
import Home from './pages/Home.jsx'
import SearchPage from './pages/SearchPage.jsx'

const AppContext = createContext(null)
export const useApp = () => useContext(AppContext)

export default function App() {
  const [settings, setSettings] = useState(null)
  const [me, setMe] = useState({ is_admin: false, name: '' })
  const [categories, setCategories] = useState([])
  const [collapsed, setCollapsed] = useState(false)
  const [filter, setFilter] = useState('')

  const refresh = useCallback(async () => {
    const [s, c] = await Promise.all([api.settings(), api.categories()])
    setSettings(s)
    setCategories(c)
  }, [])

  useEffect(() => {
    refresh().catch(() => {})
    api.me().then(setMe).catch(() => {})
  }, [refresh])

  useEffect(() => {
    if (!settings) return
    const root = document.documentElement.style
    root.setProperty('--accent', settings.accent_color)
    root.setProperty('--highlight', settings.highlight_color)
    root.setProperty('--sidebar', settings.sidebar_color)
    document.title = `${settings.app_name} – ${settings.subtitle}`
  }, [settings])

  const value = useMemo(() => ({ settings, me, categories, refresh }), [settings, me, categories, refresh])
  if (!settings) return <div className="boot">Loading…</div>

  const visible = categories.filter((c) => c.name.toLowerCase().includes(filter.trim().toLowerCase()))

  return (
    <AppContext.Provider value={value}>
      <div className={`shell${collapsed ? ' collapsed' : ''}`}>
        <header className="topbar">
          <button className="icon-btn" aria-label="Toggle sidebar" onClick={() => setCollapsed((c) => !c)}>
            <Menu size={22} />
          </button>
          <Link to="/" className="brand">
            <img src={settings.logo} alt="" />
            <span className="brand-name">{settings.app_name}</span>
          </Link>
          <span className="brand-sub">{settings.subtitle}</span>
          <span className="spacer" />
          {me.is_admin && (
            <Link to="/admin" className="admin-link"><SettingsIcon size={16} /> Admin</Link>
          )}
          {me.name && (
            <span className="user">
              <span className="avatar">{me.name.split(/\s+/).map((p) => p[0]).slice(0, 2).join('').toUpperCase()}</span>
              <span className="user-name">{me.name}</span>
            </span>
          )}
        </header>
        <aside className="sidebar">
          <div className="side-search">
            <Search size={16} />
            <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Search categories..." />
          </div>
          <nav>
            <NavLink to="/" end className="side-link"><HomeIcon size={18} /> Home</NavLink>
            <NavLink to="/documents" className="side-link"><Layers size={18} /> All Documents</NavLink>
            <NavLink to="/search" className="side-link"><Search size={18} /> Global Search</NavLink>
            <div className="side-title">DOCUMENT CATEGORIES</div>
            {visible.map((c) => (
              <NavLink key={c.id} to={`/category/${c.slug}`} className="side-link">
                <CategoryIcon name={c.icon} size={18} />
                <span className="side-name">{c.name}</span>
                <span className="count">{c.count}</span>
              </NavLink>
            ))}
          </nav>
        </aside>
        <main className="content">
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/search" element={<SearchPage />} />
            <Route path="/documents" element={<Category all />} />
            <Route path="/category/:slug" element={<Category />} />
            <Route path="/doc/:id" element={<DocumentPage />} />
            <Route path="/admin" element={<Admin />} />
            <Route path="*" element={<div className="page"><h2>Page not found</h2><Link to="/">Go home</Link></div>} />
          </Routes>
        </main>
      </div>
    </AppContext.Provider>
  )
}

export function useGoSearch() {
  const navigate = useNavigate()
  return (q, extra = {}) => {
    const sp = new URLSearchParams({ q, ...extra })
    navigate(`/search?${sp.toString()}`)
  }
}
