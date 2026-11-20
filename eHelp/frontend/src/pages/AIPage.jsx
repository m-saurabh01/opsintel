import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Sparkles } from 'lucide-react'
import { useApp } from '../App.jsx'
import AskAI from '../components/AskAI.jsx'

export default function AIPage() {
  const { settings } = useApp()
  const [params, setParams] = useSearchParams()
  const q = params.get('q') || ''
  const [draft, setDraft] = useState(q)
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
      <form className="search-bar" onSubmit={(e) => { e.preventDefault(); if (draft.trim().length > 2) setParams({ q: draft.trim() }) }}>
        <Sparkles size={18} />
        <input value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="Ask anything about your documents..." autoFocus />
        <button type="submit" className="go">Ask</button>
      </form>
      {q ? <AskAI key={q} question={q} auto /> : <div className="empty">Type a question to get a cited answer from the document library.</div>}
    </div>
  )
}
