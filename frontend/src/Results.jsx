import { useEffect, useRef, useState } from 'react'
import { ExternalLink } from 'lucide-react'

function HighlightedText({ text, highlights }) {
  if (!highlights?.length) return text
  const parts = []
  let pos = 0
  highlights.forEach(([s, e], i) => {
    if (s > pos) parts.push(text.slice(pos, s))
    parts.push(<mark key={i}>{text.slice(s, e)}</mark>)
    pos = e
  })
  if (pos < text.length) parts.push(text.slice(pos))
  return parts
}

export function locationLabel(loc) {
  switch (loc.kind) {
    case 'line':
      return `line ${loc.line}`
    case 'page':
      return `page ${loc.page}${loc.section ? ` · ${loc.section}` : ''}`
    case 'section':
      return [loc.section, loc.table ? `table ${loc.table}, row ${loc.table_row}` : loc.paragraph && `paragraph ${loc.paragraph}`]
        .filter(Boolean).join(' · ')
    case 'cell':
      return `${loc.sheet} ! ${loc.cell || ''}${loc.header ? ` (${loc.header})` : ''}`
    case 'row':
      return `row ${loc.row}${loc.column ? ` · ${loc.column}` : ''}`
    default:
      return loc.kind
  }
}

export function openTarget(r) {
  const hit = r.preview.find((p) => p.highlights.length) || r.preview[0]
  if (r.location.kind === 'line') return { fileId: r.file_id, line: r.location.line }
  if (r.location.kind === 'page') {
    return { fileId: r.file_id, chunk: r.chunk_id, mark: hit ? hit.index : 0, page: r.location.page, pdf: true }
  }
  return {
    fileId: r.file_id,
    chunk: r.chunk_id,
    mark: hit ? hit.index : 0,
    cell: r.location.kind === 'cell' ? r.location.cell : undefined,
  }
}

function sameTarget(a, b) {
  return a && b && a.fileId === b.fileId && a.line === b.line && a.chunk === b.chunk && a.pdf === b.pdf
}

export default function Results({ result, selected, onOpen, onPage, pageSize }) {
  const [focus, setFocus] = useState(0)
  const listRef = useRef(null)
  const { results, total, page } = result
  const pages = Math.ceil(total / pageSize)

  useEffect(() => setFocus(0), [result])

  useEffect(() => {
    listRef.current?.querySelectorAll('.result')[focus]?.scrollIntoView({ block: 'nearest' })
  }, [focus])

  const onKeyDown = (e) => {
    if (e.key === 'ArrowDown' || e.key === 'j') {
      e.preventDefault()
      setFocus((f) => Math.min(f + 1, results.length - 1))
    } else if (e.key === 'ArrowUp' || e.key === 'k') {
      e.preventDefault()
      setFocus((f) => Math.max(f - 1, 0))
    } else if (e.key === 'Enter' && results[focus]) {
      onOpen(openTarget(results[focus]))
    }
  }

  if (!results.length) {
    return (
      <div className="empty">
        No matches for <b>{result.query}</b>. Try a shorter query or remove filters.
      </div>
    )
  }

  const counts = [
    `${result.match_total ?? total}${result.match_total_is_lower_bound ? '+' : ''} matches`,
    result.related_total ? `${result.related_total}${result.related_truncated ? '+' : ''} related` : null,
    result.substring_total ? `${result.substring_total}${result.substring_total_is_lower_bound ? '+' : ''} substring` : null,
  ].filter(Boolean).join(' · ')

  return (
    <>
      <div className="muted summary">
        {counts} · page {page} of {pages || 1}
        <span className="hint"> · ↑/↓ to move, Enter to open</span>
      </div>
      <ol className="result-list" ref={listRef} tabIndex={0} onKeyDown={onKeyDown} aria-label="Search results">
        {results.map((r, i) => {
          const target = openTarget(r)
          const isOpen = sameTarget(selected, target)
          return (
            <li
              key={r.chunk_id}
              className={`result ${i === focus ? 'focused' : ''} ${isOpen ? 'open' : ''}`}
              onClick={() => {
                setFocus(i)
                onOpen(target)
              }}
            >
              <div className="result-head">
                <span className="path" title={r.path}>{r.path}</span>
                <span className="loc">{locationLabel(r.location)}</span>
                {r.source_url && (
                  <a
                    className="gitea-link"
                    href={r.source_url}
                    target="_blank"
                    rel="noreferrer"
                    title="Open this result in Gitea"
                    onClick={(event) => event.stopPropagation()}
                  >
                    <ExternalLink size={12} aria-hidden="true" />
                    Gitea
                  </a>
                )}
              </div>
              <div className="meta">
                {r.repo.name}{r.branch ? ` @ ${r.branch}` : ''}{r.commit_sha ? ` (${r.commit_sha.slice(0, 8)})` : ''}
                {' · '}{r.file_type}{r.language ? `/${r.language}` : ''}
                {r.match_count > 1 ? ` · ${r.match_count} matching lines` : ''}
                {r.match_type === 'related' && <span className="result-kind related-kind">Related</span>}
                {r.match_type === 'substring' && <span className="result-kind substring-kind">Substring</span>}
              </div>
              <pre className="preview">
                {r.preview.map((p, k) => (
                  <div key={k} className={p.highlights.length ? 'hit' : ''}>
                    <span className="ln">{p.label}</span>
                    <HighlightedText text={p.text} highlights={p.highlights} />
                  </div>
                ))}
              </pre>
            </li>
          )
        })}
      </ol>
      {pages > 1 && (
        <nav className="pager">
          <button disabled={page <= 1} onClick={() => onPage(page - 1)}>Previous</button>
          <span>{page} / {pages}</span>
          <button disabled={page >= pages} onClick={() => onPage(page + 1)}>Next</button>
        </nav>
      )}
    </>
  )
}
