import { nextTick, watch } from 'vue'
import { state, ask, openDoc, recordSourceClick, sendFeedback, updateFeedback, loadFeedbackForAnswer, notify } from '../store.js'
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

    function openSource(message, source) {
      recordSourceClick(message, source)
      openDoc(source.source, source.anchor || '')
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

    const reasonOptions = [
      ['retrieval_miss', '没找到相关资料'],
      ['wrong_info', '内容不对'],
      ['incomplete', '不完整'],
      ['outdated', '过时'],
      ['citation_wrong', '引用不对'],
      ['permission', '权限问题'],
      ['formatting', '格式问题'],
      ['unjustified_refusal', '本应回答却拒答'],
      ['other', '其他'],
    ]
    const sourceMarkOptions = [
      ['wrong_citation', '引用有误'],
      ['irrelevant', '不相关'],
      ['outdated', '过时'],
      ['missing_context', '缺少上下文'],
    ]
    const reasonLabel = (key) => (reasonOptions.find(item => item[0] === key) || [key, key])[1]

    function ensureFeedback(message) {
      if (!message.feedback) {
        message.feedback = { sentiment: '', reasons: [], comment: '', source_marks: [] }
      }
      if (!Array.isArray(message.feedback.reasons)) message.feedback.reasons = []
      if (!Array.isArray(message.feedback.source_marks)) message.feedback.source_marks = []
      if (typeof message.feedback.comment !== 'string') message.feedback.comment = ''
      return message.feedback
    }

    function hasReason(message, key) {
      return ensureFeedback(message).reasons.includes(key)
    }

    function toggleReason(message, key) {
      const feedback = ensureFeedback(message)
      feedback.reasons = feedback.reasons.includes(key)
        ? feedback.reasons.filter(item => item !== key)
        : [...feedback.reasons, key]
    }

    function hasSourceMark(message, index, mark) {
      return ensureFeedback(message).source_marks.some(
        item => item.source_index === index && item.mark === mark
      )
    }

    function toggleSourceMark(message, index, mark) {
      const feedback = ensureFeedback(message)
      const exists = feedback.source_marks.some(
        item => item.source_index === index && item.mark === mark
      )
      feedback.source_marks = exists
        ? feedback.source_marks.filter(
            item => !(item.source_index === index && item.mark === mark)
          )
        : [...feedback.source_marks, { source_index: index, mark }]
    }

    async function chooseSentiment(message, sentiment) {
      const feedback = ensureFeedback(message)
      feedback.sentiment = sentiment
      message._hint = ''
      if (sentiment === 'positive') {
        await submitFeedback(message)
        return
      }
      message._editing = true
    }

    async function submitFeedback(message) {
      const feedback = ensureFeedback(message)
      if (!feedback.sentiment) {
        message._hint = '请先选择有帮助或没帮助'
        return
      }
      if (feedback.sentiment === 'negative' && !feedback.reasons.length) {
        message._hint = '点踩时至少选择一个原因'
        return
      }
      if (
        feedback.reasons.includes('other') &&
        (feedback.comment || '').trim().length < 10
      ) {
        message._hint = '选择“其他”时请补充至少 10 个字符'
        return
      }
      const payload = {
        sentiment: feedback.sentiment,
        reasons: feedback.reasons,
        comment: (feedback.comment || '').trim(),
        source_marks: feedback.source_marks,
      }
      try {
        if (feedback.id) await updateFeedback(message, payload)
        else await sendFeedback(message, payload)
        message._editing = false
        message._hint = ''
        message._feedbackBackup = null
      } catch (error) {
        if (error.message.includes('已经评价过')) {
          try {
            const existing = await loadFeedbackForAnswer(message.answerId)
            if (existing) message.feedback = existing
            message._hint = '已加载之前的反馈，可以直接修改'
          } catch {
            message._hint = error.message
          }
          return
        }
        message._hint = error.message
        notify(error.message, 'error')
      }
    }

    async function editFeedback(message) {
      message._feedbackBackup = JSON.parse(JSON.stringify(message.feedback || {}))
      message._editing = true
      message._hint = ''
      try {
        const existing = await loadFeedbackForAnswer(message.answerId)
        if (existing) message.feedback = existing
      } catch {
        // 保留当前内存里的反馈，用户仍可重新提交
      }
    }

    function cancelFeedback(message) {
      if (message.feedback?.id && message._feedbackBackup) {
        message.feedback = message._feedbackBackup
      } else {
        message.feedback = null
      }
      message._feedbackBackup = null
      message._editing = false
      message._hint = ''
    }

    const quotaLabel = () => {
      const quota = state.quota
      if (!quota) return ''
      if (quota.unlimited) return '无限制'
      return `剩余 ${Number(quota.remaining) || 0} 次`
    }

    return {
      state, ask, openDoc, openSource, sourceLabel, resize, onKey, useSuggestion,
      reasonOptions, sourceMarkOptions, reasonLabel, hasReason, toggleReason,
      hasSourceMark, toggleSourceMark, chooseSentiment, submitFeedback,
      editFeedback, cancelFeedback, quotaLabel,
    }
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
                <button v-for="source in message.sources" :key="sourceLabel(source)" type="button" class="source-chip" @click="openSource(message, source)">{{ sourceLabel(source) }}</button>
              </div>
              <div v-if="message.answerId" class="feedback">
                <template v-if="message.feedback && message.feedback.id && !message._editing">
                  <span class="feedback-done">
                    {{ message.feedback.sentiment === 'positive' ? '已点赞' : '已点踩' }}
                    <template v-if="message.feedback.reasons && message.feedback.reasons.length"> · {{ message.feedback.reasons.map(reasonLabel).join('、') }}</template>
                  </span>
                  <button type="button" class="feedback-edit-link" @click="editFeedback(message)">修改</button>
                </template>
                <template v-else>
                  <span>这次回答有帮助吗？</span>
                  <button type="button" class="feedback-choice" :class="{ selected: message.feedback && message.feedback.sentiment === 'positive' }" aria-label="有帮助" @click="chooseSentiment(message, 'positive')">👍</button>
                  <button type="button" class="feedback-choice" :class="{ selected: message.feedback && message.feedback.sentiment === 'negative' }" aria-label="没帮助" @click="chooseSentiment(message, 'negative')">👎</button>
                  <div v-if="message._editing" class="feedback-form">
                    <div class="feedback-reason-chips" role="group" aria-label="反馈原因">
                      <button v-for="option in reasonOptions" :key="option[0]" type="button" class="reason-chip" :class="{ active: hasReason(message, option[0]) }" @click="toggleReason(message, option[0])">{{ option[1] }}</button>
                    </div>
                    <textarea v-model="message.feedback.comment" placeholder="补充说明（选择“其他”时至少 10 个字符）"></textarea>
                    <div v-if="message.sources && message.sources.length" class="feedback-source-marks">
                      <div v-for="(source, index) in message.sources" :key="sourceLabel(source)" class="feedback-source-row">
                        <span class="feedback-source-label">{{ sourceLabel(source) }}</span>
                        <button v-for="option in sourceMarkOptions" :key="option[0]" type="button" class="reason-chip" :class="{ active: hasSourceMark(message, source.index || index + 1, option[0]) }" @click="toggleSourceMark(message, source.index || index + 1, option[0])">{{ option[1] }}</button>
                      </div>
                    </div>
                    <small>{{ message._hint || '' }}</small>
                    <div class="feedback-actions">
                      <button type="button" @click="submitFeedback(message)">提交反馈</button>
                      <button type="button" class="feedback-cancel" @click="cancelFeedback(message)">取消</button>
                    </div>
                  </div>
                </template>
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
