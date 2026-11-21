import { nextTick, watch } from 'vue'
import { state, ask, openDoc, sendFeedback, notify } from '../store.js'
import { sourceLabel } from '../editor.js'

export default {
  emits: ['new-chat'],
  setup() {
    watch(() => state.messages.map(item => `${item.text}|${item.html}|${item.pending}|${item.error}`).join('\n'), async () => {
      await nextTick()
      const box = document.getElementById('messages')
      if (box) box.scrollTop = box.scrollHeight
    })

    function resize(event) {
      const input = event.target
      input.style.height = 'auto'
      const max = parseFloat(getComputedStyle(input).maxHeight) || 144
      input.style.height = `${Math.min(Math.max(input.scrollHeight, 48), max)}px`
    }

    function onKey(event) {
      if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault()
        ask()
      }
    }

    function useSuggestion(text) {
      state.question = text
      nextTick(() => document.getElementById('question')?.focus())
    }

    async function rate(message, rating) {
      if (rating === 5) {
        try {
          await sendFeedback(message, 5, '')
        } catch (error) {
          notify(error.message, 'error')
        }
        return
      }
      message._rating = rating
      message._showReason = true
    }

    async function submitReason(message) {
      const reason = (message._reason || '').trim()
      if (reason.length < 10) {
        message._hint = '原因至少需要 10 个字符'
        return
      }
      try {
        await sendFeedback(message, message._rating, reason)
        message._showReason = false
      } catch (error) {
        message._hint = error.message
      }
    }

    const quotaLabel = () => {
      const quota = state.quota
      if (!quota) return ''
      if (quota.unlimited) return '无限制'
      return `剩余 ${Number(quota.remaining) || 0} 次`
    }

    return { state, ask, openDoc, sourceLabel, resize, onKey, useSuggestion, rate, submitReason, quotaLabel }
  },
  template: `
    <section class="chat-panel" id="chat-panel">
      <div class="panel-heading chat-heading">
        <div class="panel-heading-copy">
          <div class="panel-kicker"><span class="kicker-mark" aria-hidden="true"></span> AI / 知识助手</div>
          <h1 class="panel-title">{{ state.conversationTitle || '把问题交给你的文档' }}</h1>
          <div class="panel-subtitle">检索、归纳、引用，一次完成。</div>
        </div>
        <div class="chat-heading-actions">
          <button class="chat-tool" type="button" :disabled="state.asking" @click="$emit('new-chat')">新对话</button>
          <span class="ready-pill"><i aria-hidden="true"></i> 就绪</span>
        </div>
      </div>
      <div id="messages" class="messages" role="log" aria-live="polite">
        <div v-if="!state.messages.length" class="empty-hint">
          <div class="hint-eyebrow"><i aria-hidden="true"></i> 私有知识工作区</div>
          <h2 class="hint-title">从你的知识库开始提问</h2>
          <p>我会从你已获授权的文档里找出依据，提炼重点，并附上可以点开的出处。找不到依据时会直接说明，不会编造。</p>
          <div class="suggestions" aria-label="推荐问题">
            <button type="button" @click="useSuggestion('公司的请假流程是什么？')"><span class="suggestion-number">01</span><span>公司的请假流程是什么？</span></button>
            <button type="button" @click="useSuggestion('报销需要哪些发票材料？')"><span class="suggestion-number">02</span><span>报销需要哪些发票材料？</span></button>
          </div>
        </div>
        <div v-for="message in state.messages" :key="message.key" class="msg" :class="message.role">
          <div class="msg-bubble">
            <template v-if="message.role === 'user'">{{ message.text }}</template>
            <template v-else>
              <div v-if="message.pending && !message.text" class="loading"></div>
              <div v-else-if="message.error" class="markdown">出错了：{{ message.error }}</div>
              <div v-else-if="message.html" class="markdown" v-html="message.html"></div>
              <div v-else class="markdown">{{ message.text }}</div>
              <div v-if="message.sources && message.sources.length" class="sources">参考来源：
                <button v-for="source in message.sources" :key="sourceLabel(source)" type="button" class="source-chip" @click="openDoc(source.source, source.anchor || '')">{{ sourceLabel(source) }}</button>
              </div>
              <div v-if="message.answerId && message.rating" class="feedback done">已评价 {{ message.rating }} 星</div>
              <div v-else-if="message.answerId" class="feedback">
                <span>这次回答有帮助吗？</span>
                <button v-for="star in 5" :key="star" type="button" :class="{ selected: star <= (message._rating || 0) }" :aria-label="star + ' 星'" @click="rate(message, star)">★</button>
                <div v-if="message._showReason" class="feedback-reason">
                  <textarea v-model="message._reason" placeholder="请说明哪里不满意（至少 10 个字符）"></textarea>
                  <small>{{ message._hint || '' }}</small>
                  <button type="button" @click="submitReason(message)">提交反馈</button>
                </div>
              </div>
            </template>
          </div>
        </div>
      </div>
      <div class="input-wrap">
        <label class="sr-only" for="question">向知识库提问</label>
        <div class="input-row">
          <textarea id="question" v-model="state.question" rows="1" placeholder="询问知识库中的任何内容…" @input="resize" @keydown="onKey"></textarea>
          <button id="ask-btn" type="button" aria-label="发送问题" :disabled="state.asking" @click="ask"><span>发送</span></button>
        </div>
        <div class="input-meta">
          <span>回答仅基于当前文档库</span>
          <span v-if="state.quota" class="quota-reminder" :class="{ 'is-depleted': !state.quota.unlimited && (state.quota.remaining || 0) <= 0 }">
            <span class="quota-reminder-label">{{ state.quota.unlimited ? 'AI 咨询额度' : '今日 AI 咨询' }}</span>
            <strong>{{ quotaLabel() }}</strong>
          </span>
          <span><kbd>回车</kbd> 发送 · <kbd>Shift</kbd> + <kbd>回车</kbd> 换行</span>
        </div>
      </div>
    </section>
  `,
}
