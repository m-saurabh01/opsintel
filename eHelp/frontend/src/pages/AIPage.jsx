import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Send, Sparkles } from 'lucide-react'
import { useApp } from '../App.jsx'
import AskAI from '../components/AskAI.jsx'

export default function AIPage() {
  const { settings } = useApp()
  const [params, setParams] = useSearchParams()
  const q = params.get('q') || ''
  const [draft, setDraft] = useState(q)
  const submit = () => { if (draft.trim().length >= 3) setParams({ q: draft.trim() }) }
  if (settings.ai_enabled !== '1') {
    return <div className="page"><h2>AI Assistant is turned off</h2><p className="muted">An administrator can enable it under Admin → AI Mode.</p></div>
  }
  return (
    <div className="search-page">
      <div className="search-head">
        <div>
          <div className="eyebrow">Workspace</div>
          <h1>AI Assistant</h1>
          <p>Ask a question in plain language. Answers are drawn only from indexed documents and cite their sources.</p>
        </div>
      </div>
      <form className="ai-compose" onSubmit={(e) => { e.preventDefault(); submit() }}>
        <textarea rows={3} value={draft} maxLength={1000} autoFocus
          placeholder="Ask a question about your documents, e.g. “What are the pre-flight inspection steps?”"
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit() } }} />
        <div className="ai-compose-bar">
          <span className="hint"><Sparkles size={14} /> Answers cite their source documents · Enter to send, Shift+Enter for a new line</span>
          <button type="submit" className="btn primary" disabled={draft.trim().length < 3}><Send size={15} /> Ask</button>
        </div>
      </form>
      {q ? <AskAI key={q} question={q} auto /> : <div className="empty">Type a question to get a cited answer from the document library.</div>}
    </div>
  )
}
