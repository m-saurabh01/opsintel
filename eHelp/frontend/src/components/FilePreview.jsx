import { useEffect, useRef, useState } from 'react'
import { api } from '../api.js'
import TextViewer from './TextViewer.jsx'
import { ChevronDown, ChevronUp } from 'lucide-react'
import { highlightIn, isVideo, scrollToEl } from '../util.jsx'

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

function Sheets({ id, ext, terms }) {
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
          if (!cancelled) { setSheets([{ name: ext.toUpperCase(), rows: data }]); setActive(0) }
        } else {
          const XLSX = await import('xlsx')
          const wb = XLSX.read(buf, { type: 'array', cellDates: true })
          const out = wb.SheetNames.map((name) => ({
            name,
            rows: XLSX.utils.sheet_to_json(wb.Sheets[name], { header: 1, raw: false, defval: '', blankrows: false }),
          }))
          if (!cancelled) {
            setSheets(out)
            const hit = terms.length
              ? out.findIndex((sh) => sh.rows.some((r) => r.some((c) => terms.some((t) => String(c).toLowerCase().includes(t)))))
              : -1
            setActive(Math.max(hit, 0))
          }
        }
      } catch (e) {
        if (!cancelled) setError(e.message || 'Could not render this spreadsheet.')
      }
    })()
    return () => { cancelled = true }
  }, [id, ext]) // eslint-disable-line react-hooks/exhaustive-deps

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
      <Grid key={active} rows={sheets[active].rows} />
    </div>
  )
}

function useFit(host, ready) {
  useEffect(() => {
    const el = host.current
    if (!ready || !el) return undefined
    const fit = () => {
      const inner = [...el.children].find((c) => c.tagName !== 'STYLE')
      if (!inner) return
      inner.style.zoom = ''
      const avail = el.clientWidth - 24
      const need = Math.max(inner.scrollWidth, el.scrollWidth - 24)
      if (need > avail && avail > 0) inner.style.zoom = String(avail / need)
      for (let i = 0; i < 3 && el.scrollWidth > el.clientWidth + 1; i += 1) {
        inner.style.zoom = String((Number(inner.style.zoom) || 1) * (el.clientWidth / el.scrollWidth) * 0.98)
      }
      el.scrollLeft = 0
    }
    fit()
    const ro = new ResizeObserver(fit)
    ro.observe(el)
    return () => ro.disconnect()
  }, [host, ready])
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
  useFit(host, state === 'ok')
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
  useFit(host, state === 'ok')
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

export default function FilePreview({ id, ext, terms = [] }) {
  const e = (ext || '').toLowerCase()
  const root = useRef(null)
  const [hits, setHits] = useState(0)
  const [cur, setCur] = useState(-1)
  const jumped = useRef(false)
  const key = terms.join('|')

  const focusHit = (i) => {
    const marks = root.current?.querySelectorAll('mark.hit') || []
    if (!marks.length) return
    const n = ((i % marks.length) + marks.length) % marks.length
    marks.forEach((m, j) => m.classList.toggle('cur', j === n))
    scrollToEl(marks[n])
    setCur(n)
  }

  useEffect(() => {
    jumped.current = false
    setHits(0); setCur(-1)
    if (!terms.length || !root.current) return undefined
    const node = root.current
    let timer
    const run = () => {
      observer.disconnect()
      const count = highlightIn(node, terms)
      observer.observe(node, { childList: true, subtree: true })
      setHits(count)
      if (count && !jumped.current) { jumped.current = true; focusHit(0) }
    }
    const observer = new MutationObserver(() => { clearTimeout(timer); timer = setTimeout(run, 150) })
    observer.observe(node, { childList: true, subtree: true })
    run()
    return () => { observer.disconnect(); clearTimeout(timer) }
  }, [id, key]) // eslint-disable-line react-hooks/exhaustive-deps

  let body
  if (isVideo(e)) body = <video className="cbt-video" controls preload="metadata" src={api.fileUrl(id)} />
  else if (SHEET.has(e) || DELIM.has(e)) body = <Sheets id={id} ext={e} terms={terms} />
  else if (e === 'docx') body = <Docx id={id} />
  else if (e === 'pptx') body = <Pptx id={id} />
  else if (PLAIN.has(e)) body = <Plain id={id} />
  else body = <TextViewer id={id} />
  return (
    <div className="file-viewer">
      {terms.length > 0 && !isVideo(e) && (
        <div className="hit-bar">
          {hits > 0 ? <span><b>{cur + 1 > 0 ? cur + 1 : 1}</b> of {hits >= 500 ? '500+' : hits} matches in this file</span>
            : <span>No highlighted matches in the preview (the match may be in the title or metadata).</span>}
          {hits > 0 && (
            <span className="hit-nav">
              <button aria-label="Previous match" onClick={() => focusHit(cur - 1)}><ChevronUp size={16} /></button>
              <button aria-label="Next match" onClick={() => focusHit(cur + 1)}><ChevronDown size={16} /></button>
            </span>
          )}
        </div>
      )}
      <div ref={root}>{body}</div>
    </div>
  )
}
