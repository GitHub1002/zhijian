export function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;')
}

function inlinePreview(text) {
  return escapeHtml(text)
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/~~(.+?)~~/g, '<del>$1</del>')
    .replace(/\*([^*]+)\*/g, '<em>$1</em>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
}

export function renderEditorPreview(source) {
  const lines = String(source || '').split('\n')
  const output = []
  let inCode = false
  let codeLanguage = ''
  let codeLines = []
  let listType = null
  const closeList = () => {
    if (listType) { output.push(`</${listType}>`); listType = null }
  }
  const closeCode = () => {
    if (!inCode) return
    output.push(`<pre><code>${escapeHtml(codeLines.join('\n'))}</code></pre>`)
    inCode = false
    codeLanguage = ''
    codeLines = []
  }
  lines.forEach(line => {
    const fence = line.match(/^```\s*([\w-]*)\s*$/)
    if (fence) {
      if (inCode) closeCode()
      else { inCode = true; codeLanguage = fence[1] || '' }
      return
    }
    if (inCode) { codeLines.push(line); return }
    if (!line.trim()) { closeList(); return }
    const heading = line.match(/^(#{1,6})\s+(.+)$/)
    if (heading) {
      closeList()
      output.push(`<h${heading[1].length}>${inlinePreview(heading[2])}</h${heading[1].length}>`)
      return
    }
    const quote = line.match(/^>\s?(.*)$/)
    if (quote) { closeList(); output.push(`<blockquote>${inlinePreview(quote[1])}</blockquote>`); return }
    const unordered = line.match(/^[-*+]\s+(.*)$/)
    if (unordered) {
      if (listType !== 'ul') { closeList(); output.push('<ul>'); listType = 'ul' }
      output.push(`<li>${inlinePreview(unordered[1])}</li>`)
      return
    }
    const ordered = line.match(/^\d+[.)]\s+(.*)$/)
    if (ordered) {
      if (listType !== 'ol') { closeList(); output.push('<ol>'); listType = 'ol' }
      output.push(`<li>${inlinePreview(ordered[1])}</li>`)
      return
    }
    closeList()
    output.push(`<p>${inlinePreview(line)}</p>`)
  })
  closeList()
  closeCode()
  return output.join('') || '<p class="preview-empty">预览会显示在这里…</p>'
}

function wrapSelection(textarea, prefix, suffix, placeholder) {
  const start = textarea.selectionStart
  const end = textarea.selectionEnd
  const selected = textarea.value.slice(start, end) || placeholder
  const replacement = prefix + selected + suffix
  textarea.setRangeText(replacement, start, end, 'select')
  textarea.setSelectionRange(start + prefix.length, start + prefix.length + selected.length)
  textarea.focus()
}

function prefixLines(textarea, prefix) {
  const value = textarea.value
  const start = value.lastIndexOf('\n', textarea.selectionStart - 1) + 1
  const endBreak = value.indexOf('\n', textarea.selectionEnd)
  const end = endBreak === -1 ? value.length : endBreak
  const selected = value.slice(start, end)
  const replacement = selected.split('\n').map(line => line.startsWith(prefix) ? line : prefix + line).join('\n')
  textarea.setRangeText(replacement, start, end, 'select')
  textarea.focus()
}

export function applyEditorFormat(textarea, format) {
  if (!textarea) return
  if (format === 'bold') return wrapSelection(textarea, '**', '**', '粗体文字')
  if (format === 'italic') return wrapSelection(textarea, '*', '*', '斜体文字')
  if (format === 'strike') return wrapSelection(textarea, '~~', '~~', '删除线文字')
  if (format === 'inline-code') return wrapSelection(textarea, '`', '`', '代码')
  if (format === 'code-block') return wrapSelection(textarea, '```\n', '\n```', '在这里输入代码')
  if (format === 'quote') return prefixLines(textarea, '> ')
  if (format === 'bullet') return prefixLines(textarea, '- ')
  if (format === 'ordered') return prefixLines(textarea, '1. ')
  if (format === 'checklist') return prefixLines(textarea, '- [ ] ')
  if (format === 'link') return wrapSelection(textarea, '[', '](https://example.com)', '链接文字')
  if (format === 'table') {
    textarea.setRangeText('| 列 1 | 列 2 |\n| --- | --- |\n| 内容 | 内容 |', textarea.selectionStart, textarea.selectionEnd, 'select')
    textarea.focus()
    return
  }
  if (format === 'hr') {
    textarea.setRangeText('\n---\n', textarea.selectionStart, textarea.selectionEnd, 'end')
    textarea.focus()
  }
}

export function applyHeading(textarea, level) {
  if (!textarea || !level) return
  const value = textarea.value
  const start = value.lastIndexOf('\n', textarea.selectionStart - 1) + 1
  const endBreak = value.indexOf('\n', textarea.selectionEnd)
  const end = endBreak === -1 ? value.length : endBreak
  const line = value.slice(start, end).replace(/^#{1,6}\s*/, '')
  textarea.setRangeText(`${'#'.repeat(level)} ${line}`, start, end, 'select')
  textarea.focus()
}

export function formatConversationTime(value) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  const now = new Date()
  if (date.toDateString() === now.toDateString()) {
    return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  }
  return date.toLocaleDateString('zh-CN', { month: 'numeric', day: 'numeric' })
}

export function sourceLabel(source) {
  return source.source + (source.heading ? ` > ${source.heading}` : '')
}

export function compressAvatar(file, size = 256) {
  return new Promise((resolve, reject) => {
    if (!/^image\/(png|jpeg|webp)$/.test(file.type)) {
      reject(new Error('图片读取失败，请换一张 JPG / PNG / WebP 试试'))
      return
    }
    const reader = new FileReader()
    reader.onload = () => {
      const img = new Image()
      img.onload = () => {
        const canvas = document.createElement('canvas')
        canvas.width = size
        canvas.height = size
        const side = Math.min(img.width, img.height)
        canvas.getContext('2d').drawImage(img, (img.width - side) / 2, (img.height - side) / 2, side, side, 0, 0, size, size)
        resolve(canvas.toDataURL('image/jpeg', 0.85))
      }
      img.onerror = () => reject(new Error('图片读取失败，请换一张 JPG / PNG / WebP 试试'))
      img.src = reader.result
    }
    reader.onerror = () => reject(new Error('图片读取失败，请换一张 JPG / PNG / WebP 试试'))
    reader.readAsDataURL(file)
  })
}
