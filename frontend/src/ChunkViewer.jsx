import { Fragment, useEffect, useMemo, useRef, useState } from 'react'
import { api } from './api.js'

const KIND_TITLE = { page: 'PDF', section: 'Document', cell: 'Spreadsheet', row: 'Delimited data' }

function HeaderRow({ extra, kind }) {
  if (kind === 'cell' && extra.headers && Object.keys(extra.headers).length) {
    return (
      <div className="headers">
        Columns: {Object.entries(extra.headers).map(([col, name]) => <span key={col}><b>{col}</b> {name}</span>)}
      </div>
    )
  }
  if (kind === 'row' && extra.headers?.length) {
    return (
      <div className="headers">
        Columns: {extra.headers.map((name, i) => <span key={i}><b>{i + 1}</b> {name}</span>)}
      </div>
    )
  }
  return null
}

function SpreadsheetGrid({ data, target, cell }) {
  const [activeSheet, setActiveSheet] = useState('')
  const [activeCell, setActiveCell] = useState(cell || '')
  const cellRefs = useRef(new Map())
  const sheets = useMemo(() => [...new Set(data.chunks
    .filter((chunk) => chunk.location.kind === 'cell')
    .map((chunk) => chunk.location.sheet))], [data])

  useEffect(() => {
    setActiveSheet(target?.location.sheet || sheets[0] || '')
    setActiveCell(cell || '')
  }, [target?.location.sheet, cell, sheets])

  const columns = useMemo(() => {
    const headers = {}
    for (const chunk of data.chunks) {
      if (chunk.location.kind === 'cell' && chunk.location.sheet === activeSheet) {
        Object.assign(headers, chunk.extra.headers || {})
      }
    }
    return Object.entries(headers).sort(([a], [b]) => a.localeCompare(b, undefined, { numeric: true }))
  }, [data, activeSheet])

  const rows = useMemo(() => {
    const grouped = new Map()
    for (const chunk of data.chunks) {
      if (chunk.location.kind !== 'cell' || chunk.location.sheet !== activeSheet) continue
      for (const line of chunk.lines) {
        const row = new Map(line.cells.map((item) => [item.column, item]))
        if (row.size) grouped.set(line.cells[0].row, row)
      }
    }
    return [...grouped.entries()].sort(([a], [b]) => a - b)
  }, [data, activeSheet])

  const moveFocus = (event, rowIndex, columnIndex) => {
    const delta = { ArrowRight: [0, 1], ArrowLeft: [0, -1], ArrowDown: [1, 0], ArrowUp: [-1, 0] }[event.key]
    if (!delta) return
    let row = rows[rowIndex + delta[0]]
    if (delta[0] === 0) row = rows[rowIndex]
    if (!row) return
    event.preventDefault()
    for (let colIndex = columnIndex + delta[1]; colIndex >= 0 && colIndex < columns.length; colIndex += delta[1]) {
      const next = row[1].get(columns[colIndex][0])
      if (next) {
        setActiveCell(next.cell)
        cellRefs.current.get(next.cell)?.focus()
        return
      }
    }
  }

  return (
    <div className="sheet-view">
      {sheets.length > 1 && (
        <div className="sheet-tabs" role="tablist" aria-label="Workbook sheets">
          {sheets.map((sheet) => (
            <button key={sheet} role="tab" aria-selected={activeSheet === sheet}
              className={activeSheet === sheet ? 'selected' : ''} onClick={() => setActiveSheet(sheet)}>
              {sheet}
            </button>
          ))}
        </div>
      )}
      {columns.length > 0 && rows.length > 0 ? (
        <div className="sheet-grid-scroll">
          <table className="sheet-grid" role="grid" aria-label={`${activeSheet} spreadsheet`}>
            <thead>
              <tr><th className="row-index" scope="col">#</th>
                {columns.map(([column, name]) => <th key={column} scope="col"><span>{column}</span>{name}</th>)}
              </tr>
            </thead>
            <tbody>
              {rows.map(([rowNumber, row], rowIndex) => (
                <tr key={rowNumber}>
                  <th className="row-index" scope="row">{rowNumber}</th>
                  {columns.map(([column], columnIndex) => {
                    const item = row.get(column)
                    if (!item) return <td key={column} />
                    const selected = activeCell === item.cell
                    const match = cell === item.cell
                    return (
                      <td key={column} className={`${match ? 'search-hit' : ''} ${selected ? 'cell-selected' : ''}`}>
                        <button
                          ref={(node) => node ? cellRefs.current.set(item.cell, node) : cellRefs.current.delete(item.cell)}
                          className="cell-value"
                          aria-label={`${item.cell}, ${item.header || column}: ${item.value}`}
                          aria-current={match ? 'location' : undefined}
                          onFocus={() => setActiveCell(item.cell)}
                          onKeyDown={(event) => moveFocus(event, rowIndex, columnIndex)}
                        >
                          {item.value || <span className="empty-cell">&nbsp;</span>}
                        </button>
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <div className="viewer-message">No cell data in this sheet context.</div>}
    </div>
  )
}

export default function ChunkViewer({ fileId, chunkId, mark, cell, onClose, closeLabel = 'Close' }) {
  const [data, setData] = useState(null)
  const [activeSheet, setActiveSheet] = useState('')
  const [error, setError] = useState('')
  const targetRef = useRef(null)

  useEffect(() => {
    let cancelled = false
    setError('')
    setData(null)
    api.chunk(fileId, chunkId, 1, cell)
      .then((d) => !cancelled && setData(d))
      .catch((e) => !cancelled && setError(e.message))
    return () => {
      cancelled = true
    }
  }, [fileId, chunkId, cell])

  useEffect(() => {
    targetRef.current?.scrollIntoView({ block: 'center' })
  }, [data])

  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const target = data?.chunks.find((c) => c.is_target)
  const kind = target?.location.kind

  return (
    <aside className="viewer" aria-label="Document viewer">
      <div className="viewer-head">
        <div>
          <div className="path">{data?.path || '…'}</div>
          {data && (
            <div className="meta">
              {data.repo_name} · {KIND_TITLE[kind] || data.file_type} ({data.language}) · section{' '}
              {target ? target.ordinal + 1 : '?'} of {data.chunk_count}
            </div>
          )}
        </div>
        <button onClick={onClose} title="Return to previous view (Esc)">{closeLabel}</button>
      </div>
      {error && <div className="error" role="alert">{error}</div>}
      {data && (
        ['xlsx', 'xlsm', 'xls', 'ods'].includes(data.language)
          ? <SpreadsheetGrid data={data} target={target} cell={cell || data.target_cell} />
          : <div className="code">
              {data.chunks.map((c) => (
                <Fragment key={c.chunk_id}>
                  <div className={`chunk-head ${c.is_target ? 'target-chunk' : ''}`}>{c.heading}</div>
                  {c.is_target && <HeaderRow extra={c.extra} kind={c.location.kind} />}
                  <pre>
                    {c.lines.map((l, i) => {
                      const isMark = c.is_target && i === mark
                      return (
                        <div key={i} ref={isMark ? targetRef : null} className={isMark ? 'target' : ''}>
                          <span className="ln">{l.label}</span>
                          {l.text || ' '}
                        </div>
                      )
                    })}
                  </pre>
                </Fragment>
              ))}
            </div>
      )}
    </aside>
  )
}
