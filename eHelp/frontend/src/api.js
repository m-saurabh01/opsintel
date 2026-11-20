async function request(path, options = {}) {
  const res = await fetch(path, options)
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch { /* keep status text */ }
    throw new Error(detail)
  }
  return res.status === 204 ? null : res.json()
}

const json = (method, body) => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

const qs = (params) => {
  const sp = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') sp.set(k, v)
  })
  const s = sp.toString()
  return s ? `?${s}` : ''
}

export const api = {
  me: () => request('/api/me'),
  settings: () => request('/api/settings'),
  home: () => request('/api/home'),
  categories: () => request('/api/categories'),
  documents: (params) => request(`/api/documents${qs(params)}`),
  document: (id) => request(`/api/documents/${id}`),
  related: (id) => request(`/api/documents/${id}/related`),
  text: (id, offset = 0) => request(`/api/documents/${id}/text${qs({ offset, limit: 100 })}`),
  aiStatus: () => request('/api/ai/status'),
  aiAsk: (question, category, signal) => fetch('/api/ai/ask', { ...json('POST', { question, category }), signal }),
  search: (params) => request(`/api/search${qs(params)}`),
  recordView: (id) => fetch(`/api/documents/${id}/view`, { method: 'POST' }).catch(() => {}),
  fileUrl: (id) => `/api/documents/${id}/file`,
  downloadUrl: (id) => `/api/documents/${id}/download`,

  updateSettings: (body) => request('/api/admin/settings', json('PUT', body)),
  uploadAsset: (file) => {
    const fd = new FormData()
    fd.append('file', file)
    return request('/api/admin/assets', { method: 'POST', body: fd })
  },
  createCategory: (body) => request('/api/admin/categories', json('POST', body)),
  updateCategory: (id, body) => request(`/api/admin/categories/${id}`, json('PUT', body)),
  deleteCategory: (id) => request(`/api/admin/categories/${id}`, { method: 'DELETE' }),
  uploadDocument: (form) => request('/api/admin/documents', { method: 'POST', body: form }),
  updateDocument: (id, body) => request(`/api/admin/documents/${id}`, json('PUT', body)),
  relations: (id) => request(`/api/admin/documents/${id}/relations`),
  replaceFile: (id, file) => {
    const fd = new FormData()
    fd.append('file', file)
    return request(`/api/admin/documents/${id}/file`, { method: 'POST', body: fd })
  },
  reindex: (id) => request(`/api/admin/documents/${id}/reindex`, { method: 'POST' }),
  deleteDocument: (id) => request(`/api/admin/documents/${id}`, { method: 'DELETE' }),
}
