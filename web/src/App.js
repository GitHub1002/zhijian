import { onMounted, onBeforeUnmount, ref } from 'vue'
import DocTree from './components/DocTree.js'
import ChatPane from './components/ChatPane.js'
import { ToastStack, ConfirmDialog, DocModal, AdminModal, PermissionModal, ProfileModal, HelpModal } from './components/Dialogs.js'
import AdminFeedbackModal from './components/AdminFeedbackModal.js'
import { state, boot, submitAuth, logout, notify, askDialog, docCount, openDoc, deleteDoc, uploadFiles, uploadLibraries, loadDocs, syncDir, ingest, openConversation, deleteConversation, startNewConversation, openPermissions, openAdmin, openAdminFeedback, displayName, initials } from './store.js'
import { formatConversationTime } from './editor.js'

export default {
  components: { DocTree, ChatPane, ToastStack, ConfirmDialog, DocModal, AdminModal, AdminFeedbackModal, PermissionModal, ProfileModal, HelpModal },
  setup() {
    const username = ref('')
    const password = ref('')
    const fileInput = ref(null)
    let dragging = false

    onMounted(() => {
      const dark = document.documentElement.getAttribute('data-theme') === 'dark'
      state.themeDark = dark
      boot()
      window.addEventListener('mousemove', onMove)
      window.addEventListener('mouseup', stopDrag)
      window.addEventListener('keydown', onKey)
      window.addEventListener('click', () => { state.userMenu = false })
    })
    onBeforeUnmount(() => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', stopDrag)
      window.removeEventListener('keydown', onKey)
    })

    function toggleTheme() {
      const dark = document.documentElement.getAttribute('data-theme') === 'dark'
      if (dark) document.documentElement.removeAttribute('data-theme')
      else document.documentElement.setAttribute('data-theme', 'dark')
      try { localStorage.setItem('kb-theme', dark ? 'light' : 'dark') } catch { /* 忽略 */ }
      const meta = document.querySelector('meta[name="theme-color"]')
      if (meta) meta.setAttribute('content', dark ? '#FFFFFF' : '#0E0E0E')
    }

    function onKey(event) {
      if (event.key === 'Escape') {
        state.userMenu = false
        state.drawerOpen = false
      }
      if (event.key === '/' && !event.target.closest('input, textarea, select')) {
        event.preventDefault()
        state.sidebarTab = 'docs'
        document.getElementById('doc-search')?.focus()
      }
    }

    function startDrag(event) {
      dragging = true
      event.currentTarget.classList.add('dragging')
      document.body.style.cursor = 'col-resize'
      document.body.style.userSelect = 'none'
    }
    function onMove(event) {
      if (!dragging) return
      const panel = document.getElementById('chat-panel')
      if (!panel) return
      const rect = panel.parentElement.getBoundingClientRect()
      const width = Math.max(320, Math.min(rect.width * 0.8, event.clientX - rect.left))
      panel.style.flex = `0 0 ${width}px`
    }
    function stopDrag() {
      if (!dragging) return
      dragging = false
      document.querySelector('.divider')?.classList.remove('dragging')
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }

    async function onUpload(event) {
      const files = [...(event.target.files || [])]
      event.target.value = ''
      if (!files.length) return
      await loadDocs()
      const options = uploadLibraries()
      if (!options.length) {
        notify('还没有可上传的知识库。请先申请权限，管理员通过后再上传。', 'warn')
        return
      }
      const preferred = options.find(item => item.value !== 'common') || options[0]
      const dir = await askDialog({
        mode: 'select',
        eyebrow: 'UPLOAD',
        title: '上传到哪个知识库',
        message: `已选择 ${files.length} 个文件。支持 Markdown、TXT、Word（.docx）和 PDF。文件会归入所选知识库，并立刻写入检索。`,
        inputLabel: '知识库',
        options,
        value: preferred.value,
        okLabel: '开始上传',
      })
      if (!dir) return
      await uploadFiles(files, dir)
    }

    async function onSync() {
      const src = await askDialog({
        mode: 'prompt',
        eyebrow: 'SYNC DIRECTORY',
        title: '同步本地目录',
        message: '填写本机目录的绝对路径。该目录下的 Markdown、TXT、Word（.docx）和 PDF 会被复制进知识库，原目录不受影响。',
        inputLabel: '目录路径',
        placeholder: '如：D:\\公司文档\\制度',
        okLabel: '下一步',
      })
      if (!src) { notify(src === null ? '没有填写目录路径，已取消同步' : '没有填写目录路径，已取消同步', 'warn'); return }
      const ok = await askDialog({
        eyebrow: 'CONFIRM SYNC',
        title: '确认同步',
        message: `将把「${src}」下的 Markdown、TXT、Word（.docx）和 PDF 写入本地知识库。同名文件会被覆盖。`,
        okLabel: '确认同步',
      })
      if (ok === null) return
      await syncDir(src)
    }

    async function confirmLogout() {
      state.userMenu = false
      const ok = await askDialog({
        eyebrow: 'SIGN OUT',
        title: '退出当前账号',
        message: `将以「${displayName() || state.user.username}」的身份退出。你的文档和问答记录都保存在本地，下次登录还在。`,
        okLabel: '退出登录',
      })
      if (ok !== null) logout()
    }

    const isAdmin = () => state.user?.role === 'admin'
    const name = () => displayName()
    const fileKind = (path) => {
      const ext = String(path || '').split('.').pop().toUpperCase()
      return ext === 'MARKDOWN' ? 'MD' : (ext || 'FILE').slice(0, 4)
    }

    return {
      state, username, password, fileInput, submitAuth, docCount, openDoc, deleteDoc, ingest,
      openConversation, deleteConversation, startNewConversation, openPermissions, openAdmin, openAdminFeedback, initials, name, isAdmin,
      formatConversationTime, toggleTheme, startDrag, onUpload, onSync, confirmLogout, logout, fileKind,
    }
  },
  template: `
    <a class="skip-link" href="#workspace">跳到主内容</a>
    <div v-if="state.drawerOpen" class="scrim" @click="state.drawerOpen = false"></div>
    <div v-if="!state.user" class="auth-gate" role="dialog" aria-modal="true">
      <div class="auth-card">
        <div class="auth-brand"><span class="auth-mark"><img src="/static/shark-ink.svg" alt=""></span></div>
        <div class="auth-kicker">{{ state.authMode === 'register' ? 'CREATE YOUR SPACE' : 'WELCOME BACK' }}</div>
        <h1>{{ state.authMode === 'register' ? '注册知识库账号' : '登录 智检' }}</h1>
        <p class="auth-copy">让每一次提问，都有据可依。</p>
        <form @submit.prevent="submitAuth(username, password)">
          <label class="auth-field"><span>用户名</span><input v-model="username" autocomplete="username" required minlength="3" maxlength="40" placeholder="3–40 个字符"></label>
          <label class="auth-field"><span>密码</span><input v-model="password" type="password" :autocomplete="state.authMode === 'register' ? 'new-password' : 'current-password'" required minlength="6" maxlength="128" placeholder="至少 6 位"></label>
          <div v-if="state.authError" class="auth-error" role="alert">{{ state.authError }}</div>
          <button class="auth-submit" type="submit" :disabled="state.authBusy">{{ state.authMode === 'register' ? '注册并进入' : '登录并进入' }}</button>
        </form>
        <button class="auth-switch" type="button" @click="state.authMode = state.authMode === 'login' ? 'register' : 'login'; state.authError = ''">
          {{ state.authMode === 'register' ? '已有账号？返回登录' : '还没有账号？注册一个' }}
        </button>
      </div>
    </div>
    <template v-else>
      <aside class="sidebar" id="sidebar">
        <div class="brand">
          <div class="brand-mark" aria-hidden="true"><img src="/static/shark-ink.svg" alt=""></div>
          <div class="brand-info"><div class="brand-title">智检</div></div>
          <button class="sidebar-toggle" type="button" aria-label="关闭侧栏" @click="state.drawerOpen = false">×</button>
        </div>
        <nav class="sidebar-nav" aria-label="主导航">
          <div class="nav-label">工作区</div>
          <button type="button" class="nav-item" :class="{ active: state.sidebarTab === 'docs' }" @click="state.sidebarTab = 'docs'">文档</button>
          <button type="button" class="nav-item" :class="{ active: state.sidebarTab === 'history' }" @click="state.sidebarTab = 'history'">历史</button>
        </nav>
        <div v-show="state.sidebarTab === 'docs'" class="sidebar-section">
          <div class="section-heading">
            <div><div class="section-label">文档库</div><div class="section-meta">{{ docCount() }} 篇文档</div></div>
            <button class="new-document-btn" type="button" @click="state.docOpen = 'create'"><span>新建</span></button>
          </div>
          <div class="doc-tools">
            <label class="search-box">
              <input id="doc-search" v-model="state.docQuery" type="search" placeholder="按标题筛选文档" autocomplete="off">
            </label>
            <div class="sidebar-actions">
              <button type="button" @click="fileInput.click()">上传</button>
              <button v-if="isAdmin()" type="button" @click="onSync">同步</button>
              <button v-if="isAdmin()" type="button" :disabled="state.ingestBusy" @click="ingest">{{ state.ingestBusy ? '索引中' : '索引' }}</button>
            </div>
          </div>
          <div class="doc-list">
            <doc-tree :node="state.tree" :query="state.docQuery" :active-path="state.currentPath" @open="openDoc"></doc-tree>
          </div>
        </div>
        <div v-show="state.sidebarTab === 'history'" class="sidebar-section">
          <div class="section-heading">
            <div><div class="section-label">历史对话</div><div class="section-meta">{{ state.conversations.length }} 组</div></div>
            <button class="new-document-btn" type="button" @click="startNewConversation"><span>新对话</span></button>
          </div>
          <div class="doc-list">
            <div v-if="!state.conversations.length" class="history-empty">提问之后，可以在这里打开原来的回答和出处。</div>
            <div v-for="item in state.conversations" :key="item.id" class="history-side" :class="{ active: item.id === state.conversationId }">
              <button type="button" class="history-side-open" @click="openConversation(item.id)">
                <span class="history-side-title">{{ item.title }}</span>
                <span class="history-side-meta">{{ formatConversationTime(item.updated_at) }} · {{ item.turns || 0 }} 轮</span>
              </button>
              <button type="button" class="history-side-delete" aria-label="删除这组对话" @click="deleteConversation(item)">删除</button>
            </div>
          </div>
        </div>
        <div class="sidebar-footer"><div class="status-dot" aria-hidden="true"></div><div><strong>本地知识库</strong><span>已连接 · 索引服务正常</span></div><span class="footer-signal">LOCAL</span></div>
      </aside>
      <main id="workspace" class="main" :class="{ 'view-doc': state.viewDoc }">
        <header class="topbar">
          <button class="drawer-toggle" type="button" aria-label="打开侧边栏" @click="state.drawerOpen = !state.drawerOpen">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 9.5h14M5 14.5h14"/></svg>
          </button>
          <div class="topbar-context"><div class="breadcrumb"><strong>智检</strong></div></div>
          <div class="topbar-actions">
            <span class="secure-badge">本地运行</span>
            <button class="theme-toggle" type="button" aria-label="切换深色或浅色模式" @click="toggleTheme">
              <svg class="theme-icon-moon" viewBox="0 0 24 24" aria-hidden="true"><path d="M20.5 14.5A8.5 8.5 0 0 1 9.5 3.5a8.5 8.5 0 1 0 11 11Z"/></svg>
              <svg class="theme-icon-sun" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4.2"/><path d="M12 2.8v2.4M12 18.8v2.4M2.8 12h2.4M18.8 12h2.4"/></svg>
            </button>
            <button class="topbar-help" type="button" @click="state.helpOpen = true"><span>使用说明</span></button>
            <button class="topbar-help" type="button" @click="openPermissions"><span>我的权限</span></button>
            <button v-if="isAdmin()" class="topbar-help" type="button" @click="openAdmin"><span>管理用户</span></button>
            <button v-if="isAdmin()" class="topbar-help" type="button" @click="openAdminFeedback"><span>质量看板</span></button>
            <div class="user-menu-wrap">
              <button class="workspace-user user-menu" type="button" @click.stop="state.userMenu = !state.userMenu">
                <span class="user-avatar"><img v-if="state.profile && state.profile.avatar" :src="state.profile.avatar" alt=""><span v-else>{{ initials(name()) }}</span></span>
                <small>{{ name() || '未登录' }}</small>
              </button>
              <div v-if="state.userMenu" class="user-panel" @click.stop>
                <div class="user-panel-head">
                  <span class="user-avatar user-avatar-lg"><img v-if="state.profile && state.profile.avatar" :src="state.profile.avatar" alt=""><span v-else>{{ initials(name()) }}</span></span>
                  <div><strong>{{ name() }}</strong><small>@{{ state.user.username }}</small></div>
                </div>
                <button type="button" class="user-panel-item" @click="state.userMenu = false; state.profileOpen = true">编辑资料</button>
                <button type="button" class="user-panel-item" @click="logout">切换账号</button>
                <button type="button" class="user-panel-item" @click="confirmLogout">退出登录</button>
              </div>
            </div>
          </div>
        </header>
        <div class="tabbar" role="group" aria-label="面板切换">
          <button type="button" class="tab-label" :class="{ active: !state.viewDoc }" @click="state.viewDoc = false">知识问答</button>
          <button type="button" class="tab-label" :class="{ active: state.viewDoc }" @click="state.viewDoc = true">文档预览</button>
        </div>
        <div class="content">
          <chat-pane @new-chat="startNewConversation"></chat-pane>
          <div class="divider" role="separator" aria-orientation="vertical" aria-label="拖动调整左右区域宽度" tabindex="0" @mousedown.prevent="startDrag"><span aria-hidden="true"></span></div>
          <section class="viewer-panel">
            <div v-if="state.currentPath" class="viewer-toolbar" style="display:flex">
              <div class="viewer-heading">
                <span class="file-badge" aria-hidden="true">{{ fileKind(state.currentPath) }}</span>
                <span class="viewer-heading-copy"><span class="viewer-eyebrow">正在查看</span><span class="viewer-title">{{ state.currentPath }}</span></span>
              </div>
              <div v-if="isAdmin()" class="viewer-actions">
                <button v-if="state.docEditable" class="toolbar-btn" type="button" @click="state.docOpen = 'edit'">编辑</button>
                <button class="toolbar-btn danger" type="button" @click="deleteDoc">删除</button>
              </div>
            </div>
            <div id="viewer" class="viewer">
              <div v-if="state.docHtml" class="markdown" v-html="state.docHtml"></div>
              <div v-else class="viewer-empty">
                <div class="viewer-empty-label">DOCUMENT PREVIEW</div>
                <strong>选择一篇文档开始阅读</strong>
                <span>从左侧打开一份资料。新建仍是 Markdown，上传还可以带上 TXT、Word 和 PDF。</span>
              </div>
            </div>
          </section>
        </div>
      </main>
      <input ref="fileInput" type="file" multiple accept=".md,.markdown,.txt,.docx,.pdf" hidden @change="onUpload">
    </template>
    <doc-modal></doc-modal>
    <admin-modal></admin-modal>
    <admin-feedback-modal></admin-feedback-modal>
    <permission-modal></permission-modal>
    <profile-modal></profile-modal>
    <help-modal></help-modal>
    <confirm-dialog></confirm-dialog>
    <toast-stack></toast-stack>
  `,
}
