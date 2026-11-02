import { useEffect, useRef, useState } from 'react'
import * as pdfjsLib from 'pdfjs-dist'
import pdfWorkerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import { api } from './api.js'

pdfjsLib.GlobalWorkerOptions.workerSrc = pdfWorkerUrl

export default function PdfViewer({ fileId, page: initialPage = 1, onClose, onTextView }) {
  const canvasRef = useRef(null)
  const hostRef = useRef(null)
  const documentRef = useRef(null)
  const renderTaskRef = useRef(null)
  const [page, setPage] = useState(initialPage)
  const [pageCount, setPageCount] = useState(0)
  const [meta, setMeta] = useState(null)
  const [zoom, setZoom] = useState(1)
  const [fitWidth, setFitWidth] = useState(true)
  const [hostWidth, setHostWidth] = useState(0)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setPage(initialPage)
  }, [fileId, initialPage])

  useEffect(() => {
    let cancelled = false
    api.file(fileId).then((info) => !cancelled && setMeta(info)).catch((e) => {
      if (!cancelled) setError(e.message)
    })
    return () => { cancelled = true }
  }, [fileId])

  useEffect(() => {
    const host = hostRef.current
    if (!host) return undefined
    const observer = new ResizeObserver((entries) => setHostWidth(entries[0].contentRect.width))
    observer.observe(host)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    let cancelled = false
    const task = pdfjsLib.getDocument({ url: api.pdfUrl(fileId) })
    setLoading(true)
    setError('')
    documentRef.current = null
    task.promise
      .then((pdf) => {
        if (cancelled) {
          pdf.destroy()
          return
        }
        documentRef.current = pdf
        setPageCount(pdf.numPages)
        setPage((current) => Math.min(Math.max(current, 1), pdf.numPages))
      })
      .catch((e) => !cancelled && setError(e.message || 'PDF could not be opened'))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
      renderTaskRef.current?.cancel()
      task.destroy()
      documentRef.current = null
    }
  }, [fileId])

  useEffect(() => {
    let cancelled = false
    const pdf = documentRef.current
    const canvas = canvasRef.current
    if (!pdf || !canvas || !hostWidth || !pageCount) return undefined
    renderTaskRef.current?.cancel()
    setError('')

    const render = async () => {
      try {
        const pdfPage = await pdf.getPage(page)
        if (cancelled) return
        const natural = pdfPage.getViewport({ scale: 1 })
        const scale = fitWidth ? Math.max(0.25, (hostWidth - 32) / natural.width) : zoom
        const viewport = pdfPage.getViewport({ scale })
        const pixelRatio = window.devicePixelRatio || 1
        canvas.width = Math.ceil(viewport.width * pixelRatio)
        canvas.height = Math.ceil(viewport.height * pixelRatio)
        canvas.style.width = `${Math.ceil(viewport.width)}px`
        canvas.style.height = `${Math.ceil(viewport.height)}px`
        const context = canvas.getContext('2d', { alpha: false })
        const task = pdfPage.render({
          canvasContext: context,
          viewport,
          transform: pixelRatio === 1 ? null : [pixelRatio, 0, 0, pixelRatio, 0, 0],
          background: '#ffffff',
        })
        renderTaskRef.current = task
        await task.promise
      } catch (e) {
        if (!cancelled && e.name !== 'RenderingCancelledException') setError(e.message || 'Page could not be rendered')
      }
    }
    render()
    return () => {
      cancelled = true
      renderTaskRef.current?.cancel()
    }
  }, [fileId, page, zoom, fitWidth, hostWidth, pageCount])

  const changeZoom = (delta) => {
    setFitWidth(false)
    setZoom((z) => Math.min(3, Math.max(0.5, Math.round((z + delta) * 100) / 100)))
  }

  return (
    <aside className="viewer pdf-viewer" aria-label="PDF viewer">
      <div className="viewer-head">
        <div>
          <div className="path">{meta?.path || (loading ? 'Loading PDF…' : 'PDF')}</div>
          <div className="meta">{meta?.repo_name || 'Indexed PDF'}{meta?.branch ? ` @ ${meta.branch}` : ''} · rendered locally</div>
        </div>
        <button onClick={onClose} title="Close (Esc)">Close</button>
      </div>
      <div className="pdf-toolbar" aria-label="PDF controls">
        <button title="Previous page" aria-label="Previous page" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>‹</button>
        <label className="pdf-page-control">
          Page
          <input
            aria-label="PDF page number"
            type="number"
            min="1"
            max={pageCount || 1}
            value={page}
            onChange={(e) => setPage(Math.min(pageCount || 1, Math.max(1, Number(e.target.value) || 1)))}
          />
          <span>of {pageCount || '…'}</span>
        </label>
        <button title="Next page" aria-label="Next page" disabled={pageCount > 0 && page >= pageCount}
          onClick={() => setPage((p) => Math.min(pageCount, p + 1))}>›</button>
        <span className="toolbar-divider" />
        <button title="Zoom out" aria-label="Zoom out" disabled={!fitWidth && zoom <= 0.5}
          onClick={() => changeZoom(-0.15)}>−</button>
        <button title="Fit page to viewer width" aria-label="Fit page to viewer width" className={fitWidth ? 'active' : ''}
          onClick={() => setFitWidth(true)}>Fit</button>
        <button title="Zoom in" aria-label="Zoom in" disabled={!fitWidth && zoom >= 3}
          onClick={() => changeZoom(0.15)}>+</button>
        <button className="pdf-text-button" onClick={onTextView}>Extracted text</button>
      </div>
      <div className="pdf-canvas-scroll" ref={hostRef}>
        {loading && <div className="viewer-message">Loading PDF page…</div>}
        {error && <div className="error pdf-error" role="alert">{error}</div>}
        <canvas ref={canvasRef} className="pdf-canvas" aria-label={`PDF page ${page}`} />
      </div>
    </aside>
  )
}
