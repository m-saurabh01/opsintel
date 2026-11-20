import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ArrowRight, BookOpen, ClipboardCheck, FileText, MessageCircle, Plane, Send, ShieldCheck, Sparkles, Wrench, Zap, Settings } from 'lucide-react'
import { useApp } from '../App.jsx'
import AskAI from '../components/AskAI.jsx'
import PageBanner from '../components/PageBanner.jsx'

const FEATURES = [
  [FileText, 'Document-Aware Answers', 'Uses only your approved documents'],
  [ShieldCheck, 'Cited & Verifiable', 'See exact source and page references'],
  [Zap, 'Mission Focused', 'Built for operations, maintenance and engineering'],
]
const IDEAS = [
  [Plane, 'Operations', 'What are the steps for aircraft turnaround at a remote station?'],
  [Wrench, 'Maintenance', 'What is the maintenance procedure for the hydraulic system?'],
  [Settings, 'Engineering', 'What are the design limits for the landing gear?'],
  [ShieldCheck, 'Safety & Quality', 'What safety checks are required before engine start?'],
  [BookOpen, 'Training & Manuals', 'Where can I find the crew training requirements?'],
  [ClipboardCheck, 'Regulatory & Compliance', 'What are the latest compliance requirements for airworthiness?'],
]

export default function AIPage() {
  const { settings, categories } = useApp()
  const [params, setParams] = useSearchParams()
  const q = params.get('q') || ''
  const category = params.get('category') || ''
  const [draft, setDraft] = useState(q)
  const [cat, setCat] = useState(category)
  const ask = (text, c = cat) => {
    const t = text.trim()
    if (t.length < 3) return
    setDraft(t)
    setParams({ q: t, ...(c ? { category: c } : {}) })
  }
  if (settings.ai_enabled !== '1') {
    return <div className="page"><h2>AI Assistant is turned off</h2><p className="muted">An administrator can enable it under Admin → AI Mode.</p></div>
  }
  return (
    <div className="ai-page">
      <PageBanner image="/img/iaf_img11.jpg" icon={<Sparkles size={34} />} title="AI Assistant">
        Ask a question in plain language. Get precise, cited answers from your documents.
      </PageBanner>
      <div className="ai-features">
        {FEATURES.map(([Icon, t, d]) => (
          <div key={t}><span className="feat-icon"><Icon size={20} /></span><div><b>{t}</b><small>{d}</small></div></div>
        ))}
      </div>
      <form className="ai-compose" onSubmit={(e) => { e.preventDefault(); ask(draft) }}>
        <textarea rows={3} value={draft} maxLength={1000} autoFocus
          placeholder="Ask a question about your documents, e.g. “What are the pre-flight inspection steps?”"
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); ask(draft) } }} />
        <div className="ai-compose-bar">
          <span className="hint">Enter to send, Shift+Enter for a new line</span>
          <label className="answer-from">Answer from
            <select value={cat} onChange={(e) => setCat(e.target.value)}>
              <option value="">All Documents</option>
              {categories.map((c) => <option key={c.id} value={c.slug}>{c.name}</option>)}
            </select>
          </label>
          <button type="submit" className="btn primary" disabled={draft.trim().length < 3}><Send size={15} /> Ask</button>
        </div>
      </form>
      {q
        ? <AskAI key={`${q}|${category}`} question={q} category={category} auto />
        : (
          <>
            <h3 className="try-title"><MessageCircle size={18} /> Try asking</h3>
            <div className="try-grid">
              {IDEAS.map(([Icon, t, d]) => (
                <button key={t} type="button" className="try-card" onClick={() => ask(d)}>
                  <Icon size={24} /><span><b>{t}</b><small>{d}</small></span><ArrowRight size={16} />
                </button>
              ))}
            </div>
          </>
        )}
    </div>
  )
}
