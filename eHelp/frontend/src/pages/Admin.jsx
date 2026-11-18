import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Pencil, RefreshCw, Trash2, Upload, X } from 'lucide-react'
import { useApp } from '../App.jsx'
import { api } from '../api.js'
import { ICON_NAMES } from '../icons.jsx'
import { FileIcon, formatDate, formatSize } from '../util.jsx'

function Notice({ note }) {
  if (!note) return null
  return <div className={note.error ? 'error' : 'ok'}>{note.text}</div>
}

function RelatedPicker({ selfId, selected, onChange }) {
  const [q, setQ] = useState('')
  const [options, setOptions] = useState([])
  const [titles, setTitles] = useState({})

  useEffect(() => {
    api.documents({ q, page_size: 30, sort: 'title' }).then((r) => {
      setOptions(r.items.filter((d) => d.id !== selfId))
      setTitles((t) => ({ ...t, ...Object.fromEntries(r.items.map((d) => [d.id, d.title])) }))
    }).catch(() => {})
  }, [q, selfId])

  useEffect(() => {
    selected.filter((id) => !titles[id]).forEach((id) => {
      api.document(id).then((d) => setTitles((t) => ({ ...t, [id]: d.title }))).catch(() => {})
    })
  }, [selected]) // eslint-disable-line react-hooks/exhaustive-deps

  const toggle = (id) => onChange(selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id])
  return (
    <div className="related-picker">
      <div className="chips">
        {selected.length === 0 && <span className="muted">None chosen – related documents are suggested automatically.</span>}
        {selected.map((id) => (
          <span key={id} className="chip">{titles[id] || `#${id}`}<button type="button" onClick={() => toggle(id)} aria-label="Remove"><X size={12} /></button></span>
        ))}
      </div>
      <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search documents to link…" />
      <div className="options">
        {options.map((d) => (
          <label key={d.id}><input type="checkbox" checked={selected.includes(d.id)} onChange={() => toggle(d.id)} /> {d.title} <small>{d.ext.toUpperCase()}</small></label>
        ))}
      </div>
    </div>
  )
}

