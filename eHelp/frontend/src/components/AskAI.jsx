import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Bot, Loader2, Sparkles, X } from 'lucide-react'
import { api } from '../api.js'
import Markdown from './Markdown.jsx'

async function* sse(res) {
  const reader = res.body.getReader()
  const dec = new TextDecoder()
  let buf = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buf += dec.decode(value, { stream: true })
    let i
    while ((i = buf.indexOf('\n\n')) >= 0) {
      const block = buf.slice(0, i)
      buf = buf.slice(i + 2)
      const event = /^event: (.*)$/m.exec(block)?.[1]
      const data = /^data: (.*)$/m.exec(block)?.[1]
      if (event && data) yield [event, JSON.parse(data)]
    }
  }
}

export default function AskAI({ question, category, auto }) {
  const [state, setState] = useState({ phase: 'idle', text: '', stage: '', citations: [], warning: '', error: '' })
  const ctl = useRef(null)
  useEffect(() => () => ctl.current?.abort(), [])
  
  const ask = useCallback(async () => {
    ctl.current?.abort()
    ctl.current = new AbortController()
    setState({ phase: 'running', text: '', stage: 'Starting…', citations: [], warning: '', error: '' })
    try {
      const res = await api.aiAsk(question, category, ctl.current.signal)
      if (!res.ok) {
        let d = res.statusText
        try { d = (await res.json()).detail || d } catch { /* keep */ }
        throw new Error(typeof d === 'string' ? d : JSON.stringify(d))
      }
      for await (const [ev, d] of sse(res)) {
        if (ev === 'stage') setState((s) => ({ ...s, stage: d.message || 'Searching documents and generating an answer…' }))
        else if (ev === 'token') setState((s) => ({ ...s, text: s.text + (d.text ?? d.token ?? '') }))
        else if (ev === 'done') setState((s) => ({ ...s, phase: 'done', text: d.answer, citations: d.citations || [], warning: d.citation_warning || '' }))
        else if (ev === 'error') throw new Error(d.message || d.detail || 'AI request failed')
      }
      setState((s) => (s.phase === 'running' ? { ...s, phase: 'done' } : s))
    } catch (e) {
      if (e.name !== 'AbortError') setState((s) => ({ ...s, phase: 'error', error: e.message }))
    }
  }, [question, category])

  useEffect(() => {
    ctl.current?.abort()
    setState({ phase: 'idle', text: '', stage: '', citations: [], warning: '', error: '' })
    if (auto && question) ask()
  }, [question, category, auto, ask])

  const { phase, text, stage, citations, warning, error } = state
  return (
    <div className="ai-panel">
      <div className="ai-head">
        <Bot size={18} /> <b>AI Assistant</b>
        <span className="muted">Answers come only from indexed documents and cite their sources.</span>
        {phase === 'running'
          ? <button type="button" className="btn small" onClick={() => { ctl.current?.abort(); setState((s) => ({ ...s, phase: 'idle' })) }}><X size={14} /> Stop</button>
          : <button type="button" className="btn primary small" onClick={ask}><Sparkles size={14} /> {phase === 'idle' ? 'Ask AI' : 'Ask again'}</button>}
      </div>
      {phase === 'running' && !text && <div className="ai-stage"><Loader2 size={14} className="spin" /> {stage}</div>}
      {text && <Markdown text={text} citations={citations} />}
      {phase === 'done' && citations.length > 0 && (
        <div className="ai-sources">
          {citations.map((c) => (
            <Link key={c.id} to={`/doc/${c.doc_id}${c.page ? `?page=${c.page}` : ''}`}><span>{c.id}</span> {c.title}{c.page ? ` · p.${c.page}` : ''}</Link>
          ))}
        </div>
      )}
      {warning && <div className="muted">{warning}</div>}
      {phase === 'error' && <div className="error">{error}</div>}
    </div>
  )
}
