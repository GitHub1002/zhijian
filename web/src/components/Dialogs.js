import { ref, computed, watch } from 'vue'
import { state, closeDialog, dismissToast, notify, askDialog, saveDoc, collectDirs, refreshAdmin, reviewPermission, resetQuota, deleteUser, requestPermission, saveProfile } from '../store.js'
import { applyEditorFormat, applyHeading, renderEditorPreview, compressAvatar } from '../editor.js'

export const ToastStack = {
  setup() { return { state, dismissToast } },
  template: `
    <div class="toast-stack" role="region" aria-label="通知">
      <div v-for="toast in state.toasts" :key="toast.id" class="toast" :class="toast.kind" :role="toast.kind === 'error' || toast.kind === 'warn' ? 'alert' : 'status'">
        <div class="toast-body"><strong>{{ toast.title }}</strong><p>{{ toast.message }}</p></div>
        <button class="toast-close" type="button" aria-label="关闭通知" @click="dismissToast(toast.id)">×</button>
      </div>
    </div>
  `,
}

export const ConfirmDialog = {
  setup() {
    const input = ref('')
    const selected = ref('')
    const menuOpen = ref(false)
    const hasInput = computed(() => state.dialog?.mode === 'prompt')
    const hasSelect = computed(() => state.dialog?.mode === 'select')
    const selectedLabel = computed(() => {
      const options = state.dialog?.options || []
      return options.find(item => item.value === selected.value)?.label || '请选择'
    })
    watch(() => state.dialog, (dialog) => {
      input.value = ''
      menuOpen.value = false
      selected.value = dialog?.value || dialog?.options?.[0]?.value || ''
    })
    function chooseLibrary(value) {
      selected.value = value
      menuOpen.value = false
    }
    function finish(ok) {
      const value = hasSelect.value ? selected.value : (hasInput.value ? input.value.trim() : true)
      input.value = ''
      menuOpen.value = false
      closeDialog(ok, ok ? value : null)
    }
    return { state, hasInput, hasSelect, input, selected, selectedLabel, menuOpen, chooseLibrary, finish }
  },
  template: `
    <div v-if="state.dialog" class="modal-overlay" style="display:flex" @click.self="finish(false)">
      <div class="modal" role="dialog" aria-modal="true" style="max-width:33rem">
        <div class="modal-header"><div><span class="modal-eyebrow">{{ state.dialog.eyebrow || (hasInput || hasSelect ? 'INPUT' : 'CONFIRM') }}</span><span>{{ state.dialog.title || '请确认' }}</span></div></div>
        <div class="modal-body">
          <p class="admin-copy" :style="hasInput || hasSelect ? '' : 'margin-bottom:0'">{{ state.dialog.message }}</p>
          <label v-if="hasInput" class="field" style="margin-top:1rem;display:block">
            <span>{{ state.dialog.inputLabel || '内容' }}</span>
            <input v-model="input" type="text" :placeholder="state.dialog.placeholder || ''" @keydown.enter.prevent="finish(true)">
          </label>
          <div v-if="hasSelect" class="field library-field">
            <span>{{ state.dialog.inputLabel || '知识库' }}</span>
            <div class="library-select">
              <button type="button" class="library-select-btn" :aria-expanded="menuOpen" @click="menuOpen = !menuOpen">
                <span>{{ selectedLabel }}</span>
                <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4 6.2 8 10.2 12 6.2"/></svg>
              </button>
              <div v-if="menuOpen" class="library-select-menu" role="listbox">
                <button v-for="item in state.dialog.options" :key="item.value" type="button" class="library-select-item" :class="{ active: item.value === selected }" role="option" :aria-selected="item.value === selected" @click="chooseLibrary(item.value)">{{ item.label }}</button>
              </div>
            </div>
          </div>
        </div>
        <div class="modal-footer">
          <button class="toolbar-btn" type="button" @click="finish(false)">{{ state.dialog.cancelLabel || '取消' }}</button>
          <button class="primary-btn" type="button" @click="finish(true)">{{ state.dialog.okLabel || '确定' }}</button>
        </div>
      </div>
    </div>
  `,
}

