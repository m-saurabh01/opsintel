import { useEffect, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { Calendar, Download, ExternalLink, Eye, FileText } from 'lucide-react'
import { api } from '../api.js'
import PdfViewer from '../components/PdfViewer.jsx'
import FilePreview from '../components/FilePreview.jsx'
import { FileIcon, formatDate, isVideo, formatSize, termsOf } from '../util.jsx'

export default function DocumentPage() {
  const { id } = useParams()
  const [params] = useSearchParams()
  const [doc, setDoc] = useState(null)
  const [related, setRelated] = useState([])
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    setDoc(null)
    setError('')
    api.document(id).then((d) => !cancelled && setDoc(d)).catch((e) => !cancelled && setError(e.message))
    api.related(id).then((r) => !cancelled && setRelated(r.items)).catch(() => {})
    const key = `viewed:${id}`
    if (!sessionStorage.getItem(key)) {
      sessionStorage.setItem(key, '1')
      api.recordView(id)
    }
    return () => { cancelled = true }
  }, [id])

  if (error) return <div className="page"><div className="error">{error}</div><Link to="/">Go home</Link></div>
  if (!doc) return <div className="page muted">Loading…</div>

  const isPdf = doc.ext === 'pdf'
  const canOpen = isPdf || isVideo(doc.ext)
  const page = Number(params.get('page') || 1)
  const terms = termsOf(params.get('q'), params.get('mode'))

  return (
    <div className="doc-page">
      <div className="crumbs">
        <Link to="/">Home</Link> /{' '}
        {doc.category ? <Link to={`/category/${doc.category_slug}`}>{doc.category}</Link> : <Link to="/documents">Documents</Link>}
        {' '}/ <b>{doc.title}</b>
      </div>
      <div className="doc-head">
        <FileIcon ext={doc.ext} size={56} />
        <div className="doc-head-main">
          <h1>{doc.title}{doc.revision ? ` – ${doc.revision}` : ''}</h1>
          <div className="doc-badges">
            {doc.category && <span className="badge">{doc.category}</span>}
            <span><FileText size={15} /> {formatSize(doc.size)}</span>
            <span><Calendar size={15} /> {formatDate(doc.created_at)}</span>
            <span><Eye size={15} /> {doc.views.toLocaleString()} views</span>
          </div>
        </div>
        <div className="doc-actions">
          {canOpen && (
            <a className="btn primary" href={isPdf ? `${api.fileUrl(doc.id)}#page=${page}` : api.fileUrl(doc.id)} target="_blank" rel="noreferrer">
              <ExternalLink size={16} /> Open in New Tab
            </a>
          )}
          <a className={`btn${canOpen ? '' : ' primary'}`} href={api.downloadUrl(doc.id)}><Download size={16} /> Download</a>
        </div>
      </div>
      <div className="doc-layout">
        <div className="viewer-col">
          {isPdf
            ? <PdfViewer url={api.fileUrl(doc.id)} downloadUrl={api.downloadUrl(doc.id)} page={page} terms={terms} />
            : <FilePreview key={doc.id} id={doc.id} ext={doc.ext} terms={terms} />}
        </div>
        <aside className="info-col">
          <div className="panel">
            <div className="panel-head"><h3>Document Information</h3></div>
            <dl className="info">
              <dt>Category</dt><dd>{doc.category || '—'}</dd>
              <dt>Document Type</dt><dd>{doc.ext.toUpperCase()}</dd>
              <dt>File Size</dt><dd>{formatSize(doc.size)}</dd>
              <dt>Last Modified</dt><dd>{formatDate(doc.updated_at, true)}</dd>
              {doc.revision && <><dt>Revision</dt><dd>{doc.revision}</dd></>}
              {doc.page_count && <><dt>Pages</dt><dd>{doc.page_count}</dd></>}
            </dl>
            {doc.description && <p className="desc">{doc.description}</p>}
            {doc.tags.length > 0 && <div className="tags pad">{doc.tags.map((t) => <span key={t} className="tag">{t}</span>)}</div>}
          </div>
          <div className="panel">
            <div className="panel-head">
              <h3>Related Documents</h3>
              {doc.category && <Link to={`/category/${doc.category_slug}`}>View All →</Link>}
            </div>
            {related.length === 0 && <p className="muted pad">No related documents.</p>}
            {related.map((r) => (
              <div key={r.id} className="related-row">
                <Link to={`/doc/${r.id}`} className="doc-row">
                  <FileIcon ext={r.ext} size={34} />
                  <span className="doc-row-main"><b>{r.title}</b><small>{formatSize(r.size)} · {formatDate(r.created_at)}</small></span>
                </Link>
                <a className="icon-btn" href={(r.ext === 'pdf' || isVideo(r.ext)) ? api.fileUrl(r.id) : api.downloadUrl(r.id)}
                  target={(r.ext === 'pdf' || isVideo(r.ext)) ? '_blank' : undefined} rel="noreferrer"
                  aria-label={(r.ext === 'pdf' || isVideo(r.ext)) ? 'Open in new tab' : 'Download'}>
                  {(r.ext === 'pdf' || isVideo(r.ext)) ? <ExternalLink size={16} /> : <Download size={16} />}
                </a>
              </div>
            ))}
          </div>
        </aside>
      </div>
    </div>
  )
}
