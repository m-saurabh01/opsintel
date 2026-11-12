function csrfHeaders(headers = {}) {
  const csrf = document.cookie.split('; ').find((part) => part.startsWith('opsintel_csrf='))
    ?.slice('opsintel_csrf='.length)
  return csrf ? { ...headers, 'X-CSRF-Token': decodeURIComponent(csrf) } : headers
}

async function request(path, params, options = {}) {
  const url = new URL(path, window.location.origin)
  for (const [k, v] of Object.entries(params || {})) {
    if (v === undefined || v === null || v === '') continue
    if (Array.isArray(v)) v.forEach((item) => url.searchParams.append(k, item))
    else url.searchParams.set(k, v)
  }
  const method = options.method || 'GET'
  const headers = { Accept: 'application/json', ...(options.body ? { 'Content-Type': 'application/json' } : {}) }
  const res = await fetch(url, {
    method,
    headers: method === 'GET' ? headers : csrfHeaders(headers),
    ...(options.body ? { body: JSON.stringify(options.body) } : {}),
  })
  const body = await res.json().catch(() => ({}))
  if (!res.ok) {
    const detail = typeof body.detail === 'string' ? body.detail : `Request failed (${res.status})`
    const error = new Error(detail)
    error.status = res.status
    throw error
  }
  return body
}

export const api = {
  authStatus: () => request('/api/auth/status'),
  me: () => request('/api/auth/me'),
  login: (body) => request('/api/auth/login', null, { method: 'POST', body }),
  bootstrap: (body) => request('/api/auth/bootstrap', null, { method: 'POST', body }),
  register: (body) => request('/api/auth/register', null, { method: 'POST', body }),
  logout: () => request('/api/auth/logout', null, { method: 'POST' }),
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
      headers: csrfHeaders({ Accept: 'application/json', 'Content-Type': 'application/json' }),
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
  adminStatus: () => request('/api/admin/status'),
  adminUsers: () => request('/api/admin/users'),
  createUser: (body) => request('/api/admin/users', null, { method: 'POST', body }),
  updateUser: (id, body) => request(`/api/admin/users/${id}`, null, { method: 'PATCH', body }),
  addLocalRepo: (body) => request('/api/admin/repos/local', null, { method: 'POST', body }),
  addGiteaRepo: (body) => request('/api/admin/repos/gitea', null, { method: 'POST', body }),
  syncRepo: (id) => request(`/api/admin/repos/${id}/sync`, null, { method: 'POST', body: {} }),
  setRepoEnabled: (id, enabled) => request(`/api/admin/repos/${id}`, null, {
    method: 'PATCH', body: { enabled },
  }),
  removeRepo: (id) => request(`/api/admin/repos/${id}`, null, {
    method: 'DELETE', body: { confirm: true },
  }),
}