export const DocModal = {
  setup() {
    const name = ref('')
    const dir = ref('')
    const content = ref('')
    const preview = ref(false)
    const extraDirs = ref([])
    const headingOpen = ref(false)
    const area = ref(null)
    const edit = computed(() => state.docOpen === 'edit')
    const dirs = computed(() => [...new Set([...collectDirs(), ...extraDirs.value])])
    const previewHtml = computed(() => renderEditorPreview(content.value))

    watch(() => state.docOpen, (mode) => {
      if (!mode) return
      preview.value = false
      headingOpen.value = false
      extraDirs.value = []
      if (mode === 'edit') {
        const parts = state.currentPath.split('/')
        name.value = parts[parts.length - 1].replace(/\.md$/i, '')
        dir.value = parts.length > 1 ? parts.slice(0, -1).join('/') : ''
        content.value = state.currentContent
      } else {
        name.value = ''
        content.value = ''
        dir.value = collectDirs()[0] || ''
      }
    })

    async function addDir() {
      const value = await askDialog({
        mode: 'prompt',
        eyebrow: 'NEW DIRECTORY',
        title: '新建目录',
        message: '输入新目录名称，可含多级（如「运营/周报」）。保存文档时会一并创建。',
        inputLabel: '目录名',
        placeholder: '如：运营资料',
        okLabel: '创建',
      })
      if (value === null) return
      const next = String(value).trim().replace(/\\/g, '/').replace(/^\/+|\/+$/g, '')
      if (!next) { notify('目录名不能为空', 'error'); return }
      if (!extraDirs.value.includes(next)) extraDirs.value.push(next)
      dir.value = next
    }

    function format(kind) {
      applyEditorFormat(area.value, kind)
      content.value = area.value.value
    }

    function chooseHeading(level) {
      headingOpen.value = false
      applyHeading(area.value, level)
      content.value = area.value.value
    }

    function onKey(event) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') { event.preventDefault(); submit() }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'b') { event.preventDefault(); format('bold') }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'i') { event.preventDefault(); format('italic') }
    }

    function submit() {
      if (!edit.value && !name.value.trim()) { notify('请先填写文档标题', 'warn'); return }
      saveDoc({ edit: edit.value, name: name.value.trim(), dir: dir.value.trim(), content: content.value })
    }

    return { state, name, dir, content, preview, edit, dirs, previewHtml, area, headingOpen, addDir, format, chooseHeading, onKey, submit }
  },
  template: `
    <div v-if="state.docOpen" class="modal-overlay" style="display:flex" @click.self="state.docOpen = false">
      <div class="modal doc-modal" role="dialog" aria-modal="true">
        <div class="modal-header">
          <div>
            <span class="modal-eyebrow">MARKDOWN DOCUMENT</span>
            <span class="modal-title">{{ edit ? '编辑文档' : '新建文档' }}</span>
            <span v-if="edit" class="modal-path">{{ state.currentPath }}</span>
          </div>
          <button class="modal-close" type="button" aria-label="关闭" @click="state.docOpen = false">×</button>
        </div>
        <div class="modal-body">
          <div v-if="!edit" class="field-grid">
            <label class="field"><span>标题</span><input v-model="name" type="text" placeholder="如：新员工手册"></label>
            <div class="field">
              <span>目录</span>
              <div class="dir-select-row">
                <select v-model="dir">
                  <option value="">文档库根目录</option>
                  <option v-for="item in dirs" :key="item" :value="item">{{ item }}</option>
                </select>
                <button class="dir-new-btn" type="button" @click="addDir">新建目录</button>
              </div>
            </div>
          </div>
          <span class="field-label">内容（Markdown）</span>
          <div class="editor-shell">
            <div class="editor-toolbar" role="toolbar" aria-label="Markdown 编辑工具栏" @click="headingOpen = false">
              <div class="editor-heading" @click.stop>
                <button type="button" class="editor-mode-btn" :aria-expanded="headingOpen" aria-label="标题层级" @click="headingOpen = !headingOpen">标题</button>
                <div v-if="headingOpen" class="editor-heading-menu" role="listbox">
                  <button v-for="level in 6" :key="level" type="button" class="editor-heading-item" role="option" @click="chooseHeading(level)">{{ level }} 级标题</button>
                </div>
              </div>
              <span class="editor-divider" aria-hidden="true"></span>
              <button type="button" class="editor-tool strong" @click="format('bold')">B</button>
              <button type="button" class="editor-tool italic" @click="format('italic')">I</button>
              <button type="button" class="editor-tool strike" @click="format('strike')">S</button>
              <button type="button" class="editor-tool" @click="format('bullet')">•</button>
              <button type="button" class="editor-tool" @click="format('ordered')">1.</button>
              <button type="button" class="editor-tool" @click="format('code-block')">代码</button>
              <button type="button" class="editor-tool" @click="format('link')">链接</button>
              <button type="button" class="editor-tool" @click="format('table')">表格</button>
              <span class="editor-toolbar-spacer"></span>
              <button type="button" class="editor-mode-btn" @click="preview = !preview">{{ preview ? '源码' : '预览' }}</button>
            </div>
            <div class="editor-surface">
              <textarea v-show="!preview" ref="area" v-model="content" placeholder="开始写作，或使用上方工具栏插入标题、列表、代码和表格…" @focus="headingOpen = false" @keydown="onKey"></textarea>
              <div v-show="preview" class="editor-preview markdown" v-html="previewHtml"></div>
            </div>
            <div class="editor-status"><span>{{ preview ? 'Markdown 预览' : 'Markdown 源码' }}</span><span><kbd>Ctrl</kbd> + <kbd>S</kbd> 保存</span></div>
          </div>
        </div>
        <div class="modal-footer">
          <button class="toolbar-btn" type="button" @click="state.docOpen = false">取消</button>
          <button class="primary-btn" type="button" @click="submit">保存文档</button>
        </div>
      </div>
    </div>
  `,
}

