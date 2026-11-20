import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Check, CheckCircle2, Loader2, Pencil, Plus, RefreshCw, RotateCcw, Search, Trash2, TriangleAlert, Upload, UploadCloud, X, XCircle } from 'lucide-react'
import { useApp } from '../App.jsx'
import { api } from '../api.js'
import Pager from '../components/Pager.jsx'
import { CategoryIcon, ICON_NAMES } from '../icons.jsx'
import { applyColors, THEMES } from '../themes.js'
import { FileIcon, formatDate, formatSize } from '../util.jsx'

function Notice({ note }) {
  if (!note) return null
  return <div className={note.error ? 'error' : 'ok'}>{note.text}</div>
}


function Modal({ title, onClose, children, wide }) {
  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  return (
    <div className="modal" role="dialog" aria-modal="true" aria-label={title} onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal-card${wide ? ' wide' : ''}`}>
        <div className="panel-head"><h3>{title}</h3><button type="button" className="icon-btn" onClick={onClose} aria-label="Close"><X size={18} /></button></div>
        {children}
      </div>
    </div>
  )
}

function ConfirmDialog({ title, message, confirmLabel = 'Delete', onConfirm, onClose }) {
  const [busy, setBusy] = useState(false)
  const go = async () => { setBusy(true); try { await onConfirm() } finally { setBusy(false); onClose() } }
  return (
    <Modal title={title} onClose={onClose}>
      <div className="confirm-body">
        <div className="confirm-icon"><TriangleAlert size={24} /></div>
        <p>{message}</p>
      </div>
      <div className="confirm-actions">
        <button type="button" className="btn" onClick={onClose} disabled={busy}>Cancel</button>
        <button type="button" className="btn danger-solid" onClick={go} disabled={busy} autoFocus>
          {busy ? <Loader2 size={15} className="spin" /> : <Trash2 size={15} />} {confirmLabel}
        </button>
      </div>
    </Modal>
  )
}

function Field({ label, required, hint, wide, children }) {
  return (
    <label className={`field${wide ? ' wide' : ''}`}>
      <span className="field-label">{label}{required && <i className="req" title="Required">*</i>}</span>
      {children}
      {hint && <small className="hint">{hint}</small>}
    </label>
  )
}

function TagInput({ value, onChange, placeholder }) {
  const [text, setText] = useState('')
  const add = (raw) => {
    const t = raw.trim().replace(/,$/, '').trim()
    if (t && !value.some((v) => v.toLowerCase() === t.toLowerCase())) onChange([...value, t])
    setText('')
  }
  return (
    <div className="tag-input">
      {value.map((t) => (
        <span key={t} className="chip">{t}<button type="button" aria-label={`Remove ${t}`} onClick={() => onChange(value.filter((x) => x !== t))}><X size={12} /></button></span>
      ))}
      <input value={text} placeholder={value.length ? '' : placeholder}
        onChange={(e) => (e.target.value.endsWith(',') ? add(e.target.value) : setText(e.target.value))}
        onKeyDown={(e) => {
          if (e.key === 'Enter') { e.preventDefault(); add(text) }
          if (e.key === 'Backspace' && !text && value.length) onChange(value.slice(0, -1))
        }}
        onBlur={() => add(text)} />
    </div>
  )
}

function Dropzone({ files, onChange, disabled }) {
  const [over, setOver] = useState(false)
  const input = useRef(null)
  const addFiles = (list) => {
    const known = new Set(files.map((f) => `${f.name}|${f.size}`))
    onChange([...files, ...[...list].filter((f) => !known.has(`${f.name}|${f.size}`))])
  }
  return (
    <div>
      <div className={`dropzone${over ? ' over' : ''}`} role="button" tabIndex={0}
        onClick={() => input.current?.click()}
        onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && input.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setOver(true) }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); if (!disabled) addFiles(e.dataTransfer.files) }}>
        <UploadCloud size={30} />
        <b>Drag files here or click to browse</b>
        <small>PDF, DOCX, PPTX, XLSX, CSV, TXT and more · several files at once</small>
        <input ref={input} type="file" multiple hidden onChange={(e) => { addFiles(e.target.files); e.target.value = '' }} />
      </div>
      {files.length > 0 && (
        <ul className="file-list">
          {files.map((f, i) => (
            <li key={`${f.name}${f.size}`} className={f.state || ''}>
              <FileIcon ext={f.name.split('.').pop().toLowerCase()} size={24} />
              <span className="fname">{f.name}</span><small>{formatSize(f.size)}</small>
              {f.state === 'busy' && <Loader2 size={16} className="spin" />}
              {f.state === 'done' && <CheckCircle2 size={16} className="okc" />}
              {f.state === 'error' && <span title={f.error}><XCircle size={16} className="errc" /></span>}
              {!disabled && !f.state && <button type="button" className="icon-btn" aria-label="Remove file" onClick={() => onChange(files.filter((_, j) => j !== i))}><X size={14} /></button>}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
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
  const [form, setForm] = useState({ title: '', description: '', category_id: '', revision: '' })
  const [tags, setTags] = useState([])
  const [related, setRelated] = useState([])
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState(null)
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))
  const mark = (name, patch) => setFiles((list) => list.map((f) => (f.name === name ? Object.assign(f, patch) : f)))

  const submit = async (e) => {
    e.preventDefault()
    if (!files.length) return
    setBusy(true)
    setNote(null)
    let done = 0
    let failed = 0
    for (const file of files) {
      mark(file.name, { state: 'busy' })
      try {
        const fd = new FormData()
        fd.append('file', file)
        if (files.length === 1 && form.title) fd.append('title', form.title)
        fd.append('description', form.description)
        if (form.category_id) fd.append('category_id', form.category_id)
        fd.append('tags', tags.join(', '))
        fd.append('revision', form.revision)
        fd.append('related_ids', JSON.stringify(related))
        await api.uploadDocument(fd)
        mark(file.name, { state: 'done' })
        done += 1
      } catch (err) {
        mark(file.name, { state: 'error', error: err.message })
        failed += 1
      }
    }
    setBusy(false)
    onDone()
    if (!failed) {
      setNote({ text: `Uploaded ${done} document${done === 1 ? '' : 's'}.` })
      setFiles([]); setTags([]); setRelated([])
      setForm((f) => ({ title: '', description: '', category_id: f.category_id, revision: '' }))
    } else {
      setFiles((list) => list.filter((f) => f.state === 'error').map((f) => { f.state = undefined; return f }))
      setNote({ error: true, text: `${failed} file${failed === 1 ? '' : 's'} failed (${done} uploaded). Fix the problem and upload again.` })
    }
  }

  return (
    <form className="panel admin-form" onSubmit={submit}>
      <div className="panel-head"><h3><Upload size={18} /> Upload documents</h3></div>
      <Dropzone files={files} onChange={setFiles} disabled={busy} />
      <div className="form-grid spaced">
        <Field label="Category" hint="Stays selected between uploads, handy for batches.">
          <select value={form.category_id} onChange={set('category_id')}>
            <option value="">— none —</option>
            {categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </Field>
        <Field label="Title" hint={files.length > 1 ? 'File names are used as titles for multiple files.' : 'Optional – defaults to the file name.'}>
          <input value={form.title} onChange={set('title')} disabled={files.length > 1} placeholder="e.g. A320 Structural Repair Manual" />
        </Field>
        <Field label="Tags" hint="Press Enter or comma to add."><TagInput value={tags} onChange={setTags} placeholder="A320, Structure, Repair" /></Field>
        <Field label="Revision"><input value={form.revision} onChange={set('revision')} placeholder="Rev 4.2" /></Field>
      </div>
      <button type="button" className="link-btn" onClick={() => setOpen((o) => !o)}>{open ? '− Hide' : '+ Add'} description and related documents</button>
      {open && (
        <div className="form-grid spaced">
          <Field label="Description" wide><textarea value={form.description} onChange={set('description')} rows={2} placeholder="Short summary shown on document cards" /></Field>
          <div className="wide"><span className="field-label">Related documents</span><RelatedPicker selfId={0} selected={related} onChange={setRelated} /></div>
        </div>
      )}
      <div className="form-actions sticky">
        <button className="btn primary" disabled={busy || !files.length}>{busy ? 'Uploading & indexing…' : `Upload${files.length ? ` ${files.length} file${files.length === 1 ? '' : 's'}` : ''}`}</button>
        <Notice note={note} />
      </div>
    </form>
  )
}

function EditDialog({ doc, categories, onClose, onSaved }) {
  const [form, setForm] = useState({
    title: doc.title, description: doc.description, category_id: doc.category_id ?? '', revision: doc.revision,
  })
  const [tags, setTags] = useState(doc.tags)
  const [related, setRelated] = useState([])
  const [ready, setReady] = useState(false)
  const [note, setNote] = useState(null)
  const [saving, setSaving] = useState(false)
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))

  useEffect(() => {
    api.relations(doc.id).then((r) => { setRelated(r.related_ids); setReady(true) }).catch(() => setReady(true))
  }, [doc.id])

  const save = async (e) => {
    e.preventDefault()
    setSaving(true)
    try {
      await api.updateDocument(doc.id, {
        ...form, tags: tags.join(', '), category_id: form.category_id === '' ? null : Number(form.category_id), related_ids: related,
      })
      onSaved()
      onClose()
    } catch (err) { setNote({ error: true, text: err.message }); setSaving(false) }
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
    <Modal title="Edit document" onClose={onClose} wide>
      <form onSubmit={save}>
        <div className="form-grid">
          <Field label="Title" required wide><input value={form.title} onChange={set('title')} required autoFocus /></Field>
          <Field label="Category">
            <select value={form.category_id} onChange={set('category_id')}>
              <option value="">— none —</option>
              {categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </Field>
          <Field label="Revision"><input value={form.revision} onChange={set('revision')} /></Field>
          <Field label="Tags" wide hint="Press Enter or comma to add."><TagInput value={tags} onChange={setTags} placeholder="Add a tag" /></Field>
          <Field label="Description" wide><textarea rows={2} value={form.description} onChange={set('description')} /></Field>
          <Field label="Replace file" wide hint="Uploads a new version and re-indexes it. Applies immediately."><input type="file" onChange={replace} /></Field>
          <div className="wide"><span className="field-label">Related documents</span>
            {ready && <RelatedPicker selfId={doc.id} selected={related} onChange={setRelated} />}
          </div>
        </div>
        <div className="form-actions sticky">
          <button className="btn primary" disabled={saving}>{saving ? 'Saving…' : 'Save changes'}</button>
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <Notice note={note} />
        </div>
      </form>
    </Modal>
  )
}

const DOC_SIZES = [15, 30, 60]

function Documents({ categories }) {
  const [q, setQ] = useState('')
  const [cat, setCat] = useState('')
  const [data, setData] = useState(null)
  const [page, setPage] = useState(1)
  const [size, setSize] = useState(DOC_SIZES[0])
  const [editing, setEditing] = useState(null)
  const { refresh } = useApp()

  const load = useCallback(() => {
    api.documents({ q, category: cat || undefined, page, page_size: size, sort: 'modified' }).then(setData).catch(() => {})
    refresh()
  }, [q, cat, page, size, refresh])
  useEffect(() => { load() }, [load])

  const [confirming, setConfirming] = useState(null)
  const remove = async (d) => {
    await api.deleteDocument(d.id)
    load()
  }
  const reindex = async (d) => { await api.reindex(d.id); load() }

  return (
    <>
      <UploadForm categories={categories} onDone={load} />
      <div className="panel">
        <div className="panel-head list-head">
          <h3>Documents</h3>
          <select className="mini-search" value={cat} onChange={(e) => { setCat(e.target.value); setPage(1) }} aria-label="Filter by category">
            <option value="">All categories</option>
            {categories.map((c) => <option key={c.id} value={c.slug}>{c.name}</option>)}
          </select>
          <input className="mini-search" value={q} onChange={(e) => { setQ(e.target.value); setPage(1) }} placeholder="Filter by title…" />
        </div>
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th></th><th>Title</th><th>Category</th><th>Size</th><th>Modified</th><th>Index</th><th></th></tr></thead>
            <tbody>
              {data?.items.map((d) => (
                <tr key={d.id}>
                  <td><FileIcon ext={d.ext} size={28} /></td>
                  <td className="cell-title"><Link to={`/doc/${d.id}`} title={d.title}>{d.title}</Link></td>
                  <td>{d.category || '—'}</td>
                  <td>{formatSize(d.size)}</td>
                  <td>{formatDate(d.updated_at)}</td>
                  <td><span className={`status ${d.index_status}`} title={d.index_error}>{d.index_status}</span></td>
                  <td className="row-actions">
                    <button className="icon-btn" title="Edit" onClick={() => setEditing(d)}><Pencil size={16} /></button>
                    <button className="icon-btn" title="Re-index" onClick={() => reindex(d)}><RefreshCw size={16} /></button>
                    <button className="icon-btn danger" title="Delete" onClick={() => setConfirming(d)}><Trash2 size={16} /></button>
                  </td>
                </tr>
              ))}
              {data?.items.length === 0 && <tr><td colSpan={7} className="muted pad">No documents found.</td></tr>}
            </tbody>
          </table>
        </div>
        <Pager page={page} total={data?.total || 0} pageSize={size} sizes={DOC_SIZES} noun="documents" onPage={setPage}
          onSize={(n) => { setSize(n); setPage(1) }} />
      </div>
      {confirming && (
        <ConfirmDialog title="Delete document" message={`Delete “${confirming.title}”? This removes the file permanently.`}
          onConfirm={() => remove(confirming)} onClose={() => setConfirming(null)} />
      )}
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
    <label className="field wide"><span className="field-label">{label}</span>
      <span className="image-field">
        {value && <img src={value} alt="" />}
        <input value={value} onChange={(e) => onChange(e.target.value)} placeholder="/img/… or upload" />
        <input type="file" accept="image/*" onChange={upload} />
      </span>
    </label>
  )
}

const CAT_SIZES = [10, 25, 50]
const EMPTY_CAT = { name: '', description: '', icon: 'folder', banner: '', sort_order: 0 }

function CategoryDialog({ category, onClose, onSaved }) {
  const [form, setForm] = useState(category ? { ...category } : EMPTY_CAT)
  const [note, setNote] = useState(null)
  const [saving, setSaving] = useState(false)
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))
  const save = async (e) => {
    e.preventDefault()
    setSaving(true)
    try {
      const body = { name: form.name, description: form.description, icon: form.icon, banner: form.banner, sort_order: Number(form.sort_order) || 0 }
      if (category) await api.updateCategory(category.id, body)
      else await api.createCategory(body)
      await onSaved()
      onClose()
    } catch (err) { setNote({ error: true, text: err.message }); setSaving(false) }
  }
  return (
    <Modal title={category ? `Edit category` : 'New category'} onClose={onClose}>
      <form onSubmit={save}>
        <div className="form-grid">
          <Field label="Name" required wide><input required autoFocus value={form.name} onChange={set('name')} placeholder="e.g. Avionics" /></Field>
          <Field label="Icon">
            <span className="icon-pick"><span className="icon-preview"><CategoryIcon name={form.icon} size={20} /></span>
              <select value={form.icon} onChange={set('icon')}>{ICON_NAMES.map((n) => <option key={n}>{n}</option>)}</select>
            </span>
          </Field>
          <Field label="Display order" hint="Lower numbers appear first."><input type="number" value={form.sort_order} onChange={set('sort_order')} /></Field>
          <Field label="Description" wide hint="Shown under the category title."><input value={form.description} onChange={set('description')} /></Field>
          <ImageField label="Banner image" value={form.banner} onChange={(v) => setForm((f) => ({ ...f, banner: v }))} />
        </div>
        <div className="form-actions sticky">
          <button className="btn primary" disabled={saving}>{saving ? 'Saving…' : category ? 'Save changes' : 'Add category'}</button>
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <Notice note={note} />
        </div>
      </form>
    </Modal>
  )
}

function Categories() {
  const { categories, refresh } = useApp()
  const [q, setQ] = useState('')
  const [page, setPage] = useState(1)
  const [size, setSize] = useState(CAT_SIZES[0])
  const [editing, setEditing] = useState(null)
  const [note, setNote] = useState(null)

  const filtered = useMemo(
    () => categories.filter((c) => `${c.name} ${c.description}`.toLowerCase().includes(q.trim().toLowerCase())),
    [categories, q],
  )
  const rows = filtered.slice((page - 1) * size, page * size)

  const [confirming, setConfirming] = useState(null)
  const remove = async (c) => {
    try { await api.deleteCategory(c.id); setNote(null); await refresh() } catch (err) { setNote({ error: true, text: err.message }) }
  }

  return (
    <div className="panel">
      <div className="panel-head list-head">
        <h3>Categories</h3>
        <input className="mini-search" value={q} onChange={(e) => { setQ(e.target.value); setPage(1) }} placeholder="Filter categories…" />
        <button className="btn primary small" onClick={() => setEditing('new')}><Plus size={15} /> New category</button>
      </div>
      <Notice note={note} />
      <div className="table-wrap">
        <table className="table">
          <thead><tr><th></th><th>Name</th><th>Description</th><th>Documents</th><th>Order</th><th></th></tr></thead>
          <tbody>
            {rows.map((c) => (
              <tr key={c.id}>
                <td><span className="icon-preview"><CategoryIcon name={c.icon} size={18} /></span></td>
                <td className="cell-title"><Link to={`/category/${c.slug}`}>{c.name}</Link></td>
                <td className="cell-desc" title={c.description}>{c.description || '—'}</td>
                <td>{c.count}</td>
                <td>{c.sort_order}</td>
                <td className="row-actions">
                  <button className="icon-btn" title="Edit" onClick={() => setEditing(c)}><Pencil size={16} /></button>
                  <button className="icon-btn danger" title="Delete" onClick={() => setConfirming(c)}><Trash2 size={16} /></button>
                </td>
              </tr>
            ))}
            {rows.length === 0 && <tr><td colSpan={6} className="muted pad">No categories found.</td></tr>}
          </tbody>
        </table>
      </div>
      <Pager page={page} total={filtered.length} pageSize={size} sizes={CAT_SIZES} noun="categories" onPage={setPage}
        onSize={(n) => { setSize(n); setPage(1) }} />
      {confirming && (
        <ConfirmDialog title="Delete category" message={`Delete “${confirming.name}”? Its documents are kept but uncategorised.`}
          onConfirm={() => remove(confirming)} onClose={() => setConfirming(null)} />
      )}
      {editing && <CategoryDialog category={editing === 'new' ? null : editing} onClose={() => setEditing(null)} onSaved={refresh} />}
    </div>
  )
}

const TEXT_SETTINGS = [
  ['app_name', 'Application name'], ['subtitle', 'Subtitle'], ['hero_eyebrow', 'Hero eyebrow'],
  ['hero_title', 'Hero title'], ['hero_highlight', 'Hero highlighted line'], ['hero_text', 'Hero text'],
  ['search_placeholder', 'Search placeholder'],
]
const COLOR_SETTINGS = [
  ['accent_color', 'Accent', 'Buttons, links, active items'], ['highlight_color', 'Highlight', 'Hero emphasis'],
  ['sidebar_color', 'Sidebar & top bar', 'Navigation background'], ['bg_color', 'Page background', 'Behind the cards'],
]
const TOGGLES = [['show_recent', 'Recent documents'], ['show_popular', 'Popular documents']]
const SETTING_KEYS = ['theme', ...TEXT_SETTINGS.map(([k]) => k), 'logo', 'hero_image', ...COLOR_SETTINGS.map(([k]) => k), ...TOGGLES.map(([k]) => k)]
const HEX = /^#[0-9a-f]{6}$/i

function ColorField({ label, hint, value, onChange }) {
  return (
    <div className="color-field">
      <input type="color" value={HEX.test(value) ? value : '#000000'} onChange={(e) => onChange(e.target.value)} aria-label={label} />
      <span><b>{label}</b><small>{hint}</small></span>
      <input className="hex" value={value} maxLength={7} onChange={(e) => onChange(e.target.value)} aria-label={`${label} hex`} />
    </div>
  )
}

function Appearance() {
  const { settings, refresh } = useApp()
  const [form, setForm] = useState(settings)
  const [note, setNote] = useState(null)
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))
  const setColor = (k) => (v) => setForm((f) => ({ ...f, [k]: v, theme: 'custom' }))
  const dirty = SETTING_KEYS.some((k) => form[k] !== settings[k])

  useEffect(() => {
    applyColors(Object.fromEntries(COLOR_SETTINGS.map(([k]) => [k, HEX.test(form[k]) ? form[k] : settings[k]])))
  }, [form, settings])
  const settingsRef = useRef(settings)
  useEffect(() => { settingsRef.current = settings }, [settings])
  useEffect(() => () => applyColors(settingsRef.current), [])

  const pick = (t) => setForm((f) => ({ ...f, theme: t.id, accent_color: t.accent, highlight_color: t.highlight, sidebar_color: t.sidebar, bg_color: t.bg }))

  const save = async (e) => {
    e.preventDefault()
    try {
      await api.updateSettings(Object.fromEntries(SETTING_KEYS.map((k) => [k, form[k]])))
      await refresh()
      setNote({ text: 'Saved. Changes are live for everyone.' })
    } catch (err) { setNote({ error: true, text: err.message }) }
  }

  return (
    <form className="panel admin-form" onSubmit={save}>
      <section className="form-section">
        <h4>Colour theme</h4>
        <div className="theme-grid">
          {THEMES.map((t) => (
            <button type="button" key={t.id} className={`theme-card${form.theme === t.id ? ' selected' : ''}`} onClick={() => pick(t)}>
              <span className="swatch" style={{ background: t.bg }}>
                <i style={{ background: t.sidebar }} /><i style={{ background: t.accent }} /><i style={{ background: t.highlight }} />
              </span>
              <b>{t.name}</b>
              {form.theme === t.id && <Check size={16} className="tick" />}
            </button>
          ))}
          <div className={`theme-card custom${form.theme === 'custom' ? ' selected' : ''}`}>
            <span className="swatch" style={{ background: form.bg_color }}>
              <i style={{ background: form.sidebar_color }} /><i style={{ background: form.accent_color }} /><i style={{ background: form.highlight_color }} />
            </span>
            <b>Custom</b>
            {form.theme === 'custom' && <Check size={16} className="tick" />}
          </div>
        </div>
        <p className="hint">Pick a preset, then fine-tune any colour below. The whole app previews your choice live; nothing is saved until you press Save.</p>
        <div className="color-grid">
          {COLOR_SETTINGS.map(([k, label, hint]) => <ColorField key={k} label={label} hint={hint} value={form[k]} onChange={setColor(k)} />)}
        </div>
      </section>
      <section className="form-section">
        <h4>Branding</h4>
        <div className="form-grid">
          <Field label="Application name"><input value={form.app_name} onChange={set('app_name')} /></Field>
          <Field label="Subtitle"><input value={form.subtitle} onChange={set('subtitle')} /></Field>
          <ImageField label="Logo" value={form.logo} onChange={(v) => setForm((f) => ({ ...f, logo: v }))} />
        </div>
      </section>
      <section className="form-section">
        <h4>Home page</h4>
        <div className="form-grid">
          {TEXT_SETTINGS.slice(2).map(([k, label]) => (
            <Field key={k} label={label} wide={k === 'hero_text' || k === 'search_placeholder'}><input value={form[k]} onChange={set(k)} /></Field>
          ))}
          <ImageField label="Hero image" value={form.hero_image} onChange={(v) => setForm((f) => ({ ...f, hero_image: v }))} />
          <div className="wide toggles">
            {TOGGLES.map(([k, label]) => (
              <label key={k} className="check"><input type="checkbox" checked={form[k] === '1'} onChange={(e) => setForm((f) => ({ ...f, [k]: e.target.checked ? '1' : '0' }))} /> Show {label}</label>
            ))}
          </div>
        </div>
      </section>
      <div className="form-actions sticky">
        <button className="btn primary" disabled={!dirty}>Save appearance</button>
        <button type="button" className="btn" disabled={!dirty} onClick={() => { setForm(settings); setNote(null) }}><RotateCcw size={14} /> Discard changes</button>
        {dirty && <span className="muted">Unsaved changes</span>}
        <Notice note={note} />
      </div>
    </form>
  )
}

function AiSettings() {
  const { settings, refresh } = useApp()
  const [enabled, setEnabled] = useState(settings.ai_enabled === '1')
  const [limit, setLimit] = useState(settings.ai_daily_limit)
  const [status, setStatus] = useState(null)
  const [note, setNote] = useState(null)
  const load = useCallback(() => api.aiStatus().then(setStatus).catch(() => {}), [])
  useEffect(() => { load() }, [load])
  const dirty = enabled !== (settings.ai_enabled === '1') || limit !== settings.ai_daily_limit
  const save = async (e) => {
    e.preventDefault()
    if (!/^\d+$/.test(String(limit))) { setNote({ error: true, text: 'Limit must be a whole number (0 = unlimited).' }); return }
    try {
      await api.updateSettings({ ai_enabled: enabled ? '1' : '0', ai_daily_limit: String(limit) })
      await refresh(); await load()
      setNote({ text: 'AI settings saved.' })
    } catch (err) { setNote({ error: true, text: err.message }) }
  }
  return (
    <form className="panel admin-form" onSubmit={save}>
      <section className="form-section">
        <h4>AI mode</h4>
        <div className="form-grid">
          <div className="wide toggles">
            <label className="check"><input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} /> Enable AI assistant for all users</label>
          </div>
          <Field label="Daily request limit" hint="Total AI questions allowed per day across all users. 0 = unlimited.">
            <input type="number" min="0" value={limit} onChange={(e) => setLimit(e.target.value)} />
          </Field>
          {status && (
            <div className="field wide">
              <span className="field-label">Status</span>
              <small className="hint">
                Today: {status.used} used{status.limit ? `, ${status.remaining} remaining of ${status.limit}` : ' (no limit)'} ·
                {' '}Model server: {!status.enabled ? 'checked when AI is on' : status.reachable ? (status.model_present ? 'ready' : 'reachable, model missing') : 'unreachable'}
              </small>
            </div>
          )}
        </div>
      </section>
      <div className="form-actions sticky">
        <button className="btn primary" disabled={!dirty}>Save AI settings</button>
        <Notice note={note} />
      </div>
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
        {[['documents', 'Documents'], ['categories', 'Categories'], ['appearance', 'Appearance'], ['ai', 'AI Mode']].map(([k, label]) => (
          <button key={k} className={`tab${tab === k ? ' active' : ''}`} onClick={() => setTab(k)}>{label}</button>
        ))}
      </div>
      {tab === 'documents' && <Documents categories={categories} />}
      {tab === 'categories' && <Categories />}
      {tab === 'appearance' && <Appearance />}
      {tab === 'ai' && <AiSettings />}
    </div>
  )
}
