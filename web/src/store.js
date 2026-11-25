import { reactive } from 'vue'
import { api } from './api.js'

const TITLES = { success: '已完成', warn: '请注意', error: '出错了', info: '提示' }
const DURATION = { success: 3000, info: 3600, warn: 4800, error: 6400 }

export const state = reactive({
  booting: true,
  user: null,
  profile: null,
  quota: null,
  authMode: 'login',
  authError: '',
  authBusy: false,
  sidebarTab: 'docs',
  drawerOpen: false,
  viewDoc: false,
  userMenu: false,
  tree: { dirs: [], files: [] },
  libraries: [],
  docQuery: '',
  currentPath: '',
  currentContent: '',
  docHtml: '',
  docEditable: true,
  conversations: [],
  conversationId: null,
  conversationTitle: '',
  messages: [],
  question: '',
  asking: false,
  toasts: [],
  dialog: null,
  docOpen: false,
  adminOpen: false,
  adminUsers: [],
  adminRequests: [],
  adminState: '',
  adminReqState: '',
  adminFeedbackOpen: false,
  adminFeedbackItems: [],
  adminFeedbackPage: 1,
  adminFeedbackPages: 1,
  adminFeedbackTotal: 0,
  adminFeedbackState: '',
  adminFeedbackFilters: { sentiment: '', category: '', status: '', library: '' },
  adminFeedbackDetail: null,
  adminFeedbackDetailState: '',
  adminAnalyticsOverview: null,
  adminAnalyticsLibraries: [],
  adminAnalyticsReasons: [],
  adminAnalyticsCategories: [],
  adminAnalyticsClusters: [],
  adminAnalyticsState: '',
  adminQualityTab: 'feedback',
  adminContentTasks: [],
  adminContentTaskPage: 1,
  adminContentTaskPages: 1,
  adminContentTaskTotal: 0,
  adminContentTaskState: '',
  adminContentTaskFilters: { status: '', priority: '' },
  adminCuratedExamples: [],
  adminCuratedPage: 1,
  adminCuratedPages: 1,
  adminCuratedTotal: 0,
  adminCuratedState: '',
  adminCuratedFilters: { status: '', library: '' },
  adminExperiments: [],
  adminExperimentState: '',
  adminExperimentResults: null,
  adminExperimentResultsState: '',
  adminEvalRuns: [],
  adminEvalPage: 1,
  adminEvalPages: 1,
  adminEvalTotal: 0,
  adminEvalState: '',
  adminEvalDetail: null,
  adminEvalDetailState: '',
  adminAuditEvents: [],
  adminAuditPage: 1,
  adminAuditPages: 1,
  adminAuditTotal: 0,
  adminAuditState: '',
  permissionOpen: false,
  permissions: [],
  permissionState: '',
  permissionAdmin: false,
  profileOpen: false,
  helpOpen: false,
  ingestBusy: false,
})

let toastSeq = 1

export function notify(message, kind = 'info') {
  const id = toastSeq++
  state.toasts.push({ id, message, kind, title: TITLES[kind] || '提示' })
  window.setTimeout(() => dismissToast(id), DURATION[kind] || 3600)
}

export function dismissToast(id) {
  state.toasts = state.toasts.filter(item => item.id !== id)
}

export function askDialog(options) {
  return new Promise(resolve => {
    state.dialog = { ...options, resolve }
  })
}

export function closeDialog(ok, value = null) {
  const dialog = state.dialog
  state.dialog = null
  if (dialog) dialog.resolve(ok ? value : null)
}

function countDocs(node) {
  if (!node) return 0
  return (node.files || []).length + (node.dirs || []).reduce((sum, dir) => sum + countDocs(dir), 0)
}

export function docCount() {
  return countDocs(state.tree)
}

export function collectDirs(node = state.tree, prefix = '', out = []) {
  ;(node.dirs || []).forEach(dir => {
    const path = prefix ? `${prefix}/${dir.name}` : dir.name
    out.push(path)
    collectDirs(dir, path, out)
  })
  return out
}