function UploadForm({ categories, onDone }) {
  const [files, setFiles] = useState([])
  const [form, setForm] = useState({ title: '', description: '', category_id: '', tags: '', revision: '' })
  const [related, setRelated] = useState([])
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState(null)
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))

  const submit = async (e) => {
    e.preventDefault()
    if (!files.length) return
    setBusy(true)
    setNote(null)
    let done = 0
    try {
      for (const file of files) {
        const fd = new FormData()
        fd.append('file', file)
        if (files.length === 1 && form.title) fd.append('title', form.title)
        fd.append('description', form.description)
        if (form.category_id) fd.append('category_id', form.category_id)
        fd.append('tags', form.tags)
        fd.append('revision', form.revision)
        fd.append('related_ids', JSON.stringify(related))
        await api.uploadDocument(fd)
        done += 1
      }
      setNote({ text: `Uploaded ${done} document${done === 1 ? '' : 's'}.` })
      setFiles([])
      setForm({ title: '', description: '', category_id: form.category_id, tags: '', revision: '' })
      setRelated([])
      e.target.reset()
      onDone()
    } catch (err) {
      setNote({ error: true, text: `${err.message}${done ? ` (${done} uploaded before the error)` : ''}` })
      onDone()
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="panel admin-form" onSubmit={submit}>
      <div className="panel-head"><h3><Upload size={18} /> Upload documents</h3></div>
      <div className="form-grid">
        <label className="wide">Files (PDF, DOCX, PPTX, XLSX, TXT, …)
          <input type="file" multiple required onChange={(e) => setFiles([...e.target.files])} />
        </label>
        <label>Category
          <select value={form.category_id} onChange={set('category_id')}>
            <option value="">— none —</option>
            {categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </label>
        <label>Title {files.length > 1 && <small>(file names are used for multi-upload)</small>}
          <input value={form.title} onChange={set('title')} disabled={files.length > 1} placeholder="Defaults to the file name" />
        </label>
        <label>Revision<input value={form.revision} onChange={set('revision')} placeholder="Rev 4.2" /></label>
        <label>Tags<input value={form.tags} onChange={set('tags')} placeholder="A320, Structure, Repair" /></label>
        <label className="wide">Description<textarea value={form.description} onChange={set('description')} rows={2} /></label>
        <div className="wide"><span className="label">Related documents</span><RelatedPicker selfId={0} selected={related} onChange={setRelated} /></div>
      </div>
      <div className="form-actions">
        <button className="btn primary" disabled={busy || !files.length}>{busy ? 'Uploading & indexing…' : 'Upload'}</button>
        <Notice note={note} />
      </div>
    </form>
  )
}

function EditDialog({ doc, categories, onClose, onSaved }) {
  const [form, setForm] = useState({
    title: doc.title, description: doc.description, category_id: doc.category_id ?? '',
    tags: doc.tags.join(', '), revision: doc.revision,
  })
  const [related, setRelated] = useState([])
  const [ready, setReady] = useState(false)
  const [note, setNote] = useState(null)
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))

  useEffect(() => {
    api.relations(doc.id).then((r) => { setRelated(r.related_ids); setReady(true) }).catch(() => setReady(true))
  }, [doc.id])

  const save = async (e) => {
    e.preventDefault()
    try {
      await api.updateDocument(doc.id, {
        ...form, category_id: form.category_id === '' ? null : Number(form.category_id), related_ids: related,
      })
      onSaved()
      onClose()
    } catch (err) { setNote({ error: true, text: err.message }) }
  }

  const replace = async (e) => {
    const file = e.target.files[0]
    if (!file) return
    try {
      const out = await api.replaceFile(doc.id, file)
      setNote({ text: `File replaced (${out.index_status}).` })
      onSaved()
    } catch (err) { setNote({ error: true, text: err.message }) }
  }

  return (
    <div className="modal" role="dialog" aria-modal="true">
      <form className="modal-card" onSubmit={save}>
        <div className="panel-head"><h3>Edit document</h3><button type="button" className="icon-btn" onClick={onClose} aria-label="Close"><X size={18} /></button></div>
        <div className="form-grid">
          <label className="wide">Title<input value={form.title} onChange={set('title')} required /></label>
          <label>Category
            <select value={form.category_id} onChange={set('category_id')}>
              <option value="">— none —</option>
              {categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </label>
          <label>Revision<input value={form.revision} onChange={set('revision')} /></label>
          <label className="wide">Tags<input value={form.tags} onChange={set('tags')} /></label>
          <label className="wide">Description<textarea rows={2} value={form.description} onChange={set('description')} /></label>
          <label className="wide">Replace file<input type="file" onChange={replace} /></label>
          <div className="wide"><span className="label">Related documents</span>
            {ready && <RelatedPicker selfId={doc.id} selected={related} onChange={setRelated} />}
          </div>
        </div>
        <div className="form-actions"><button className="btn primary">Save changes</button><Notice note={note} /></div>
      </form>
    </div>
  )
}

