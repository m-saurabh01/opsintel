import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Clock, Search, TrendingUp } from 'lucide-react'
import { useApp, useGoSearch } from '../App.jsx'
import { api } from '../api.js'
import { DocRow } from '../components/DocList.jsx'

export default function Home() {
  const { settings } = useApp()
  const [data, setData] = useState(null)
  const [q, setQ] = useState('')
  const goSearch = useGoSearch()

  useEffect(() => { api.home().then(setData).catch(() => {}) }, [])

  const submit = (e) => {
    e.preventDefault()
    goSearch(q.trim())
  }

  return (
    <div className="home">
      <section className="hero" style={{ backgroundImage: `linear-gradient(180deg, rgba(6,20,45,0) 25%, rgba(6,20,45,.88) 100%), url(${settings.hero_image})` }}>
        <div className="hero-copy">
          <div className="eyebrow">{settings.hero_eyebrow}</div>
          <h1>{settings.hero_title}<br /><span>{settings.hero_highlight}</span></h1>
          <p>{settings.hero_text}</p>
        </div>
        <form className="hero-search" onSubmit={submit}>
          <Search size={20} />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={settings.search_placeholder} autoFocus />
          <button type="submit">Search</button>
        </form>
      </section>
      <section className="panels">
        {settings.show_recent === '1' && (
          <div className="panel">
            <div className="panel-head">
              <h3><Clock size={18} /> Recent Documents</h3>
              <Link to="/documents">View All →</Link>
            </div>
            {data?.recent.length === 0 && <p className="muted pad">No documents yet.</p>}
            {data?.recent.map((d) => <DocRow key={d.id} doc={d} />)}
          </div>
        )}
        {settings.show_popular === '1' && (
          <div className="panel">
            <div className="panel-head">
              <h3><TrendingUp size={18} /> Popular Documents</h3>
              <Link to="/documents?sort=popular">View All →</Link>
            </div>
            {data?.popular.length === 0 && <p className="muted pad">Popular documents appear once people start reading.</p>}
            {data?.popular.map((d) => <DocRow key={d.id} doc={d} showViews />)}
          </div>
        )}
      </section>
    </div>
  )
}
