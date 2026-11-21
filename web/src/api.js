export async function api(path, options = {}) {
  const resp = await fetch(path, {
    credentials: 'same-origin',
    ...options,
    headers: options.body instanceof FormData
      ? options.headers
      : { 'Content-Type': 'application/json', ...(options.headers || {}) },
  })
  const text = await resp.text()
  let data = {}
  if (text) {
    try { data = JSON.parse(text) } catch { data = { detail: text.slice(0, 200) } }
  }
  if (!resp.ok) {
    const error = new Error(typeof data.detail === 'string' ? data.detail : '请求失败')
    error.status = resp.status
    error.data = data
    throw error
  }
  return data
}