function Documents({ categories }) {
  const [q, setQ] = useState('')
  const [data, setData] = useState(null)
  const [page, setPage] = useState(1)
  const [editing, setEditing] = useState(null)
  const { refresh } = useApp()

  const load = useCallback(() => {
    api.documents({ q, page, page_size: 15, sort: 'modified' }).then(setData).catch(() => {})
    refresh()
  }, [q, page, refresh])
  useEffect(() => { load() }, [load])

  const remove = async (d) => {
    if (!window.confirm(`Delete “${d.title}”? This removes the file permanently.`)) return
    await api.deleteDocument(d.id)
    load()
  }
  const reindex = async (d) => { await api.reindex(d.id); load() }

  return (
    <>
      <UploadForm categories={categories} onDone={load} />
      <div className="panel">
        <div className="panel-head">
          <h3>Documents ({data?.total ?? '…'})</h3>
          <input className="mini-search" value={q} onChange={(e) => { setQ(e.target.value); setPage(1) }} placeholder="Filter…" />
        </div>
        <table className="table">
          <thead><tr><th></th><th>Title</th><th>Category</th><th>Size</th><th>Modified</th><th>Index</th><th></th></tr></thead>
          <tbody>
            {data?.items.map((d) => (
              <tr key={d.id}>
                <td><FileIcon ext={d.ext} size={28} /></td>
                <td><Link to={`/doc/${d.id}`}>{d.title}</Link></td>
                <td>{d.category || '—'}</td>
                <td>{formatSize(d.size)}</td>
                <td>{formatDate(d.updated_at)}</td>
                <td><span className={`status ${d.index_status}`} title={d.index_error}>{d.index_status}</span></td>
                <td className="row-actions">
                  <button className="icon-btn" title="Edit" onClick={() => setEditing(d)}><Pencil size={16} /></button>
                  <button className="icon-btn" title="Re-index" onClick={() => reindex(d)}><RefreshCw size={16} /></button>
                  <button className="icon-btn danger" title="Delete" onClick={() => remove(d)}><Trash2 size={16} /></button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {data && data.total > 15 && (
          <div className="pager pad">
            <button disabled={page <= 1} onClick={() => setPage(page - 1)}>‹</button>
            <span>{page} / {Math.ceil(data.total / 15)}</span>
            <button disabled={page * 15 >= data.total} onClick={() => setPage(page + 1)}>›</button>
          </div>
        )}
      </div>
      {editing && <EditDialog doc={editing} categories={categories} onClose={() => setEditing(null)} onSaved={load} />}
    </>
  )
}

function ImageField({ label, value, onChange }) {
  const upload = async (e) => {
    const file = e.target.files[0]
    if (!file) return
    const { url } = await api.uploadAsset(file)
    onChange(url)
  }
  return (
    <label className="wide">{label}
      <span className="image-field">
        {value && <img src={value} alt="" />}
        <input value={value} onChange={(e) => onChange(e.target.value)} placeholder="/img/… or upload" />
        <input type="file" accept="image/*" onChange={upload} />
      </span>
    </label>
  )
}

function Categories() {
  const { categories, refresh } = useApp()
  const [draft, setDraft] = useState({ name: '', description: '', icon: 'folder' })
  const [note, setNote] = useState(null)

  const run = async (fn) => {
    try { await fn(); setNote(null); await refresh() } catch (err) { setNote({ error: true, text: err.message }) }
  }
  const patch = (c, body) => run(() => api.updateCategory(c.id, body))

  return (
    <>
      <form className="panel admin-form" onSubmit={(e) => { e.preventDefault(); run(async () => { await api.createCategory(draft); setDraft({ name: '', description: '', icon: 'folder' }) }) }}>
        <div className="panel-head"><h3>New category</h3></div>
        <div className="form-grid">
          <label>Name<input required value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} /></label>
          <label>Icon<select value={draft.icon} onChange={(e) => setDraft({ ...draft, icon: e.target.value })}>{ICON_NAMES.map((n) => <option key={n}>{n}</option>)}</select></label>
          <label className="wide">Description<input value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })} /></label>
        </div>
        <div className="form-actions"><button className="btn primary">Add category</button><Notice note={note} /></div>
      </form>
      {categories.map((c) => (
        <div key={c.id} className="panel admin-form">
          <div className="form-grid">
            <label>Name<input defaultValue={c.name} onBlur={(e) => e.target.value !== c.name && patch(c, { name: e.target.value })} /></label>
            <label>Icon<select value={c.icon} onChange={(e) => patch(c, { icon: e.target.value })}>{ICON_NAMES.map((n) => <option key={n}>{n}</option>)}</select></label>
            <label className="wide">Description<input defaultValue={c.description} onBlur={(e) => e.target.value !== c.description && patch(c, { description: e.target.value })} /></label>
            <ImageField label="Banner image" value={c.banner} onChange={(v) => patch(c, { banner: v })} />
            <label>Order<input type="number" defaultValue={c.sort_order} onBlur={(e) => patch(c, { sort_order: Number(e.target.value) })} /></label>
          </div>
          <div className="form-actions">
            <span className="muted">{c.count} documents</span>
            <button className="btn danger" onClick={() => window.confirm(`Delete category “${c.name}”? Its documents are kept but uncategorised.`) && run(() => api.deleteCategory(c.id))}>Delete</button>
          </div>
        </div>
      ))}
    </>
  )
}