export const AdminModal = {
  setup() {
    return { state, refreshAdmin, reviewPermission, resetQuota, deleteUser }
  },
  template: `
    <div v-if="state.adminOpen" class="modal-overlay" style="display:flex" @click.self="state.adminOpen = false">
      <div class="modal admin-modal" role="dialog" aria-modal="true">
        <div class="modal-header">
          <div><span class="modal-eyebrow">ADMIN CONTROL</span><span>权限与额度管理</span></div>
          <button class="modal-close" type="button" aria-label="关闭" @click="state.adminOpen = false">×</button>
        </div>
        <div class="modal-body">
          <p class="admin-copy">管理员默认拥有全部知识库权限。先处理权限申请，再按需重置额度或删除用户；删除用户会一并清理其会话、问答记录和权限申请，操作不可撤销。</p>
          <div class="admin-section-title">待审批的知识库权限</div>
          <div v-if="state.adminReqState" class="admin-users-state">{{ state.adminReqState }}</div>
          <div class="admin-users-list">
            <div v-if="!state.adminRequests.length" class="admin-empty">暂无待审批申请。</div>
            <div v-for="item in state.adminRequests" :key="item.id" class="admin-user-row permission-admin-row">
              <div class="admin-user-main"><strong>{{ item.username }}</strong><span>申请「{{ item.name }}」</span></div>
              <div class="admin-user-action">
                <button class="admin-approve-btn" type="button" @click="reviewPermission(item.id, 'approved')">通过</button>
                <button class="admin-reject-btn" type="button" @click="reviewPermission(item.id, 'rejected')">拒绝</button>
              </div>
            </div>
          </div>
          <div class="admin-section-title">用户额度</div>
          <div v-if="state.adminState" class="admin-users-state">{{ state.adminState }}</div>
          <div class="admin-users-list">
            <div v-if="!state.adminUsers.length" class="admin-empty">还没有注册用户。</div>
            <div v-for="user in state.adminUsers" :key="user.id" class="admin-user-row">
              <div class="admin-user-main">
                <strong>{{ user.username }}</strong>
                <span>{{ user.role === 'admin' || user.quota?.unlimited ? '无限制' : '剩余 ' + (user.quota?.remaining || 0) + ' / ' + (user.quota?.limit || 10) + ' 次' }}</span>
              </div>
              <div class="admin-user-action">
                <span v-if="user.role === 'admin'" class="admin-role">管理员</span>
                <div v-else class="admin-user-actions">
                  <button class="admin-reset-btn" type="button" @click="resetQuota(user)">重置今日额度</button>
                  <button class="admin-delete-btn" type="button" @click="deleteUser(user)">删除用户</button>
                </div>
              </div>
            </div>
          </div>
        </div>
        <div class="modal-footer">
          <button class="toolbar-btn" type="button" @click="refreshAdmin">刷新列表</button>
          <button class="primary-btn" type="button" @click="state.adminOpen = false">完成</button>
        </div>
      </div>
    </div>
  `,
}

export const PermissionModal = {
  setup() {
    const labels = { approved: '已通过', pending: '待审批', rejected: '已拒绝', none: '未申请' }
    return { state, labels, requestPermission }
  },
  template: `
    <div v-if="state.permissionOpen" class="modal-overlay" style="display:flex" @click.self="state.permissionOpen = false">
      <div class="modal permission-modal" role="dialog" aria-modal="true">
        <div class="modal-header">
          <div><span class="modal-eyebrow">ACCESS CONTROL</span><span>我的知识库权限</span></div>
          <button class="modal-close" type="button" aria-label="关闭" @click="state.permissionOpen = false">×</button>
        </div>
        <div class="modal-body">
          <p class="admin-copy">按需申请知识库。管理员审批通过后，你才能阅读该库文档，AI 也只会在你已获授权的库内检索。</p>
          <div v-if="state.permissionState" class="admin-users-state">{{ state.permissionState }}</div>
          <div class="permission-list">
            <div v-if="!state.permissions.length" class="admin-empty">暂无可申请的知识库。</div>
            <div v-for="item in state.permissions" :key="item.permission_key || item.key" class="permission-row">
              <div><strong>{{ item.name }}</strong><span>{{ item.description || '' }}</span></div>
              <div>
                <span v-if="(item.status || 'none') === 'approved'" class="permission-status approved">已授权</span>
                <span v-else-if="item.status === 'pending'" class="permission-status pending">等待审批</span>
                <button v-else class="permission-request-btn" type="button" @click="requestPermission(item.permission_key || item.key)">申请权限</button>
                <small class="permission-label">{{ labels[item.status || 'none'] }}</small>
              </div>
            </div>
          </div>
        </div>
        <div class="modal-footer"><button class="primary-btn" type="button" @click="state.permissionOpen = false">完成</button></div>
      </div>
    </div>
  `,
}

