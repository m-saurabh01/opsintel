import { useRef, useState } from 'react'
import { ArrowUpRight, Bot, CircleStop, FileText, LockKeyhole, Send, ShieldCheck, Sparkles } from 'lucide-react'
import { api } from './api.js'

const SUGGESTIONS = [
  'Where is the Authorization header validated?',
  'Which settings control the DB2 connection timeout?',
  'How does the logout endpoint revoke a token?',
]
const STAGE_LABELS = {
  queued: 'Waiting for the local AI queue',
  retrieving: 'Retrieving indexed evidence',
  generating: 'Reading evidence and drafting an answer',
  validating: 'Checking source citations',
  retrying: 'Retrying the local model request',
}

function citationLocation(location) {
  if (location.kind === 'line') return `line ${location.line}`
  if (location.kind === 'page') return `page ${location.page}${location.section ? ` · ${location.section}` : ''}`
  if (location.kind === 'cell') return `${location.sheet} ! ${location.cell}${location.header ? ` · ${location.header}` : ''}`
  if (location.kind === 'row') return `row ${location.row}${location.column ? ` · ${location.column}` : ''}`
  if (location.kind === 'section') {
    return [location.section, location.table ? `table ${location.table}, row ${location.table_row}`
      : location.paragraph ? `paragraph ${location.paragraph}` : null].filter(Boolean).join(' · ')
  }
  return location.kind
}

async function consumeEvents(response, onEvent) {
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  const dispatch = (block) => {
    let event = 'message'
    const data = []
    for (const line of block.split(/\r?\n/)) {
      if (line.startsWith('event:')) event = line.slice(6).trim()
      else if (line.startsWith('data:')) data.push(line.slice(5).trimStart())
    }
    if (!data.length) return
    try { onEvent(event, JSON.parse(data.join('\n'))) } catch { onEvent('error', { message: 'Invalid AI stream response' }) }
  }
  while (true) {
    const { value, done } = await reader.read()
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done })
    let boundary
    while ((boundary = buffer.search(/\r?\n\r?\n/)) !== -1) {
      const block = buffer.slice(0, boundary)
      const separator = buffer.slice(boundary).match(/^\r?\n\r?\n/)[0]
      buffer = buffer.slice(boundary + separator.length)
      dispatch(block)
    }
    if (done) break
  }
  if (buffer.trim()) dispatch(buffer)
  reader.releaseLock()
}

