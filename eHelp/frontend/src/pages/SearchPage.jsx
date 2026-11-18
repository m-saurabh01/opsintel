import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Code, Download, ExternalLink, Search, Sparkles, X } from 'lucide-react'
import { useApp } from '../App.jsx'
import { api } from '../api.js'
import PdfViewer from '../components/PdfViewer.jsx'
import FilePreview from '../components/FilePreview.jsx'
import { FileIcon, FILE_TYPES, formatSize, Marked } from '../util.jsx'

const PAGE_SIZE = 10

export default function SearchPage() {
  const { categories } = useApp()
  const [params, setParams] = useSearchParams()
  const q = params.get('q') || ''
  const mode = params.get('mode') || 'smart'
  const category = params.get('category') || ''
  const type = params.get('type') || ''
  const page = Number(params.get('page') || 1)
  const [draft, setDraft] = useState(q)
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [selected, setSelected] = useState(null)

  useEffect(() => setDraft(q), [q])

  const set = (patch) => {
    const next = new URLSearchParams(params)
    Object.entries(patch).forEach(([k, v]) => (v ? next.set(k, v) : next.delete(k)))
    if (!('page' in patch)) next.delete('page')
    setParams(next)
  }

  useEffect(() => {
    if (!q) { setData(null); return undefined }
    let cancelled = false
    setError('')
    api.search({ q, mode, category, type, page, page_size: PAGE_SIZE })
      .then((d) => { if (!cancelled) { setData(d); setSelected(d.items[0] || null) } })
      .catch((e) => !cancelled && setError(e.message))
    return () => { cancelled = true }
  }, [q, mode, category, type, page])

  const pages = data ? Math.ceil(data.total / PAGE_SIZE) : 0
  const doc = selected?.document
  const previewPage = selected?.snippets?.find((s) => s.page)?.page || 1

  return (
    <div className="search-page">
      <div className="search-head">
        <span className="search-badge"><Search size={30} /></span>
        <div>
          <h1>Global Search</h1>
          <p>Search source documents and technical manuals across all indexed files.</p>
        </div>
      </div>
      <form className="search-bar" onSubmit={(e) => { e.preventDefault(); set({ q: draft.trim() }) }}>
        <Search size={18} />
        <input value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="Search documents..." autoFocus />
        {draft && <button type="button" className="icon-btn" aria-label="Clear" onClick={() => { setDraft(''); set({ q: '' }) }}><X size={16} /></button>}
        <button type="submit" className="go">Search</button>
      </form>
      <div className="filters">
        <select value={category} onChange={(e) => set({ category: e.target.value, q })}>
          <option value="">All Categories</option>
          {categories.map((c) => <option key={c.id} value={c.slug}>{c.name}</option>)}
        </select>
        <select value={type} onChange={(e) => set({ type: e.target.value, q })}>
          <option value="">All File Types</option>
          {FILE_TYPES.map((t) => <option key={t} value={t}>{t.toUpperCase()}</option>)}
        </select>
        <div className="seg">
          <button className={mode === 'smart' ? 'active' : ''} onClick={() => set({ mode: '', q })}><Sparkles size={14} /> Smart</button>
          <button className={mode === 'exact' ? 'active' : ''} onClick={() => set({ mode: 'exact', q })}><Code size={14} /> Exact Substring</button>
        </div>
      </div>
      {error && <div className="error">{error}</div>}
      {!q && <div className="empty">Type a word or phrase to search inside every indexed document.</div>}
      {data && (
        <div className="split">
          <div className="results">
            <div className="results-head"><b>Search Results</b><span>{data.total} documents · Page {page} of {Math.max(pages, 1)}</span></div>
            {data.items.length === 0 && <div className="empty">No documents matched “{q}”.</div>}
            {data.items.map((item) => (
              <div key={item.document.id} className={`result${selected?.document.id === item.document.id ? ' active' : ''}`}
                onClick={() => setSelected(item)}>
                <div className="result-top">
                  <FileIcon ext={item.document.ext} size={34} />
                  <div className="result-title">
                    <b>{item.document.title}</b>
                    <small>{[item.document.category, item.document.page_count && `${item.document.page_count} pages`, formatSize(item.document.size), item.matches && `${item.matches} matches`].filter(Boolean).join(' · ')}</small>
                  </div>
                  <Link className="btn small" to={`/doc/${item.document.id}${item.snippets[0]?.page ? `?page=${item.snippets[0].page}` : ''}`}
                    onClick={(e) => e.stopPropagation()}><ExternalLink size={14} /> Open</Link>
                </div>
                {item.snippets.map((s, i) => (
                  <div key={i} className="snippet"><span className="loc">{s.page ? `p.${s.page}` : s.label || '·'}</span><Marked text={s.text} /></div>
                ))}
              </div>
            ))}
            {pages > 1 && (
              <div className="pager">
                <button disabled={page <= 1} onClick={() => set({ page: String(page - 1), q })}>‹</button>
                <span>{page} / {pages}</span>
                <button disabled={page >= pages} onClick={() => set({ page: String(page + 1), q })}>›</button>
              </div>
            )}
          </div>
          <div className="preview">
            {doc ? (
              <>
                <div className="preview-head">
                  <FileIcon ext={doc.ext} size={32} />
                  <div><b>{doc.title}</b><small>{doc.category}{doc.page_count ? ` · ${doc.page_count} pages` : ''} · {formatSize(doc.size)}</small></div>
                </div>
                {doc.ext === 'pdf'
                  ? <PdfViewer key={`${doc.id}-${previewPage}`} compact url={api.fileUrl(doc.id)} downloadUrl={api.downloadUrl(doc.id)} page={previewPage} />
                  : (
                    <FilePreview key={doc.id} id={doc.id} ext={doc.ext} />
                  )}
              </>
            ) : <div className="empty">Select a result to preview it.</div>}
          </div>
        </div>
      )}
    </div>
  )
}
