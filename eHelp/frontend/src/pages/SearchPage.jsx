import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Code, Download, PanelRightClose, PanelRightOpen, ExternalLink, Search, Sparkles, X } from 'lucide-react'
import { useApp } from '../App.jsx'
import { api } from '../api.js'
import PdfViewer from '../components/PdfViewer.jsx'
import FilePreview from '../components/FilePreview.jsx'
import PageBanner from '../components/PageBanner.jsx'
import Pager from '../components/Pager.jsx'
import { FileIcon, FILE_TYPES, formatSize, Marked, termsOf } from '../util.jsx'

const SIZES = [10, 20, 50]

export default function SearchPage() {
  const { categories } = useApp()
  const [params, setParams] = useSearchParams()
  const q = params.get('q') || ''
  const mode = params.get('mode') || 'smart'
  const category = params.get('category') || ''
  const type = params.get('type') || ''
  const page = Number(params.get('page') || 1)
  const pageSize = SIZES.includes(Number(params.get('size'))) ? Number(params.get('size')) : SIZES[0]
  const [draft, setDraft] = useState(q)
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [selected, setSelected] = useState(null)
  const [pickedPage, setPickedPage] = useState(0)
  const [showPreview, setShowPreview] = useState(true)
  const terms = termsOf(q, mode)
  const termKey = terms.join('|')

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
    api.search({ q, mode, category, type, page, page_size: pageSize })
      .then((d) => { if (!cancelled) { setData(d); setSelected(d.items[0] || null); setPickedPage(0) } })
      .catch((e) => !cancelled && setError(e.message))
    return () => { cancelled = true }
  }, [q, mode, category, type, page, pageSize])

  const doc = selected?.document
  const previewPage = pickedPage || selected?.snippets?.find((s) => s.page)?.page || 1
  const choose = (item, pg = 0) => { setSelected(item); setPickedPage(pg) }

  useEffect(() => {
    const onKey = (e) => {
      if (!data || !['ArrowDown', 'ArrowUp'].includes(e.key)) return
      if (['INPUT', 'SELECT', 'TEXTAREA'].includes(document.activeElement?.tagName)) return
      e.preventDefault()
      const i = data.items.findIndex((x) => x.document.id === selected?.document.id)
      const n = Math.min(Math.max(i + (e.key === 'ArrowDown' ? 1 : -1), 0), data.items.length - 1)
      if (data.items[n]) choose(data.items[n])
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className={`search-page${q ? '' : ' landing'}`}>
      {q ? (
        <PageBanner image="/img/tejas3.jpg" icon={<Search size={32} />} title="Global Search">
          Search source documents and technical manuals across all indexed files.
        </PageBanner>
      ) : (
        <div className="landing-head">
          <div className="banner-icon"><Search size={36} /></div>
          <div className="banner-text">
            <h1>Global Search</h1>
            <p>Search source documents and technical manuals across all indexed files.</p>
          </div>
        </div>
      )}
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
      {data && (
        <div className={`split${showPreview ? '' : ' solo'}`}>
          <div className="results">
            <div className="eyebrow">Query results</div>
            <div className="results-head">
              <b>{data.total} document{data.total === 1 ? '' : 's'}</b>
              <span className="hint">↑/↓ to move · click a snippet to jump</span>
              <button type="button" className="icon-btn" title={showPreview ? 'Hide preview' : 'Show preview'}
                onClick={() => setShowPreview((v) => !v)}>
                {showPreview ? <PanelRightClose size={18} /> : <PanelRightOpen size={18} />}
              </button>
            </div>
            {data.items.length === 0 && <div className="empty">No documents matched “{q}”.</div>}
            {data.items.map((item) => (
              <div key={item.document.id} className={`result${selected?.document.id === item.document.id ? ' active' : ''}`}
                onClick={() => choose(item)}>
                <div className="result-top">
                  <FileIcon ext={item.document.ext} size={34} />
                  <div className="result-title">
                    <b>{item.document.title}</b>
                    <small>{[item.document.category, item.document.page_count && `${item.document.page_count} pages`, formatSize(item.document.size), item.matches && `${item.matches} matches`].filter(Boolean).join(' · ')}</small>
                  </div>
                  <Link className="btn small" to={`/doc/${item.document.id}?${new URLSearchParams({ ...(item.snippets[0]?.page ? { page: item.snippets[0].page } : {}), q, mode }).toString()}`}
                    onClick={(e) => e.stopPropagation()}><ExternalLink size={14} /> Open</Link>
                </div>
                {item.snippets.map((s, i) => (
                  <button key={i} type="button" className="snippet"
                    onClick={(e) => { e.stopPropagation(); choose(item, s.page || 0) }}>
                    <span className="loc">{s.page ? `p.${s.page}` : s.label || 'match'}</span>
                    <Marked text={s.text} />
                  </button>
                ))}
              </div>
            ))}
            <Pager page={page} total={data.total} pageSize={pageSize} sizes={SIZES} noun="documents"
              onPage={(p) => set({ page: String(p), q })} onSize={(n) => set({ size: n === SIZES[0] ? '' : String(n), q })} />
          </div>
          <div className="preview" hidden={!showPreview}>
            {doc ? (
              <>
                <div className="preview-head">
                  <FileIcon ext={doc.ext} size={32} />
                  <div className="preview-title"><b>{doc.title}</b><small>{doc.category}{doc.page_count ? ` · ${doc.page_count} pages` : ''} · {formatSize(doc.size)}</small></div>
                  <Link className="btn small" to={`/doc/${doc.id}?${new URLSearchParams({ page: previewPage, q, mode })}`}><ExternalLink size={14} /> Open</Link>
                  <a className="btn small" href={api.downloadUrl(doc.id)}><Download size={14} /></a>
                </div>
                {doc.ext === 'pdf'
                  ? <PdfViewer key={doc.id} compact terms={terms} url={api.fileUrl(doc.id)} downloadUrl={api.downloadUrl(doc.id)} page={previewPage} />
                  : (
                    <FilePreview key={`${doc.id}|${termKey}`} id={doc.id} ext={doc.ext} terms={terms} />
                  )}
              </>
            ) : <div className="empty">Select a result to preview it.</div>}
          </div>
        </div>
      )}
    </div>
  )
}
