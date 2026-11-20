export const THEMES = [
  { id: 'iaf', name: 'IAF Blue', accent: '#0b78d1', highlight: '#22d3ee', sidebar: '#0b2447', bg: '#eef3fa' },
  { id: 'midnight', name: 'Midnight', accent: '#6366f1', highlight: '#a5b4fc', sidebar: '#111827', bg: '#eef0f6' },
  { id: 'desert', name: 'Desert Sand', accent: '#b45309', highlight: '#fbbf24', sidebar: '#4a3a24', bg: '#f6f1e7' },
  { id: 'olive', name: 'Olive Drab', accent: '#4d7c0f', highlight: '#bef264', sidebar: '#2b3a1f', bg: '#f0f3e8' },
  { id: 'steel', name: 'Steel Grey', accent: '#2563eb', highlight: '#7dd3fc', sidebar: '#27313f', bg: '#eff1f4' },
  { id: 'crimson', name: 'Crimson', accent: '#be123c', highlight: '#fda4af', sidebar: '#3b0d1c', bg: '#f8eff1' },
]

export const THEME_KEYS = { accent: 'accent_color', highlight: 'highlight_color', sidebar: 'sidebar_color', bg: 'bg_color' }

export function applyColors(s) {
  const root = document.documentElement.style
  root.setProperty('--accent', s.accent_color)
  root.setProperty('--highlight', s.highlight_color)
  root.setProperty('--sidebar', s.sidebar_color)
  root.setProperty('--bg', s.bg_color || '#eef3fa')
}