export function displayName() {
  return state.profile?.display_name || state.user?.username || ''
}

export function initials(name) {
  return (name || 'KB').slice(0, 2).toUpperCase()
}

function enter(payload) {
  state.user = payload.user
  state.quota = payload.quota
  state.authError = ''
  document.body.classList.remove('auth-locked')
  return Promise.all([loadDocs(), loadConversations(), loadProfile()])
}

export async function boot() {
  try {
    const data = await api('/api/auth/me')
    await enter(data)
  } catch {
    state.user = null
    document.body.classList.add('auth-locked')
  } finally {
    state.booting = false
  }
}

export async function submitAuth(username, password) {
  state.authBusy = true
  state.authError = ''
  try {
    const data = await api(`/api/auth/${state.authMode}`, {
      method: 'POST',
      body: JSON.stringify({ username: username.trim(), password }),
    })
    await enter(data)
  } catch (error) {
    state.authError = error.message
  } finally {
    state.authBusy = false
  }
}

export async function logout() {
  try { await api('/api/auth/logout', { method: 'POST' }) } catch { /* 仍回到登录页 */ }
  window.location.reload()
}

export async function loadProfile() {
  const profile = await api('/api/profile')
  state.profile = profile
  return profile
}

export async function saveProfile(body) {
  const data = await api('/api/profile', { method: 'POST', body: JSON.stringify(body) })
  state.profile = data.profile
  return data.profile
}

export async function loadDocs() {
  const data = await api('/api/docs')
  state.tree = data.tree || { dirs: [], files: [] }
  state.libraries = data.libraries || []
}

export function uploadLibraries() {
  const options = []
  if (state.user?.role === 'admin') options.push({ value: 'common', label: '全员' })
  for (const item of state.libraries) {
    if (item.status === 'approved' && item.permission_key) {
      options.push({ value: item.permission_key, label: item.name || item.permission_key })
    }
  }
  return options
}

export async function openDoc(path, anchor = '') {
  const data = await api('/api/doc/' + encodeURIComponent(path))
  state.currentPath = path
  state.currentContent = data.content || ''
  state.docHtml = data.html || ''
  state.docEditable = data.editable !== false
  state.sidebarTab = 'docs'
  if (window.matchMedia('(max-width: 1023px)').matches) {
    state.viewDoc = true
    state.drawerOpen = false
  }
  if (anchor) {
    requestAnimationFrame(() => {
      const target = document.getElementById(anchor)
      if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' })
    })
  }
}

export async function saveDoc({ edit, name, dir, content }) {
  const path = edit ? state.currentPath : `${dir ? dir.replace(/\\/g, '/').replace(/^\/+|\/+$/g, '') + '/' : ''}${name}`
  try {
    const data = edit
      ? await api('/api/doc/' + encodeURIComponent(state.currentPath), { method: 'PUT', body: JSON.stringify({ content }) })
      : await api('/api/doc', { method: 'POST', body: JSON.stringify({ path, content }) })
    const saved = edit ? state.currentPath : data.path
    state.docOpen = false
    notify(`已保存「${saved}」`, 'success')
    await loadDocs()
    await openDoc(saved)
  } catch (error) {
    if (error.status === 403 && String(error.message).includes('请先申请权限')) {
      const go = await askDialog({
        eyebrow: 'NO PERMISSION',
        title: '该目录已存在',
        message: error.message,
        okLabel: '去申请权限',
      })
      if (go !== null) {
        state.docOpen = false
        openPermissions()
      }
      return
    }
    notify('保存失败：' + error.message, 'error')
  }
}

export async function deleteDoc() {
  if (!state.currentPath) return
  const target = state.currentPath
  const ok = await askDialog({
    eyebrow: 'DELETE DOCUMENT',
    title: '删除这篇文档',
    message: `将永久删除「${target}」。删除后需要重新上传才能恢复。`,
    okLabel: '删除文档',
  })
  if (ok === null) return
  try {
    await api('/api/doc/' + encodeURIComponent(target), { method: 'DELETE' })
    state.currentPath = ''
    state.currentContent = ''
    state.docHtml = ''
    notify(`已删除「${target}」`, 'success')
    await loadDocs()
  } catch (error) {
    notify('删除失败：' + error.message, 'error')
  }
}