export default function AIAssistant({ repos, health, onOpenCitation }) {
  const [question, setQuestion] = useState('')
  const [repoId, setRepoId] = useState('')
  const [answer, setAnswer] = useState('')
  const [citations, setCitations] = useState([])
  const [stage, setStage] = useState('')
  const [warning, setWarning] = useState('')
  const [error, setError] = useState('')
  const [cached, setCached] = useState(false)
  const [busy, setBusy] = useState(false)
  const [jobId, setJobId] = useState(null)
  const abortRef = useRef(null)

  const ai = health?.ai
  const ready = Boolean(ai?.enabled && ai?.reachable && ai?.version_ok && ai?.model_present)
  const modelLabel = health === undefined ? 'Checking Ollama…'
    : ready ? ai.model : ai?.enabled === false ? 'AI disabled' : 'Ollama unavailable'

  const ask = async (value = question) => {
    const prompt = value.trim()
    if (prompt.length < 3 || busy) return
    setQuestion(prompt)
    setAnswer('')
    setCitations([])
    setStage('queued')
    setWarning('')
    setError('')
    setCached(false)
    setBusy(true)
    const controller = new AbortController()
    abortRef.current = controller
    try {
      const submitted = await api.ask(prompt, repoId ? [Number(repoId)] : null)
      setJobId(submitted.job_id)
      const response = await api.askEvents(submitted.job_id, controller.signal)
      await consumeEvents(response, (event, data) => {
        if (event === 'stage') setStage(data.stage)
        else if (event === 'token') setAnswer((current) => current + (data.text || ''))
        else if (event === 'done') {
          setCitations(data.citations || [])
          setWarning(data.citation_warning || '')
          setCached(Boolean(data.cached))
          setStage('done')
          setBusy(false)
        } else if (event === 'error') {
          setError(data.message || 'The AI request failed.')
          setStage('failed')
          setBusy(false)
        } else if (event === 'cancelled') {
          setStage('cancelled')
          setBusy(false)
        }
      })
    } catch (e) {
      if (e.name !== 'AbortError') setError(e.message)
      setBusy(false)
    } finally {
      abortRef.current = null
    }
  }

  const cancel = async () => {
    if (jobId) await api.cancelAsk(jobId).catch(() => {})
    abortRef.current?.abort()
    setBusy(false)
    setStage('cancelled')
  }

  const onSubmit = (event) => {
    event.preventDefault()
    ask()
  }

  return (
    <section className="assistant-view">
      <div className="assistant-heading">
        <div>
          <span className="section-eyebrow">LOCAL MODEL · SOURCE-GROUNDED</span>
          <h1>AI Assistant</h1>
          <p>Ask a question. Answers are generated from retrieved repository evidence and link back to its source.</p>
        </div>
        <span className={`assistant-model ${ready ? 'ready' : ''}`}><span className="health-dot" />
          {modelLabel}</span>
      </div>

      <div className="assistant-layout">
        <div className="assistant-main">
          <div className="assistant-scope">
            <LockKeyhole size={14} />
            <span>Local-only, single-user mode</span>
            <span className="scope-separator" />
            <label htmlFor="assistant-repo">Evidence scope</label>
            <select id="assistant-repo" value={repoId} onChange={(e) => setRepoId(e.target.value)}>
              <option value="">All indexed repositories</option>
              {repos.map((repo) => <option key={repo.id} value={repo.id}>{repo.name}</option>)}
            </select>
          </div>

          <form className="assistant-prompt" onSubmit={onSubmit}>
            <label htmlFor="assistant-question">Your question</label>
            <textarea id="assistant-question" value={question} onChange={(e) => setQuestion(e.target.value)}
              placeholder="Ask about an implementation, configuration or procedure…" maxLength={1000} rows={4}
              disabled={busy || !ready} />
            <div className="prompt-footer">
              <span>{question.length}/1000 · evidence is treated as untrusted input</span>
              {busy ? (
                <button className="ask-button cancel" type="button" onClick={cancel}><CircleStop size={15} /> Cancel</button>
              ) : (
                <button className="ask-button" type="submit" disabled={!ready || question.trim().length < 3}>
                  <Send size={14} /> Ask locally
                </button>
              )}
            </div>
          </form>

          {!answer && !busy && !error && (
            <div className="assistant-suggestions">
              <span>Try a question</span>
              {SUGGESTIONS.map((sample) => <button key={sample} onClick={() => ask(sample)} disabled={!ready}>{sample}<ArrowUpRight size={13} /></button>)}
            </div>
          )}

          {error && <div className="error assistant-error" role="alert">{error}</div>}
          {busy && <div className="answer-progress"><span className="progress-pulse" />{STAGE_LABELS[stage] || 'Preparing request'}</div>}
          {answer && (
            <section className="answer-panel" aria-live="polite">
              <div className="answer-header"><span className="answer-icon"><Sparkles size={16} /></span>
                <div><strong>Answer</strong><small>{cached ? 'From local answer cache' : `Generated by ${ai?.model || 'local Ollama'}`}</small></div>
                {stage === 'done' && <span className="answer-complete">Source check complete</span>}
              </div>
              <div className="answer-text">{answer}</div>
              {warning && <div className="citation-warning" role="status">{warning}</div>}
              {citations.length > 0 && (
                <div className="citation-list">
                  <div className="citation-heading"><span>Retrieved sources</span><span>{citations.length}</span></div>
                  {citations.map((citation) => (
                    <button className="citation-card" key={citation.id} onClick={() => onOpenCitation(citation)}>
                      <span className="citation-id">[{citation.id}]</span>
                      <span className="citation-copy"><strong>{citation.path}</strong>
                        <small>{citation.repo}{citation.branch ? ` @ ${citation.branch}` : ''} · {citationLocation(citation.location)}</small></span>
                      <ArrowUpRight size={14} />
                    </button>
                  ))}
                </div>
              )}
            </section>
          )}
        </div>

        <aside className="assistant-rail">
          <div className="rail-heading"><Bot size={17} /><span>How answers work</span></div>
          <ol>
            <li><b>Retrieve</b><span>Relevant indexed chunks are selected before generation.</span></li>
            <li><b>Answer</b><span>The local model receives only a bounded evidence set.</span></li>
            <li><b>Verify</b><span>Only citations matching retrieved chunk IDs are shown.</span></li>
          </ol>
          <div className="rail-safety"><ShieldCheck size={16} /><span>Repository text is treated as untrusted data. The assistant cannot run tools or change files.</span></div>
          <div className="rail-scope"><LockKeyhole size={14} /> Until M5, keep this server on localhost.</div>
        </aside>
      </div>
    </section>
  )
}
