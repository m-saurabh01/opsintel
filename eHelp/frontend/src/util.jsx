import { File, FileSpreadsheet, FileText, Presentation, Video } from 'lucide-react'

export function formatSize(bytes) {
  if (bytes == null) return ''
  const units = ['B', 'KB', 'MB', 'GB']
  let value = bytes
  let i = 0
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024
    i += 1
  }
  return `${value >= 100 || i === 0 ? Math.round(value) : value.toFixed(1)} ${units[i]}`
}

export function formatDate(ts, withTime = false) {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  const date = d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })
  return withTime ? `${date}, ${d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })}` : date
}

const KINDS = {
  pdf: { label: 'PDF', color: '#d9362b', icon: FileText },
  doc: { label: 'DOC', color: '#2b6cd9', icon: FileText },
  docx: { label: 'DOCX', color: '#2b6cd9', icon: FileText },
  xls: { label: 'XLS', color: '#1d8f4e', icon: FileSpreadsheet },
  xlsx: { label: 'XLSX', color: '#1d8f4e', icon: FileSpreadsheet },
  csv: { label: 'CSV', color: '#1d8f4e', icon: FileSpreadsheet },
  ppt: { label: 'PPT', color: '#d9772b', icon: Presentation },
  pptx: { label: 'PPTX', color: '#d9772b', icon: Presentation },
  txt: { label: 'TXT', color: '#64748b', icon: FileText },
  mp4: { label: 'CBT', color: '#7c3aed', icon: Video },
  m4v: { label: 'CBT', color: '#7c3aed', icon: Video },
  webm: { label: 'CBT', color: '#7c3aed', icon: Video },
}

export function FileIcon({ ext, size = 44 }) {
  const kind = KINDS[ext] || { label: (ext || 'file').toUpperCase().slice(0, 4), color: '#64748b', icon: File }
  const Icon = kind.icon
  return (
    <span className="file-icon" style={{ '--c': kind.color, width: size, height: size }} title={kind.label}>
      <Icon size={size * 0.5} />
      <b>{kind.label}</b>
    </span>
  )
}

export const FILE_TYPES = ['pdf', 'docx', 'doc', 'pptx', 'ppt', 'xlsx', 'xls', 'csv', 'txt', 'mp4', 'webm']
export const VIDEO_EXTS = ['mp4', 'm4v', 'webm']
export const isVideo = (ext) => VIDEO_EXTS.includes((ext || '').toLowerCase())

export const BANNERS = ['afimg4', 'iaf_img12', 'afimg9', 'afimg10', 'tejas5', 'an32', 'afimg7', 'iaf_img14']

export function bannerFor(category) {
  if (category?.banner) return category.banner
  return `/img/${BANNERS[(category?.id || 0) % BANNERS.length]}.jpg`
}

// Server marks matches with \x02 ... \x03 so snippets never need HTML.
export function Marked({ text }) {
  const parts = String(text || '').split(/(\x02[^\x03]*\x03)/)
  return (
    <span className="marked">
      {parts.map((p, i) => (p.startsWith('\x02')
        ? <mark key={i}>{p.slice(1, -1)}</mark>
        : p))}
    </span>
  )
}

export function termsOf(q, mode) {
  const text = String(q || '').trim().toLowerCase()
  if (!text) return []
  if (mode === 'exact') return [text]
  const words = text.replace(/["()]/g, ' ').split(/\s+/).filter((w) => w && !['and', 'or', 'not'].includes(w))
  return [...new Set(words)].sort((a, b) => b.length - a.length)
}

const SKIP = new Set(['STYLE', 'SCRIPT', 'MARK', 'TEXTAREA', 'INPUT'])
const MAX_MARKS = 500

// Wraps matches of `terms` in <mark class="hit">; returns the total number of marks under root.
export function highlightIn(root, terms) {
  if (!root || !terms.length) return 0
  const re = new RegExp(terms.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|'), 'gi')
  let total = root.querySelectorAll('mark.hit').length
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode: (n) => (n.parentElement && !SKIP.has(n.parentElement.tagName) && n.nodeValue.trim()
      ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT),
  })
  const nodes = []
  while (walker.nextNode()) nodes.push(walker.currentNode)
  for (const node of nodes) {
    if (total >= MAX_MARKS) break
    const text = node.nodeValue
    re.lastIndex = 0
    let m = re.exec(text)
    if (!m) continue
    const frag = document.createDocumentFragment()
    let last = 0
    while (m && total < MAX_MARKS) {
      if (m.index > last) frag.append(text.slice(last, m.index))
      const mark = document.createElement('mark')
      mark.className = 'hit'
      mark.textContent = m[0]
      frag.append(mark)
      total += 1
      last = m.index + m[0].length
      if (m[0].length === 0) re.lastIndex += 1
      m = re.exec(text)
    }
    if (last < text.length) frag.append(text.slice(last))
    node.replaceWith(frag)
  }
  return total
}

// Scrolls the nearest scrollable ancestor so that `el` is centred.
export function scrollToEl(el) {
  let p = el.parentElement
  while (p && p !== document.body) {
    const oy = getComputedStyle(p).overflowY
    if ((oy === 'auto' || oy === 'scroll') && p.scrollHeight > p.clientHeight) {
      const box = el.getBoundingClientRect()
      const host = p.getBoundingClientRect()
      p.scrollTop += box.top - host.top - p.clientHeight / 2 + box.height / 2
      const ox = getComputedStyle(p).overflowX
      if ((ox === 'auto' || ox === 'scroll') && p.scrollWidth > p.clientWidth) {
        p.scrollLeft += box.left - host.left - p.clientWidth / 2 + box.width / 2
      }
      return
    }
    p = p.parentElement
  }
}
