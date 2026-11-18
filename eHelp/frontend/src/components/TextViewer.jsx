import { useEffect, useState } from 'react'
import { api } from '../api.js'

export default function TextViewer({ id }) {
  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)

  const load = async (offset) => {
    setLoading(true)
    try {
      const res = await api.text(id, offset)
      setItems((prev) => (offset ? [...prev, ...res.items] : res.items))
      setTotal(res.total)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { setItems([]); load(0) }, [id]) // eslint-disable-line react-hooks/exhaustive-deps

  if (!loading && total === 0) {
    return <div className="text-viewer empty">No extractable text preview for this file. Use Download to open it.</div>
  }
  return (
    <div className="text-viewer">
      {items.map((c) => (
        <section key={c.ordinal}>
          {(c.page || c.label) && <h4>{c.page ? `Page ${c.page}` : c.label}{c.page && c.label ? ` · ${c.label}` : ''}</h4>}
          <pre>{c.text}</pre>
        </section>
      ))}
      {items.length < total && (
        <button className="more" disabled={loading} onClick={() => load(items.length)}>
          {loading ? 'Loading…' : `Load more (${total - items.length} remaining)`}
        </button>
      )}
    </div>
  )
}