export async function uploadFiles(files, dir) {
  const form = new FormData()
  for (const file of files) form.append('files', file)
  form.append('dir', dir || '')
  try {
    const data = await api('/api/upload', { method: 'POST', body: form })
    const skipped = data.skipped || []
    if (data.uploaded.length) {
      const extra = skipped.length ? `，另有 ${skipped.length} 个未收入` : ''
      notify(`已上传 ${data.uploaded.length} 个文档${extra}`, skipped.length ? 'warn' : 'success')
      await loadDocs()
    } else {
      notify(skipped.map(item => `${item.name}：${item.reason}`).join('；') || '没有可上传的文档', 'warn')
    }
  } catch (error) {
    notify('上传失败：' + error.message, 'error')
  }
}

export async function syncDir(source) {
  try {
    const data = await api('/api/sync', { method: 'POST', body: JSON.stringify({ source_dir: source }) })
    const extra = data.skipped && data.skipped.length ? `，另有 ${data.skipped.length} 个未收入` : ''
    notify(`已同步 ${data.count} 个文档${extra}`, extra ? 'warn' : 'success')
    await loadDocs()
  } catch (error) {
    notify('同步失败：' + error.message, 'error')
  }
}

export async function ingest() {
  const ok = await askDialog({
    eyebrow: 'REINDEX',
    title: '重建全部索引',
    message: '将重新扫描文档目录并重建向量与关键词索引。文档较多时需要一两分钟，期间可以继续浏览已有内容。',
    okLabel: '开始重建',
  })
  if (ok === null) return
  state.ingestBusy = true
  try {
    const data = await api('/api/ingest', { method: 'POST' })
    notify(`索引完成：${data.files} 篇文档，${data.chunks} 个片段`, 'success')
    await loadDocs()
  } catch (error) {
    notify('索引失败：' + error.message, 'error')
  } finally {
    state.ingestBusy = false
  }
}

export async function loadConversations() {
  const data = await api('/api/conversations')
  state.conversations = data.conversations || []
}

export function startNewConversation() {
  state.conversationId = null
  state.conversationTitle = ''
  state.messages = []
  state.question = ''
  state.viewDoc = false
}

export async function openConversation(id) {
  const data = await api('/api/conversations/' + encodeURIComponent(id))
  state.conversationId = data.id
  state.conversationTitle = data.title || ''
  state.messages = []
  ;(data.messages || []).forEach(item => {
    state.messages.push({ key: `q-${item.answer_id}`, role: 'user', text: item.question })
    state.messages.push({
      key: `a-${item.answer_id}`,
      role: 'ai',
      html: item.answer_html || '',
      text: '',
      sources: dedupeSources(item.sources || []),
      answerId: item.answer_id,
      rating: item.rating,
      feedback: item.feedback || null,
      pending: false,
    })
  })
  state.viewDoc = false
  if (window.matchMedia('(max-width: 1023px)').matches) state.drawerOpen = false
}

export async function deleteConversation(item) {
  const ok = await askDialog({
    eyebrow: 'DELETE CHAT',
    title: '删除这组对话',
    message: `将删除「${item.title || '这组对话'}」，其中的提问和回答会一并清除。`,
    okLabel: '删除对话',
  })
  if (ok === null) return
  try {
    await api('/api/conversations/' + encodeURIComponent(item.id), { method: 'DELETE' })
    if (state.conversationId === item.id) startNewConversation()
    await loadConversations()
  } catch (error) {
    notify(error.message || '删除失败', 'error')
  }
}

function dedupeSources(sources) {
  const seen = new Set()
  return sources.filter(source => {
    const label = source.source + (source.heading ? ` > ${source.heading}` : '')
    if (seen.has(label)) return false
    seen.add(label)
    return true
  })
}

