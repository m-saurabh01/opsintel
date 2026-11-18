import { useEffect, useRef, useState } from 'react'
import * as pdfjsLib from 'pdfjs-dist'
import pdfWorkerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import { Download, ExternalLink, LayoutGrid, Maximize, Minus, Plus, Printer, RotateCw } from 'lucide-react'

pdfjsLib.GlobalWorkerOptions.workerSrc = pdfWorkerUrl

function Thumb({ pdf, number, active, onClick }) {
  const ref = useRef(null)
  const holder = useRef(null)
  useEffect(() => {
    let cancelled = false
    let task
    const observer = new IntersectionObserver(async ([entry]) => {
      if (!entry.isIntersecting || cancelled) return
      observer.disconnect()
      try {
        const page = await pdf.getPage(number)
        const base = page.getViewport({ scale: 1 })
        const viewport = page.getViewport({ scale: 110 / base.width })
        const canvas = ref.current
        if (!canvas || cancelled) return
        canvas.width = viewport.width
        canvas.height = viewport.height
        task = page.render({ canvasContext: canvas.getContext('2d'), viewport, background: '#fff' })
        await task.promise
      } catch { /* cancelled */ }
    })
    observer.observe(holder.current)
    return () => { cancelled = true; observer.disconnect(); task?.cancel() }
  }, [pdf, number])
  return (
    <button ref={holder} className={`thumb${active ? ' active' : ''}`} onClick={onClick} aria-label={`Page ${number}`}>
      <canvas ref={ref} width="110" height="140" />
      <span>{number}</span>
    </button>
  )
}

