import { useEffect, useRef, useState } from 'react'
import { api } from '../api.js'
import TextViewer from './TextViewer.jsx'

const SHEET = new Set(['xlsx', 'xls', 'xlsm', 'ods'])
const DELIM = new Set(['csv', 'tsv'])
const PLAIN = new Set(['txt', 'md', 'log', 'json', 'xml', 'yml', 'yaml', 'ini', 'properties', 'sql', 'sh', 'bat',
  'py', 'java', 'js', 'jsx', 'ts', 'html', 'htm', 'css', 'jsp', 'conf', 'cfg'])
const MAX_ROWS = 2000
const MAX_PLAIN = 2_000_000

async function fetchBuffer(id) {
  const res = await fetch(api.fileUrl(id))
  if (!res.ok) throw new Error(`Could not load file (${res.status})`)
  return res.arrayBuffer()
}

function Grid({ rows }) {
  const shown = rows.slice(0, MAX_ROWS)
  const cols = shown.reduce((m, r) => Math.max(m, r.length), 0)
  if (!shown.length) return <div className="empty">This sheet is empty.</div>
  return (
    <div className="grid-wrap">
      <table className="grid">
        <thead>
          <tr><th className="rownum" />{Array.from({ length: cols }, (_, i) => <th key={i}>{colName(i)}</th>)}</tr>
        </thead>
        <tbody>
          {shown.map((r, i) => (
            <tr key={i}>
              <th className="rownum">{i + 1}</th>
              {Array.from({ length: cols }, (_, c) => <td key={c}>{r[c] ?? ''}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > MAX_ROWS && <p className="grid-note">Showing the first {MAX_ROWS} of {rows.length} rows. Download for the full file.</p>}
    </div>
  )
}

function colName(i) {
  let s = ''
  for (let n = i + 1; n > 0; n = Math.floor((n - 1) / 26)) s = String.fromCharCode(65 + ((n - 1) % 26)) + s
  return s
}

function Sheets({ id, ext }) {
  const [sheets, setSheets] = useState(null)
  const [active, setActive] = useState(0)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    setSheets(null); setActive(0); setError('')
    ;(async () => {
      try {
        const buf = await fetchBuffer(id)
        if (DELIM.has(ext)) {
          const Papa = (await import('papaparse')).default
          const text = new TextDecoder().decode(buf)
          const { data } = Papa.parse(text, { skipEmptyLines: true })
          if (!cancelled) setSheets([{ name: ext.toUpperCase(), rows: data }])
        } else {
          const XLSX = await import('xlsx')
          const wb = XLSX.read(buf, { type: 'array', cellDates: true })
          const out = wb.SheetNames.map((name) => ({
            name,
            rows: XLSX.utils.sheet_to_json(wb.Sheets[name], { header: 1, raw: false, defval: '', blankrows: false }),
          }))
          if (!cancelled) setSheets(out)
        }
      } catch (e) {
        if (!cancelled) setError(e.message || 'Could not render this spreadsheet.')
      }
    })()
    return () => { cancelled = true }
  }, [id, ext])

  if (error) return <Fallback id={id} reason={error} />
  if (!sheets) return <div className="empty">Loading preview…</div>
  return (
    <div className="file-preview">
      {sheets.length > 1 && (
        <div className="sheet-tabs">
          {sheets.map((s, i) => (
            <button key={s.name} className={i === active ? 'on' : ''} onClick={() => setActive(i)}>{s.name}</button>
          ))}
        </div>
      )}
      <Grid rows={sheets[active].rows} />
    </div>
  )
}

function Docx({ id }) {
  const host = useRef(null)
  const [state, setState] = useState('loading')
  useEffect(() => {
    let cancelled = false
    setState('loading')
    ;(async () => {
      try {
        const [buf, { renderAsync }] = await Promise.all([fetchBuffer(id), import('docx-preview')])
        if (cancelled || !host.current) return
        host.current.innerHTML = ''
        await renderAsync(buf, host.current, undefined, {
          inWrapper: true, ignoreWidth: false, breakPages: true, experimental: true,
        })
        if (!cancelled) setState('ok')
      } catch {
        if (!cancelled) setState('error')
      }
    })()
    return () => { cancelled = true }
  }, [id])
  return (
    <>
      {state === 'error' && <Fallback id={id} reason="This document could not be rendered." />}
      {state === 'loading' && <div className="empty">Loading preview…</div>}
      <div ref={host} className="docx-host" hidden={state !== 'ok'} />
    </>
  )
}

function Pptx({ id }) {
  const host = useRef(null)
  const [state, setState] = useState('loading')
  useEffect(() => {
    let cancelled = false
    setState('loading')
    ;(async () => {
      try {
        const [buf, mod] = await Promise.all([fetchBuffer(id), import('pptx-preview')])
        if (cancelled || !host.current) return
        host.current.innerHTML = ''
        const width = Math.max(480, Math.min(host.current.clientWidth || 900, 1100))
        const viewer = mod.init(host.current, { width, height: Math.round(width * 9 / 16), mode: 'list' })
        await viewer.preview(buf)
        if (!cancelled) setState('ok')
      } catch {
        if (!cancelled) setState('error')
      }
    })()
    return () => { cancelled = true }
  }, [id])
  return (
    <>
      {state === 'error' && <Fallback id={id} reason="This presentation could not be rendered faithfully." />}
      {state === 'loading' && <div className="empty">Loading preview…</div>}
      <div ref={host} className="pptx-host" hidden={state !== 'ok'} />
    </>
  )
}

function Plain({ id }) {
  const [text, setText] = useState(null)
  const [error, setError] = useState('')
  useEffect(() => {
    let cancelled = false
    setText(null); setError('')
    fetchBuffer(id)
      .then((buf) => {
        if (cancelled) return
        const slice = buf.byteLength > MAX_PLAIN ? buf.slice(0, MAX_PLAIN) : buf
        const t = new TextDecoder().decode(slice)
        setText(buf.byteLength > MAX_PLAIN ? `${t}\n\n… truncated, download for the full file` : t)
      })
      .catch((e) => !cancelled && setError(e.message))
    return () => { cancelled = true }
  }, [id])
  if (error) return <Fallback id={id} reason={error} />
  if (text === null) return <div className="empty">Loading preview…</div>
  return <pre className="plain-view">{text}</pre>
}

function Fallback({ id, reason }) {
  return (
    <div className="file-preview">
      <div className="preview-note">{reason} Showing extracted text instead.</div>
      <TextViewer id={id} />
    </div>
  )
}

export default function FilePreview({ id, ext }) {
  const e = (ext || '').toLowerCase()
  let body
  if (SHEET.has(e) || DELIM.has(e)) body = <Sheets id={id} ext={e} />
  else if (e === 'docx') body = <Docx id={id} />
  else if (e === 'pptx') body = <Pptx id={id} />
  else if (PLAIN.has(e)) body = <Plain id={id} />
  else body = <TextViewer id={id} />
  return <div className="file-viewer">{body}</div>
}