function parseSseBlock(block) {
  let event = 'message'
  const dataLines = []
  block.split('\n').forEach(line => {
    if (line.startsWith('event:')) event = line.slice(6).trim()
    else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim())
  })
  if (!dataLines.length) return null
  return { event, data: JSON.parse(dataLines.join('\n')) }
}

export async function ask() {
  const question = state.question.trim()
  if (!question || state.asking) return
  state.question = ''
  state.asking = true
  state.messages.push({ key: `u-${Date.now()}`, role: 'user', text: question })
  const bubble = {
    key: `a-${Date.now()}`,
    role: 'ai',
    html: '',
    text: '',
    sources: [],
    answerId: null,
    rating: null,
    pending: true,
    error: '',
  }
  state.messages.push(bubble)
  try {
    const resp = await fetch('/api/ask', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, conversation_id: state.conversationId }),
    })
    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}))
      bubble.pending = false
      bubble.error = data.detail || '未知错误'
      return
    }
    // 拒答是一次 JSON。有依据时改为事件流：token 先显示，done 再补出处和剩余次数。
    const contentType = resp.headers.get('content-type') || ''
    if (!contentType.includes('text/event-stream')) {
      applyAnswer(bubble, await resp.json())
      return
    }
    const reader = resp.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      let splitAt = buffer.indexOf('\n\n')
      while (splitAt >= 0) {
        const raw = buffer.slice(0, splitAt)
        buffer = buffer.slice(splitAt + 2)
        const parsed = parseSseBlock(raw)
        if (parsed?.event === 'error') {
          bubble.pending = false
          bubble.error = parsed.data.detail || '未知错误'
          return
        }
        if (parsed?.event === 'done') {
          applyAnswer(bubble, parsed.data)
          return
        }
        if (parsed?.event === 'token' && parsed.data.token) bubble.text += parsed.data.token
        splitAt = buffer.indexOf('\n\n')
      }
    }
    bubble.pending = false
  } catch (error) {
    bubble.pending = false
    bubble.error = error.message || '请求失败'
  } finally {
    state.asking = false
  }
}

function applyAnswer(bubble, data) {
  bubble.pending = false
  bubble.html = data.answer_html || ''
  bubble.text = data.answer || bubble.text
  bubble.sources = dedupeSources(data.sources || [])
  bubble.answerId = data.answer_id || null
  bubble.rating = data.rating || null
  bubble.traceId = data.trace_id || null
  bubble.feedback = null
  if (data.quota) state.quota = data.quota
  if (data.conversation_id) {
    state.conversationId = data.conversation_id
    loadConversations().then(() => {
      const current = state.conversations.find(item => item.id === state.conversationId)
      if (current) state.conversationTitle = current.title
    }).catch(() => {})
  }
}

export function recordSourceClick(message, source) {
  if (!message || !message.answerId) return
  const payload = JSON.stringify({
    answer_id: message.answerId,
    source: source.source || '',
    heading: source.heading || '',
    anchor: source.anchor || '',
    library: source.library || '',
    source_index: source.index || 0,
  })
  if (navigator.sendBeacon) {
    navigator.sendBeacon(
      '/api/source-click',
      new Blob([payload], { type: 'application/json' })
    )
    return
  }
  fetch('/api/source-click', {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: payload,
    keepalive: true,
  }).catch(() => {})
}

export async function sendFeedback(message, payload) {
  const data = await api('/api/feedback', {
    method: 'POST',
    body: JSON.stringify({ answer_id: message.answerId, ...payload }),
  })
  message.feedback = data.feedback || null
  message.rating = message.feedback?.rating || null
  return message.feedback
}