export default function PdfViewer({ url, downloadUrl, page: initialPage = 1, compact = false, title, terms = [] }) {
  const canvasRef = useRef(null)
  const hostRef = useRef(null)
  const stageRef = useRef(null)
  const renderRef = useRef(null)
  const [pdf, setPdf] = useState(null)
  const [page, setPage] = useState(initialPage)
  const [zoom, setZoom] = useState(1)
  const [rotation, setRotation] = useState(0)
  const [width, setWidth] = useState(0)
  const [thumbs, setThumbs] = useState(!compact)
  const [error, setError] = useState('')
  const [boxes, setBoxes] = useState([])
  const termKey = terms.join('|')

  useEffect(() => setPage(initialPage), [url, initialPage])

  useEffect(() => {
    const host = hostRef.current
    const observer = new ResizeObserver((e) => setWidth(e[0].contentRect.width))
    observer.observe(host)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    let cancelled = false
    const task = pdfjsLib.getDocument({ url })
    setError('')
    task.promise
      .then((doc) => {
        if (cancelled) { doc.destroy(); return }
        setPdf(doc)
        setPage((p) => Math.min(Math.max(p, 1), doc.numPages))
      })
      .catch((e) => !cancelled && setError(e.message || 'PDF could not be opened'))
    return () => { cancelled = true; renderRef.current?.cancel(); task.destroy(); setPdf(null) }
  }, [url])

  useEffect(() => {
    if (!pdf || !width) return undefined
    let cancelled = false
    renderRef.current?.cancel()
    ;(async () => {
      try {
        const p = await pdf.getPage(page)
        if (cancelled) return
        const natural = p.getViewport({ scale: 1, rotation })
        const scale = Math.max(0.2, ((width - 32) / natural.width) * zoom)
        const viewport = p.getViewport({ scale, rotation })
        const ratio = window.devicePixelRatio || 1
        const canvas = canvasRef.current
        canvas.width = Math.ceil(viewport.width * ratio)
        canvas.height = Math.ceil(viewport.height * ratio)
        canvas.style.width = `${Math.ceil(viewport.width)}px`
        canvas.style.height = `${Math.ceil(viewport.height)}px`
        const task = p.render({
          canvasContext: canvas.getContext('2d', { alpha: false }), viewport, background: '#fff',
          transform: ratio === 1 ? null : [ratio, 0, 0, ratio, 0, 0],
        })
        renderRef.current = task
        await task.promise
        stageRef.current?.scrollTo({ top: 0 })
        if (terms.length) {
          const content = await p.getTextContent()
          if (cancelled) return
          const found = []
          for (const it of content.items) {
            const str = it.str || ''
            const low = str.toLowerCase()
            if (!low.trim()) continue
            for (const t of terms) {
              let at = low.indexOf(t)
              while (at !== -1) {
                const [a, b, , , e, f] = pdfjsLib.Util.transform(viewport.transform, it.transform)
                const h = Math.hypot(a, b)
                const w = it.width * scale
                found.push({
                  left: e + (w * at) / str.length - 1, top: f - h - 1,
                  width: Math.max((w * t.length) / str.length, 6) + 2, height: h + 3,
                })
                at = low.indexOf(t, at + t.length)
              }
            }
          }
          setBoxes(found)
          const first = found.reduce((m, b) => Math.min(m, b.top), Infinity)
          if (found.length) stageRef.current?.scrollTo({ top: Math.max(0, first - 80) })
        } else setBoxes([])
      } catch (e) {
        if (!cancelled && e.name !== 'RenderingCancelledException') setError(e.message || 'Page could not be rendered')
      }
    })()
    return () => { cancelled = true; renderRef.current?.cancel() }
  }, [pdf, page, zoom, rotation, width, termKey]) // eslint-disable-line react-hooks/exhaustive-deps

  const count = pdf?.numPages || 0
  const go = (p) => setPage(Math.min(Math.max(1, p), count || 1))
  const fullscreen = () => hostRef.current?.parentElement?.requestFullscreen?.()

  return (
    <div className={`pdfv${compact ? ' compact' : ''}`}>
      <div className="pdfv-bar">
        <button aria-label="Toggle thumbnails" onClick={() => setThumbs((t) => !t)}><LayoutGrid size={18} /></button>
        <span className="page-box">
          <input type="number" min="1" max={count || 1} value={page} aria-label="Page number"
            onChange={(e) => go(Number(e.target.value) || 1)} /> / {count || '…'}
        </span>
        <span className="sep" />
        <button aria-label="Zoom out" onClick={() => setZoom((z) => Math.max(0.4, +(z - 0.15).toFixed(2)))}><Minus size={18} /></button>
        <span className="zoom">{Math.round(zoom * 100)}%</span>
        <button aria-label="Zoom in" onClick={() => setZoom((z) => Math.min(3, +(z + 0.15).toFixed(2)))}><Plus size={18} /></button>
        <button aria-label="Rotate" onClick={() => setRotation((r) => (r + 90) % 360)}><RotateCw size={18} /></button>
        <span className="spacer" />
        <a href={`${url}#page=${page}`} target="_blank" rel="noreferrer" aria-label="Open in new tab" title={title || 'Open in new tab'}><ExternalLink size={18} /></a>
        <button aria-label="Full screen" onClick={fullscreen}><Maximize size={18} /></button>
        <button aria-label="Print" onClick={() => { const w = window.open(url, '_blank'); w?.addEventListener('load', () => w.print()) }}><Printer size={18} /></button>
        <a href={downloadUrl} aria-label="Download"><Download size={18} /></a>
      </div>
      <div className="pdfv-body">
        {thumbs && pdf && (
          <div className="thumbs">
            {Array.from({ length: count }, (_, i) => (
              <Thumb key={i + 1} pdf={pdf} number={i + 1} active={page === i + 1} onClick={() => go(i + 1)} />
            ))}
          </div>
        )}
        <div className="pdfv-stage" ref={hostRef}>
          <div className="pdfv-scroll" ref={stageRef}>
            {error ? <div className="error">{error}</div> : (
              <div className="pdfv-page">
                <canvas ref={canvasRef} />
                {boxes.map((b, i) => <span key={i} className="pdf-hit" style={b} />)}
              </div>
            )}
          </div>
        </div>
      </div>
      <div className="pdfv-foot">
        <button disabled={page <= 1} onClick={() => go(1)}>«</button>
        <button disabled={page <= 1} onClick={() => go(page - 1)}>‹</button>
        <span>{page} / {count || '…'}</span>
        <button disabled={page >= count} onClick={() => go(page + 1)}>›</button>
        <button disabled={page >= count} onClick={() => go(count)}>»</button>
      </div>
    </div>
  )
}