export const ProfileModal = {
  setup() {
    const name = ref('')
    const avatar = ref('')
    const draft = ref('')
    const error = ref('')
    const busy = ref(false)
    watch(() => state.profileOpen, (opened) => {
      if (!opened) return
      error.value = ''
      draft.value = ''
      name.value = state.profile?.display_name || state.profile?.username || ''
      avatar.value = state.profile?.avatar || ''
    })
    async function pick(event) {
      const file = event.target.files && event.target.files[0]
      event.target.value = ''
      if (!file) return
      try {
        draft.value = await compressAvatar(file)
      } catch (err) {
        notify(err.message, 'error')
      }
    }
    async function submit() {
      error.value = ''
      const prevName = state.profile?.display_name || ''
      const body = {}
      if (name.value.trim() !== prevName) body.display_name = name.value.trim()
      if (draft.value) body.avatar = draft.value
      if (!body.display_name && !body.avatar) { state.profileOpen = false; return }
      if (body.display_name && !/^[\u4e00-\u9fffA-Za-z]{1,20}$/.test(body.display_name)) {
        error.value = '名称只能包含中文和英文字符（1–20 个）'
        return
      }
      busy.value = true
      try {
        await saveProfile(body)
        notify('资料已更新', 'success')
        state.profileOpen = false
      } catch (err) {
        error.value = err.message || '保存失败，请稍后再试'
      } finally {
        busy.value = false
      }
    }
    const shown = computed(() => draft.value || avatar.value)
    return { state, name, error, busy, shown, pick, submit }
  },
  template: `
    <div v-if="state.profileOpen" class="modal-overlay" style="display:flex" @click.self="state.profileOpen = false">
      <div class="modal" role="dialog" aria-modal="true">
        <div class="modal-header">
          <div><span class="modal-eyebrow">PROFILE</span><span>编辑资料</span></div>
          <button class="modal-close" type="button" aria-label="关闭" @click="state.profileOpen = false">×</button>
        </div>
        <div class="modal-body">
          <div class="profile-avatar-row">
            <button class="profile-avatar-btn" type="button" title="更换头像" @click="$refs.file.click()">
              <img v-if="shown" :src="shown" alt="">
              <span v-else>{{ (name || 'K').slice(0, 1).toUpperCase() }}</span>
              <span class="profile-avatar-hint">更换头像</span>
            </button>
            <div class="profile-avatar-meta">头像支持 JPG / PNG / WebP，会自动压缩。<br>名称与头像共用修改次数：每月 2 次。</div>
          </div>
          <input ref="file" type="file" accept="image/png,image/jpeg,image/webp" hidden @change="pick">
          <label class="field"><span>显示名称</span><input v-model="name" type="text" maxlength="20" placeholder="仅中文和英文" autocomplete="nickname"></label>
          <div v-if="error" class="auth-error" role="alert">{{ error }}</div>
          <div v-if="state.profile" class="profile-quota">本月剩余修改次数：<b>{{ state.profile.edits_left }} / {{ state.profile.edits_limit }}</b></div>
        </div>
        <div class="modal-footer">
          <button class="toolbar-btn" type="button" @click="state.profileOpen = false">取消</button>
          <button class="primary-btn" type="button" :disabled="busy" @click="submit">保存修改</button>
        </div>
      </div>
    </div>
  `,
}

export const HelpModal = {
  setup() { return { state } },
  template: `
    <div v-if="state.helpOpen" class="modal-overlay" style="display:flex" @click.self="state.helpOpen = false">
      <div class="modal" role="dialog" aria-modal="true" style="max-width:33rem">
        <div class="modal-header"><div><span class="modal-eyebrow">HELP</span><span>使用说明</span></div></div>
        <div class="modal-body">
          <p class="admin-copy" style="margin-bottom:0">左侧可以在文档和历史对话之间切换。上传支持 Markdown、TXT、Word（.docx）和 PDF；在线新建和编辑仍是 Markdown。点开历史里的一条，就能看到当时的回答和出处。中间输入框按回车发送，Shift + 回车换行。回答下方的出处可以跳到原文。如果某类资料看不到，点右上角「我的权限」申请，管理员审批后即可使用。</p>
        </div>
        <div class="modal-footer"><button class="primary-btn" type="button" @click="state.helpOpen = false">知道了</button></div>
      </div>
    </div>
  `,
}