export async function updateFeedback(message, payload) {
  if (!message.feedback?.id) return sendFeedback(message, payload)
  const data = await api(`/api/feedback/${encodeURIComponent(message.feedback.id)}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
  message.feedback = data.feedback || message.feedback
  message.rating = message.feedback?.rating || null
  return message.feedback
}

export async function loadFeedbackForAnswer(answerId) {
  const data = await api(`/api/feedback/answer/${encodeURIComponent(answerId)}`)
  return data.feedback || null
}

export async function openAdminFeedback() {
  state.adminFeedbackOpen = true
  state.adminFeedbackDetail = null
  await Promise.all([
    loadAdminFeedback(1),
    loadAdminAnalytics(),
    state.adminQualityTab === 'tasks'
      ? loadAdminContentTasks(1)
      : state.adminQualityTab === 'curated'
        ? loadAdminCuratedExamples(1)
        : state.adminQualityTab === 'experiments'
          ? loadAdminExperiments()
          : state.adminQualityTab === 'eval'
            ? loadAdminEvalRuns(1)
            : state.adminQualityTab === 'audit'
              ? loadAdminAudit(1)
              : Promise.resolve(),
  ])
}

export async function loadAdminAudit(page = 1) {
  state.adminAuditState = '正在加载审计记录…'
  try {
    const data = await api(
      `/api/admin/audit-log?page=${encodeURIComponent(page)}&page_size=20`
    )
    state.adminAuditEvents = data.items || []
    state.adminAuditPage = data.page || 1
    state.adminAuditPages = data.pages || 1
    state.adminAuditTotal = data.total || 0
    state.adminAuditState = ''
  } catch (error) {
    state.adminAuditState = error.message
  }
}

export async function loadAdminEvalRuns(page = 1) {
  state.adminEvalState = '正在加载评测记录…'
  try {
    const data = await api(
      `/api/admin/eval/runs?page=${encodeURIComponent(page)}&page_size=20`
    )
    state.adminEvalRuns = data.items || []
    state.adminEvalPage = data.page || 1
    state.adminEvalPages = data.pages || 1
    state.adminEvalTotal = data.total || 0
    state.adminEvalState = ''
  } catch (error) {
    state.adminEvalState = error.message
  }
}

export async function loadAdminEvalRun(runId) {
  state.adminEvalDetail = null
  state.adminEvalDetailState = '正在加载评测详情…'
  try {
    const data = await api(`/api/admin/eval/runs/${encodeURIComponent(runId)}`)
    state.adminEvalDetail = data.run || null
    state.adminEvalDetailState = ''
  } catch (error) {
    state.adminEvalDetailState = error.message
  }
}

export async function loadAdminExperiments() {
  state.adminExperimentState = '正在加载实验…'
  try {
    const data = await api('/api/admin/experiments')
    state.adminExperiments = data.items || []
    state.adminExperimentState = ''
  } catch (error) {
    state.adminExperimentState = error.message
  }
}

export async function createExperiment(payload) {
  try {
    const data = await api('/api/admin/experiments', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
    notify('实验已创建', 'success')
    await loadAdminExperiments()
    return data.experiment
  } catch (error) {
    notify(error.message, 'error')
    return null
  }
}

export async function updateExperiment(key, payload) {
  try {
    const data = await api(`/api/admin/experiments/${encodeURIComponent(key)}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    })
    state.adminExperiments = state.adminExperiments.map(item =>
      item.key === data.experiment.key ? data.experiment : item
    )
    notify('实验已更新', 'success')
    return data.experiment
  } catch (error) {
    notify(error.message, 'error')
    return null
  }
}

export async function loadExperimentResults(key) {
  state.adminExperimentResults = null
  state.adminExperimentResultsState = '正在加载实验结果…'
  try {
    const data = await api(
      `/api/admin/experiments/${encodeURIComponent(key)}/results`
    )
    state.adminExperimentResults = data
    state.adminExperimentResultsState = ''
  } catch (error) {
    state.adminExperimentResultsState = error.message
  }
}

