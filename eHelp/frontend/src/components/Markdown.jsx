import { Fragment } from 'react'
import { Link } from 'react-router-dom'

// Small, dependency-free Markdown renderer that builds React elements (never raw HTML),
// so model output cannot inject markup. [E1]-style citations become links to the source.
const CITE = String.raw`[\[(]E\d+(?:[^\])\n]{0,60})?[\])]`
const INLINE = new RegExp(String.raw`(\*\*[^*]+\*\*|__[^_]+__|`+'`[^`]+`'+String.raw`|\*[^*\s][^*]*\*|_[^_\s][^_]*_|${CITE})`, 'g')

function Inline({ text, cites }) {
  return text.split(INLINE).map((p, i) => {
    if (!p) return null
    if (new RegExp(`^${CITE}$`).test(p)) {
      // Accepts [E1], [E1, E2] and (E1, Section 2); only known evidence IDs are linked.
      return [...new Set(p.match(/E\d+/g))].map((id) => {
        const c = cites[id]
        return c ? <Link key={`${i}${id}`} className="ai-cite" title={c.title} to={`/doc/${c.doc_id}${c.page ? `?page=${c.page}` : ''}`}>{id}</Link> : null
      })
    }
    if (/^(\*\*|__)/.test(p)) return <strong key={i}><Inline text={p.slice(2, -2)} cites={cites} /></strong>
    if (p.startsWith('`')) return <code key={i}>{p.slice(1, -1)}</code>
    if (/^[*_][^*_\s]/.test(p) && /[*_]$/.test(p)) return <em key={i}><Inline text={p.slice(1, -1)} cites={cites} /></em>
    return <Fragment key={i}>{p}</Fragment>
  })
}

const BULLET = /^\s*[-*•]\s+(.*)$/
const NUMBER = /^\s*(\d+)[.)]\s+(.*)$/
const HEADING = /^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$/
const TABLE_SEP = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/
const cells = (line) => line.trim().replace(/^\||\|$/g, '').split('|').map((c) => c.trim())

// A table is a separator row after a header, or 2+ consecutive rows with the same number (>1) of pipe-separated cells.
function isTable(lines, i) {
  if (!lines[i].includes('|')) return false
  if (TABLE_SEP.test(lines[i + 1] || '')) return true
  const n = cells(lines[i]).length
  return n > 1 && (lines[i + 1] || '').includes('|') && cells(lines[i + 1]).length === n
}

function parse(src) {
  const lines = src.replace(/\r\n?/g, '\n').split('\n')
  const blocks = []
  let i = 0
  while (i < lines.length) {
    const line = lines[i]
    if (!line.trim()) { i++; continue }
    if (/^\s*```/.test(line)) {
      const code = []
      i++
      while (i < lines.length && !/^\s*```/.test(lines[i])) code.push(lines[i++])
      i++
      blocks.push({ type: 'code', text: code.join('\n') })
    } else if (HEADING.test(line)) {
      const [, h, text] = HEADING.exec(line)
      blocks.push({ type: 'heading', level: Math.min(h.length + 2, 6), text })
      i++
    } else if (/^\s*([-*_])\s*\1\s*\1[\s\-*_]*$/.test(line)) {
      blocks.push({ type: 'hr' })
      i++
    } else if (isTable(lines, i)) {
      const head = cells(line)
      const rows = []
      i += TABLE_SEP.test(lines[i + 1] || '') ? 2 : 1
      while (i < lines.length && lines[i].includes('|') && lines[i].trim()) rows.push(cells(lines[i++]))
      blocks.push({ type: 'table', head, rows })
    } else if (BULLET.test(line) || NUMBER.test(line)) {
      const ordered = NUMBER.test(line)
      const items = []
      const start = ordered ? Number(NUMBER.exec(line)[1]) : 1
      while (i < lines.length) {
        const m = (ordered ? NUMBER : BULLET).exec(lines[i])
        if (m) { items.push(m[ordered ? 2 : 1]); i++ }
        else if (/^\s{2,}\S/.test(lines[i]) && items.length && !BULLET.test(lines[i]) && !NUMBER.test(lines[i])) { items[items.length - 1] += ` ${lines[i].trim()}`; i++ }
        else if (!lines[i].trim() && (ordered ? NUMBER : BULLET).test(lines[i + 1] || '')) i++
        else break
      }
      blocks.push({ type: 'list', ordered, start, items })
    } else {
      const para = []
      while (i < lines.length && lines[i].trim() && !/^\s*```/.test(lines[i]) && !HEADING.test(lines[i])
        && !BULLET.test(lines[i]) && !NUMBER.test(lines[i]) && !isTable(lines, i)) para.push(lines[i++].trim())
      blocks.push({ type: 'p', text: para.join(' ') })
    }
  }
  return blocks
}

export default function Markdown({ text, citations = [] }) {
  const cites = Object.fromEntries(citations.map((c) => [c.id, c]))
  const inl = (t) => <Inline text={t} cites={cites} />
  return (
    <div className="md">
      {parse(text || '').map((b, i) => {
        switch (b.type) {
          case 'heading': { const H = `h${b.level}`; return <H key={i}>{inl(b.text)}</H> }
          case 'code': return <pre key={i}><code>{b.text}</code></pre>
          case 'hr': return <hr key={i} />
          case 'list': {
            const L = b.ordered ? 'ol' : 'ul'
            return <L key={i} {...(b.ordered && b.start !== 1 ? { start: b.start } : {})}>{b.items.map((t, j) => <li key={j}>{inl(t)}</li>)}</L>
          }
          case 'table':
            return (
              <div key={i} className="md-table"><table>
                <thead><tr>{b.head.map((c, j) => <th key={j}>{inl(c)}</th>)}</tr></thead>
                <tbody>{b.rows.map((r, j) => <tr key={j}>{r.map((c, k) => <td key={k}>{inl(c)}</td>)}</tr>)}</tbody>
              </table></div>
            )
          default: return <p key={i}>{inl(b.text)}</p>
        }
      })}
    </div>
  )
}