const TEXT_SETTINGS = [
  ['app_name', 'Application name'], ['subtitle', 'Subtitle'], ['hero_eyebrow', 'Hero eyebrow'],
  ['hero_title', 'Hero title'], ['hero_highlight', 'Hero highlighted line'], ['hero_text', 'Hero text'],
  ['search_placeholder', 'Search placeholder'],
]
const COLOR_SETTINGS = [['accent_color', 'Accent'], ['highlight_color', 'Highlight'], ['sidebar_color', 'Sidebar']]
const TOGGLES = [['show_category_tiles', 'Category tiles'], ['show_recent', 'Recent documents'], ['show_popular', 'Popular documents']]

function Appearance() {
  const { settings, refresh } = useApp()
  const [form, setForm] = useState(settings)
  const [note, setNote] = useState(null)
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))

  const save = async (e) => {
    e.preventDefault()
    try { await api.updateSettings(form); await refresh(); setNote({ text: 'Saved.' }) } catch (err) { setNote({ error: true, text: err.message }) }
  }
  return (
    <form className="panel admin-form" onSubmit={save}>
      <div className="form-grid">
        {TEXT_SETTINGS.map(([k, label]) => <label key={k} className={k === 'hero_text' || k === 'search_placeholder' ? 'wide' : ''}>{label}<input value={form[k]} onChange={set(k)} /></label>)}
        <ImageField label="Logo" value={form.logo} onChange={(v) => setForm((f) => ({ ...f, logo: v }))} />
        <ImageField label="Hero image" value={form.hero_image} onChange={(v) => setForm((f) => ({ ...f, hero_image: v }))} />
        {COLOR_SETTINGS.map(([k, label]) => <label key={k}>{label} colour<input type="color" value={form[k]} onChange={set(k)} /></label>)}
        <div className="wide toggles">
          {TOGGLES.map(([k, label]) => (
            <label key={k} className="check"><input type="checkbox" checked={form[k] === '1'} onChange={(e) => setForm((f) => ({ ...f, [k]: e.target.checked ? '1' : '0' }))} /> Show {label}</label>
          ))}
        </div>
      </div>
      <div className="form-actions"><button className="btn primary">Save appearance</button><Notice note={note} /></div>
    </form>
  )
}

export default function Admin() {
  const { me, categories } = useApp()
  const [tab, setTab] = useState('documents')
  if (!me.is_admin) {
    return <div className="page"><h2>Administrator access required</h2><p className="muted">Your account is not in the admin group.</p></div>
  }
  return (
    <div className="page admin">
      <h1>Administration</h1>
      <div className="tabs">
        {[['documents', 'Documents'], ['categories', 'Categories'], ['appearance', 'Appearance']].map(([k, label]) => (
          <button key={k} className={`tab${tab === k ? ' active' : ''}`} onClick={() => setTab(k)}>{label}</button>
        ))}
      </div>
      {tab === 'documents' && <Documents categories={categories} />}
      {tab === 'categories' && <Categories />}
      {tab === 'appearance' && <Appearance />}
    </div>
  )
}
