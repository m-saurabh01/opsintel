import { Link } from 'react-router-dom'
import { Eye, MoreVertical } from 'lucide-react'
import { FileIcon, formatDate, formatSize } from '../util.jsx'

export function DocRow({ doc, showViews }) {
  return (
    <Link to={`/doc/${doc.id}`} className="doc-row">
      <FileIcon ext={doc.ext} size={36} />
      <span className="doc-row-main">
        <b>{doc.title}</b>
        <small>{[doc.category, formatSize(doc.size), formatDate(doc.created_at)].filter(Boolean).join(' · ')}</small>
      </span>
      {showViews && doc.views > 0 && <span className="pill"><Eye size={14} /> {doc.views}</span>}
      {!showViews && <MoreVertical size={16} className="muted" />}
    </Link>
  )
}

export function DocCard({ doc }) {
  return (
    <Link to={`/doc/${doc.id}`} className="doc-card">
      <div className="doc-card-head">
        <FileIcon ext={doc.ext} />
        <h3>{doc.title}{doc.revision ? ` ${doc.revision}` : ''}</h3>
      </div>
      <div className="doc-meta">
        <span>{formatSize(doc.size)}</span>
        <span>{formatDate(doc.created_at)}</span>
        {doc.page_count ? <span>{doc.page_count} pages</span> : null}
      </div>
      {doc.description && <p>{doc.description}</p>}
      <div className="tags">{doc.tags.slice(0, 4).map((t) => <span key={t} className="tag">{t}</span>)}</div>
    </Link>
  )
}
