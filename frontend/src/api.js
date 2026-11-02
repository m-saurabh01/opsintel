async function request(path, params, options = {}) {
  const url = new URL(path, window.location.origin)
  for (const [k, v] of Object.entries(params || {})) {
    if (v === undefined || v === null || v === '') continue
    if (Array.isArray(v)) v.forEach((item) => url.searchParams.append(k, item))
    else url.searchParams.set(k, v)
  }
  const res = await fetch(url, { method: options.method || 'GET', headers: { Accept: 'application/json' } })
  const body = await res.json().catch(() => ({}))
  if (!res.ok) {
    const detail = typeof body.detail === 'string' ? body.detail : `Request failed (${res.status})`
    throw new Error(detail)
  }
  return body
}

export const api = {
  health: () => request('/api/health'),
  repos: () => request('/api/repos'),
  facets: () => request('/api/facets'),
  search: (params) => request('/api/search', params),
  file: (id) => request(`/api/files/${id}`),
  lines: (id, start, end) => request(`/api/files/${id}/lines`, { start, end }),
  chunk: (id, chunkId, context = 1, cell) => request(`/api/files/${id}/chunks/${chunkId}`, { context, cell }),
  pdfUrl: (id) => `/api/files/${id}/raw.pdf`,
  ask: async (question, repoIds) => {
    const res = await fetch('/api/ai/ask', {
      method: 'POST',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, repo_ids: repoIds?.length ? repoIds : null }),
    })
    const body = await res.json().catch(() => ({}))
    if (!res.ok) throw new Error(typeof body.detail === 'string' ? body.detail : `Request failed (${res.status})`)
    return body
  },
  askEvents: async (jobId, signal) => {
    const res = await fetch(`/api/ai/ask/${jobId}/events`, { headers: { Accept: 'text/event-stream' }, signal })
    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      throw new Error(typeof body.detail === 'string' ? body.detail : `Request failed (${res.status})`)
    }
    return res
  },
  cancelAsk: (jobId) => request(`/api/ai/ask/${jobId}`, null, { method: 'DELETE' }),
}
