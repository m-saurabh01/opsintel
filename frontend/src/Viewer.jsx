import { useEffect, useRef, useState } from 'react'
import { api } from './api.js'

const BEFORE = 40
const AFTER = 120
const MORE = 200

export default function Viewer({ fileId, line, onClose }) {
  const [meta, setMeta] = useState(null)
  const [lines, setLines] = useState([])
  const [range, setRange] = useState(null)
  const [error, setError] = useState('')
  const targetRef = useRef(null)

  useEffect(() => {
    let cancelled = false
    setError('')
    setLines([])
    const start = Math.max(1, line - BEFORE)
    Promise.all([api.file(fileId), api.lines(fileId, start, line + AFTER)])
      .then(([m, v]) => {
        if (cancelled) return
        setMeta(m)
        setLines(v.lines)
        setRange({ start: v.start, end: v.end, total: v.line_count })
      })
      .catch((e) => !cancelled && setError(e.message))
    return () => {
      cancelled = true
    }
  }, [fileId, line])

  useEffect(() => {
    targetRef.current?.scrollIntoView({ block: 'center' })
  }, [range?.total, fileId, line])

  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const loadEarlier = async () => {
    const start = Math.max(1, range.start - MORE)
    const v = await api.lines(fileId, start, range.start - 1)
    setLines((prev) => [...v.lines, ...prev])
    setRange((r) => ({ ...r, start }))
  }

  const loadLater = async () => {
    const v = await api.lines(fileId, range.end + 1, range.end + MORE)
    setLines((prev) => [...prev, ...v.lines])
    setRange((r) => ({ ...r, end: v.end }))
  }

  return (
    <aside className="viewer" aria-label="Source viewer">
      <div className="viewer-head">
        <div>
          <div className="path">{meta?.path || '…'}</div>
          {meta && (
            <div className="meta">
              {meta.repo_name}{meta.branch ? ` @ ${meta.branch}` : ''} · {meta.language || meta.file_type} ·{' '}
              {meta.line_count} lines · {meta.encoding} · indexed {meta.indexed_at} UTC
            </div>
          )}
        </div>
        <button onClick={onClose} title="Close (Esc)">Close</button>
      </div>
      {error && <div className="error" role="alert">{error}</div>}
      {range && (
        <div className="code">
          {range.start > 1 && <button className="more" onClick={loadEarlier}>Load earlier lines</button>}
          <pre>
            {lines.map((l) => (
              <div key={l.line} ref={l.line === line ? targetRef : null} className={l.line === line ? 'target' : ''}>
                <span className="ln">{l.line}</span>
                {l.text || ' '}
              </div>
            ))}
          </pre>
          {range.end < range.total && <button className="more" onClick={loadLater}>Load later lines</button>}
        </div>
      )}
    </aside>
  )
}
