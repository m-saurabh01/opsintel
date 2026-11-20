import { useEffect, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { Calendar, Filter, Grid2x2, List, Search, SortAsc } from 'lucide-react'
import { useApp } from '../App.jsx'
import { api } from '../api.js'
import { DocCard, DocRow } from '../components/DocList.jsx'
import Pager from '../components/Pager.jsx'
import { CategoryIcon } from '../icons.jsx'
import { bannerFor, FILE_TYPES } from '../util.jsx'

const SIZES = [12, 24, 48, 96]

export default function Category({ all = false }) {
  const { slug } = useParams()
  const { categories } = useApp()
  const [params, setParams] = useSearchParams()
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const category = all ? null : categories.find((c) => c.slug === slug)

  const sort = params.get('sort') || 'newest'
  const type = params.get('type') || ''
  const modified = params.get('modified') || ''
  const view = params.get('view') || 'grid'
  const page = Number(params.get('page') || 1)
  const pageSize = SIZES.includes(Number(params.get('size'))) ? Number(params.get('size')) : SIZES[0]
  const q = params.get('q') || ''
  const [draft, setDraft] = useState(q)

  useEffect(() => setDraft(q), [q, slug])

  const set = (patch) => {
    const next = new URLSearchParams(params)
    Object.entries(patch).forEach(([k, v]) => (v ? next.set(k, v) : next.delete(k)))
    if (!('page' in patch)) next.delete('page')
    setParams(next, { replace: true })
  }

  useEffect(() => {
    let cancelled = false
    setError('')
    api.documents({
      category: all ? undefined : slug, q, type, sort, modified_days: modified, page, page_size: pageSize,
    }).then((d) => !cancelled && setData(d)).catch((e) => !cancelled && setError(e.message))
    return () => { cancelled = true }
  }, [all, slug, q, type, sort, modified, page, pageSize])

  if (!all && categories.length && !category) {
    return <div className="page"><h2>Category not found</h2><Link to="/">Go home</Link></div>
  }

  const title = all ? 'All Documents' : category?.name

  return (
    <div className="category">
      <div className="cat-hero" style={{ backgroundImage: `linear-gradient(90deg, rgba(240,246,255,.92) 25%, rgba(240,246,255,0) 65%), url(${all ? '/img/afimg5.jpg' : bannerFor(category)})` }}>
        <div className="crumbs"><Link to="/">Home</Link> / <span>{all ? 'Documents' : 'Categories'}</span>{!all && <> / <b>{title}</b></>}</div>
        <div className="cat-title">
          <span className="cat-icon"><CategoryIcon name={all ? 'layers' : category?.icon} size={32} /></span>
          <div>
            <h1>{title}</h1>
            <p>{all ? 'Every document in the library.' : category?.description}</p>
          </div>
        </div>
      </div>
      <div className="tabs"><span className="tab active">Documents</span></div>
      <div className="toolbar">
        <form className="inline-search" onSubmit={(e) => { e.preventDefault(); set({ q: draft.trim() }) }}>
          <Search size={18} />
          <input value={draft} onChange={(e) => setDraft(e.target.value)} placeholder={`Search within ${title || ''}...`} />
        </form>
        <label className="select"><Filter size={16} />
          <select value={type} onChange={(e) => set({ type: e.target.value })}>
            <option value="">All types</option>
            {FILE_TYPES.map((t) => <option key={t} value={t}>{t.toUpperCase()}</option>)}
          </select>
        </label>
        <label className="select"><Calendar size={16} />
          <select value={modified} onChange={(e) => set({ modified: e.target.value })}>
            <option value="">Modified: any time</option>
            <option value="7">Last 7 days</option>
            <option value="30">Last 30 days</option>
            <option value="90">Last 90 days</option>
            <option value="365">Last year</option>
          </select>
        </label>
        <label className="select"><SortAsc size={16} />
          <select value={sort} onChange={(e) => set({ sort: e.target.value })}>
            <option value="newest">Sort: Newest</option>
            <option value="modified">Sort: Recently modified</option>
            <option value="oldest">Sort: Oldest</option>
            <option value="title">Sort: Title A–Z</option>
            <option value="popular">Sort: Most viewed</option>
            <option value="size">Sort: Largest</option>
          </select>
        </label>
        <div className="view-toggle">
          <button className={view === 'grid' ? 'active' : ''} aria-label="Grid view" onClick={() => set({ view: '' })}><Grid2x2 size={18} /></button>
          <button className={view === 'list' ? 'active' : ''} aria-label="List view" onClick={() => set({ view: 'list' })}><List size={18} /></button>
        </div>
      </div>
      {error && <div className="error">{error}</div>}
      {data?.items.length === 0 && <div className="empty">No documents match these filters.</div>}
      {view === 'grid'
        ? <div className="cards">{data?.items.map((d) => <DocCard key={d.id} doc={d} />)}</div>
        : <div className="panel list-panel">{data?.items.map((d) => <DocRow key={d.id} doc={d} showViews />)}</div>}
      <Pager page={page} total={data?.total || 0} pageSize={pageSize} sizes={SIZES} noun="documents"
        onPage={(p) => set({ page: String(p) })} onSize={(n) => set({ size: n === SIZES[0] ? '' : String(n) })} />
    </div>
  )
}