export async function loadAdminCuratedExamples(page = 1) {
  state.adminCuratedState = '正在加载精选正例…'
  const params = new URLSearchParams({ page: String(page), page_size: '20' })
  Object.entries(state.adminCuratedFilters).forEach(([key, value]) => {
    if (value) params.set(key, value)
  })
  try {
    const data = await api(`/api/admin/curated-examples?${params.toString()}`)
    state.adminCuratedExamples = data.items || []
    state.adminCuratedPage = data.page || 1
    state.adminCuratedPages = data.pages || 1
    state.adminCuratedTotal = data.total || 0
    state.adminCuratedState = ''
  } catch (error) {
    state.adminCuratedState = error.message
  }
}

export async function updateCuratedExample(exampleId, payload) {
  try {
    const data = await api(`/api/admin/curated-examples/${encodeURIComponent(exampleId)}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    })
    state.adminCuratedExamples = state.adminCuratedExamples.map(item =>
      item.id === data.example.id ? data.example : item
    )
    notify('精选正例已更新', 'success')
    return data.example
  } catch (error) {
    notify(error.message, 'error')
    return null
  }
}

export async function loadAdminContentTasks(page = 1) {
  state.adminContentTaskState = '正在加载内容任务…'
  const params = new URLSearchParams({ page: String(page), page_size: '20' })
  Object.entries(state.adminContentTaskFilters).forEach(([key, value]) => {
    if (value) params.set(key, value)
  })
  try {
    const data = await api(`/api/admin/content-tasks?${params.toString()}`)
    state.adminContentTasks = data.items || []
    state.adminContentTaskPage = data.page || 1
    state.adminContentTaskPages = data.pages || 1
    state.adminContentTaskTotal = data.total || 0
    state.adminContentTaskState = ''
  } catch (error) {
    state.adminContentTaskState = error.message
  }
}

export async function createTaskFromFeedback(feedbackId) {
  try {
    const data = await api(`/api/admin/feedback/${encodeURIComponent(feedbackId)}/task`, {
      method: 'POST',
      body: JSON.stringify({}),
    })
    notify(data.created ? '已创建内容任务' : '已关联到现有内容任务', 'success')
    await Promise.all([
      loadAdminFeedback(state.adminFeedbackPage),
      loadAdminContentTasks(1),
    ])
    return data.task
  } catch (error) {
    notify(error.message, 'error')
    return null
  }
}

export async function updateContentTask(taskId, payload) {
  try {
    const data = await api(`/api/admin/content-tasks/${encodeURIComponent(taskId)}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    })
    state.adminContentTasks = state.adminContentTasks.map(item =>
      item.id === data.task.id ? data.task : item
    )
    notify('内容任务已更新', 'success')
    return data.task
  } catch (error) {
    notify(error.message, 'error')
    return null
  }
}

export async function loadAdminAnalytics() {
  state.adminAnalyticsState = '正在加载看板…'
  try {
    const [overview, libraries, reasons, categories, clusters] = await Promise.all([
      api('/api/admin/analytics/overview'),
      api('/api/admin/analytics/libraries'),
      api('/api/admin/analytics/reasons'),
      api('/api/admin/analytics/categories'),
      api('/api/admin/analytics/clusters'),
    ])
    state.adminAnalyticsOverview = overview || null
    state.adminAnalyticsLibraries = libraries.items || []
    state.adminAnalyticsReasons = reasons.items || []
    state.adminAnalyticsCategories = categories.items || []
    state.adminAnalyticsClusters = clusters.items || []
    state.adminAnalyticsState = ''
  } catch (error) {
    state.adminAnalyticsState = error.message
  }
}

export function exportAdminFeedback() {
  const params = new URLSearchParams()
  Object.entries(state.adminFeedbackFilters).forEach(([key, value]) => {
    if (value) params.set(key, value)
  })
  const query = params.toString()
  const link = document.createElement('a')
  link.href = `/api/admin/feedback/export.csv${query ? `?${query}` : ''}`
  link.download = 'feedback.csv'
  document.body.appendChild(link)
  link.click()
  link.remove()
}

