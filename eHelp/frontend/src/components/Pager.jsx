import { ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight } from 'lucide-react'

function pageItems(page, pages) {
  const items = []
  for (let p = 1; p <= pages; p += 1) {
    if (p === 1 || p === pages || Math.abs(p - page) <= 1) items.push(p)
    else if (items[items.length - 1] !== '…') items.push('…')
  }
  return items
}

// Footer with range summary, page-size picker and page buttons. Renders nothing for an empty list.
export default function Pager({ page, total, pageSize, onPage, onSize, sizes, noun = 'items' }) {
  if (!total) return null
  const pages = Math.max(1, Math.ceil(total / pageSize))
  const from = (page - 1) * pageSize + 1
  const to = Math.min(page * pageSize, total)
  return (
    <div className="footer-row">
      <span className="muted">Showing {from}–{to} of {total.toLocaleString()} {noun}</span>
      {onSize && sizes && (
        <label className="size-pick">Per page
          <select value={pageSize} onChange={(e) => onSize(Number(e.target.value))}>
            {sizes.map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
        </label>
      )}
      {pages > 1 && (
        <div className="pager">
          <button aria-label="First page" disabled={page <= 1} onClick={() => onPage(1)}><ChevronsLeft size={16} /></button>
          <button aria-label="Previous page" disabled={page <= 1} onClick={() => onPage(page - 1)}><ChevronLeft size={16} /></button>
          {pageItems(page, pages).map((p, i) => (p === '…'
            ? <span key={`g${i}`}>…</span>
            : <button key={p} className={p === page ? 'active' : ''} aria-current={p === page ? 'page' : undefined} onClick={() => onPage(p)}>{p}</button>))}
          <button aria-label="Next page" disabled={page >= pages} onClick={() => onPage(page + 1)}><ChevronRight size={16} /></button>
          <button aria-label="Last page" disabled={page >= pages} onClick={() => onPage(pages)}><ChevronsRight size={16} /></button>
        </div>
      )}
    </div>
  )
}