export async function loadAdminFeedback(page = 1) {
  state.adminFeedbackState = '正在加载反馈…'
  const params = new URLSearchParams({ page: String(page), page_size: '20' })
  Object.entries(state.adminFeedbackFilters).forEach(([key, value]) => {
    if (value) params.set(key, value)
  })
  try {
    const data = await api(`/api/admin/feedback?${params.toString()}`)
    state.adminFeedbackItems = data.items || []
    state.adminFeedbackPage = data.page || 1
    state.adminFeedbackPages = data.pages || 1
    state.adminFeedbackTotal = data.total || 0
    state.adminFeedbackState = ''
  } catch (error) {
    state.adminFeedbackState = error.message
  }
}

export async function loadAdminFeedbackDetail(id) {
  state.adminFeedbackDetailState = '正在加载详情…'
  try {
    const data = await api(`/api/admin/feedback/${encodeURIComponent(id)}`)
    state.adminFeedbackDetail = data.feedback || null
    state.adminFeedbackDetailState = ''
  } catch (error) {
    state.adminFeedbackDetailState = error.message
  }
}

export async function triageFeedback(id, payload) {
  const data = await api(`/api/admin/feedback/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
  state.adminFeedbackDetail = data.feedback || state.adminFeedbackDetail
  notify('反馈状态已更新', 'success')
  await Promise.all([loadAdminFeedback(state.adminFeedbackPage), loadAdminAnalytics()])
}

export async function openPermissions() {
  state.permissionOpen = true
  state.permissionState = '正在加载权限…'
  try {
    const data = await api('/api/permissions')
    state.permissions = data.permissions || []
    state.permissionAdmin = Boolean(data.is_admin)
    state.permissionState = data.is_admin
      ? '管理员拥有全部知识库权限。'
      : '申请后由管理员审批，通过后即可查看对应库文档。'
  } catch (error) {
    state.permissionState = error.message
  }
}

export async function requestPermission(key) {
  const data = await api(`/api/permissions/${encodeURIComponent(key)}/request`, { method: 'POST' })
  state.permissions = data.permissions || []
  await loadDocs()
}

export async function openAdmin() {
  state.adminOpen = true
  await refreshAdmin()
}

export async function refreshAdmin() {
  state.adminState = '正在加载用户…'
  state.adminReqState = '正在加载申请…'
  try {
    const [users, requests] = await Promise.all([
      api('/api/admin/users'),
      api('/api/admin/permission-requests'),
    ])
    state.adminUsers = users.users || []
    state.adminRequests = (requests.requests || []).filter(item => item.status === 'pending')
    state.adminState = ''
    state.adminReqState = ''
  } catch (error) {
    state.adminState = error.message
    state.adminReqState = error.message
  }
}

export async function reviewPermission(id, status) {
  await api(`/api/admin/permission-requests/${encodeURIComponent(id)}`, {
    method: 'POST',
    body: JSON.stringify({ status }),
  })
  await refreshAdmin()
}

export async function resetQuota(user) {
  const ok = await askDialog({
    eyebrow: 'RESET QUOTA',
    title: '重置今日额度',
    message: `将把「${user.username}」今天的 AI 咨询次数清零，重置后可以重新使用 10 次。`,
    okLabel: '重置额度',
  })
  if (ok === null) return
  await api(`/api/admin/users/${encodeURIComponent(user.id)}/reset-quota`, { method: 'POST' })
  notify(`已重置「${user.username}」的今日额度`, 'success')
  await refreshAdmin()
}

export async function deleteUser(user) {
  const ok = await askDialog({
    eyebrow: 'DELETE USER',
    title: '删除这个用户',
    message: `将永久删除「${user.username}」，它的会话、问答记录和权限申请会一并清除。此操作无法撤销。`,
    okLabel: '删除用户',
  })
  if (ok === null) return
  await api(`/api/admin/users/${encodeURIComponent(user.id)}`, { method: 'DELETE' })
  notify(`已删除用户「${user.username}」`, 'success')
  await refreshAdmin()
}
