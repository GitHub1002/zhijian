import { state, loadAdminFeedback, loadAdminFeedbackDetail, triageFeedback } from '../store.js'

const STATUS_OPTIONS = [
  ['new', '待处理'],
  ['triaged', '已分流'],
  ['in_progress', '处理中'],
  ['resolved', '已解决'],
  ['dismissed', '已忽略'],
]
const CATEGORY_OPTIONS = [
  ['positive', '正向'],
  ['retrieval_failure', '检索失败'],
  ['generation_failure', '生成失败'],
  ['citation_issue', '引用问题'],
  ['doc_issue', '文档问题'],
  ['permission', '权限'],
  ['ux', '表达/交互'],
  ['unknown', '未知'],
]
const SENTIMENT_OPTIONS = [
  ['negative', '点踩'],
  ['positive', '点赞'],
]

export default {
  setup() {
    function applyFilters() {
      loadAdminFeedback(1)
    }

    function formatTime(value) {
      return value ? value.replace('T', ' ').slice(0, 16) : ''
    }

    function triageDetail() {
      const detail = state.adminFeedbackDetail
      if (!detail) return
      triageFeedback(detail.id, {
        status: detail.status,
        category: detail.triage_category || 'unknown',
        note: detail.triage_note || '',
      })
    }

    return {
      state,
      loadAdminFeedback,
      loadAdminFeedbackDetail,
      applyFilters,
      formatTime,
      triageDetail,
      statusOptions: STATUS_OPTIONS,
      categoryOptions: CATEGORY_OPTIONS,
      sentimentOptions: SENTIMENT_OPTIONS,
    }
  },
  template: `
    <div v-if="state.adminFeedbackOpen" class="modal-overlay" style="display:flex" @click.self="state.adminFeedbackOpen = false">
      <div class="modal admin-modal feedback-admin-modal" role="dialog" aria-modal="true">
        <div class="modal-header">
          <div><span class="modal-eyebrow">QUALITY LOOP</span><span>反馈与检索轨迹</span></div>
          <button class="modal-close" type="button" aria-label="关闭" @click="state.adminFeedbackOpen = false">×</button>
        </div>
        <div class="modal-body">
          <p class="admin-copy">点踩会带上原因、来源标记和当次检索轨迹。先看问题是“没检索到”还是“检索到但答错”，再决定修检索、修 prompt 还是补文档。</p>
          <div class="admin-feedback-filters">
            <select v-model="state.adminFeedbackFilters.sentiment" @change="applyFilters">
              <option value="">全部情感</option>
              <option v-for="item in sentimentOptions" :key="item[0]" :value="item[0]">{{ item[1] }}</option>
            </select>
            <select v-model="state.adminFeedbackFilters.category" @change="applyFilters">
              <option value="">全部分流</option>
              <option v-for="item in categoryOptions" :key="item[0]" :value="item[0]">{{ item[1] }}</option>
            </select>
            <select v-model="state.adminFeedbackFilters.status" @change="applyFilters">
              <option value="">全部状态</option>
              <option v-for="item in statusOptions" :key="item[0]" :value="item[0]">{{ item[1] }}</option>
            </select>
            <button class="toolbar-btn" type="button" @click="applyFilters">刷新</button>
          </div>
          <div v-if="state.adminFeedbackState" class="admin-users-state">{{ state.adminFeedbackState }}</div>
          <div class="admin-feedback-layout">
            <div class="admin-feedback-list">
              <div v-if="!state.adminFeedbackItems.length" class="admin-empty">还没有反馈。</div>
              <button v-for="item in state.adminFeedbackItems" :key="item.id" type="button" class="admin-feedback-row" :class="{ active: state.adminFeedbackDetail && state.adminFeedbackDetail.id === item.id }" @click="loadAdminFeedbackDetail(item.id)">
                <span class="admin-feedback-badge" :class="item.sentiment">{{ item.sentiment === 'positive' ? '👍' : '👎' }}</span>
                <span class="admin-feedback-main">
                  <strong>{{ item.question || '（无问题文本）' }}</strong>
                  <small>{{ item.reasons && item.reasons.length ? item.reasons.join('、') : '未分类' }} · {{ item.triage_category || 'unknown' }} · {{ formatTime(item.created_at) }}</small>
                </span>
                <span class="permission-status" :class="item.status">{{ item.status }}</span>
              </button>
              <div class="admin-feedback-pagination">
                <button type="button" :disabled="state.adminFeedbackPage <= 1" @click="loadAdminFeedback(state.adminFeedbackPage - 1)">上一页</button>
                <span>第 {{ state.adminFeedbackPage }} / {{ state.adminFeedbackPages }} 页 · 共 {{ state.adminFeedbackTotal }} 条</span>
                <button type="button" :disabled="state.adminFeedbackPage >= state.adminFeedbackPages" @click="loadAdminFeedback(state.adminFeedbackPage + 1)">下一页</button>
              </div>
            </div>
            <div class="admin-feedback-detail">
              <div v-if="state.adminFeedbackDetailState" class="admin-users-state">{{ state.adminFeedbackDetailState }}</div>
              <template v-else-if="state.adminFeedbackDetail">
                <div class="admin-section-title">问题与回答</div>
                <p class="admin-feedback-question">{{ state.adminFeedbackDetail.question }}</p>
                <pre class="admin-feedback-answer">{{ state.adminFeedbackDetail.answer }}</pre>
                <div class="admin-section-title">反馈</div>
                <p class="admin-feedback-meta">
                  {{ state.adminFeedbackDetail.sentiment === 'positive' ? '点赞' : '点踩' }} ·
                  {{ (state.adminFeedbackDetail.reasons || []).join('、') || '未分类' }} ·
                  {{ state.adminFeedbackDetail.username }}
                </p>
                <p v-if="state.adminFeedbackDetail.comment" class="admin-feedback-comment">{{ state.adminFeedbackDetail.comment }}</p>
                <p v-if="state.adminFeedbackDetail.source_marks && state.adminFeedbackDetail.source_marks.length" class="admin-feedback-meta">
                  来源标记：<span v-for="mark in state.adminFeedbackDetail.source_marks" :key="mark.source_index + mark.mark">{{ mark.mark }}(#{{ mark.source_index }}) </span>
                </p>
                <div class="admin-section-title">检索轨迹</div>
                <p v-if="!state.adminFeedbackDetail.trace" class="admin-empty">这条回答没有轨迹。</p>
                <template v-else>
                  <p class="admin-feedback-meta">
                    grounded={{ state.adminFeedbackDetail.trace.grounded }} ·
                    拒答={{ state.adminFeedbackDetail.trace.refusal_reason || '无' }} ·
                    best_rerank={{ state.adminFeedbackDetail.trace.best_rerank_score }} ·
                    top_k={{ state.adminFeedbackDetail.trace.top_k }}
                  </p>
                  <div class="admin-feedback-candidates">
                    <div v-for="candidate in (state.adminFeedbackDetail.trace.candidates || [])" :key="candidate.rank" class="admin-feedback-candidate">
                      <span>#{{ candidate.rank }}</span>
                      <strong>{{ candidate.source }} {{ candidate.heading ? '> ' + candidate.heading : '' }}</strong>
                      <small>v={{ candidate.vector_score }} b={{ candidate.bm25_score }} rrf={{ candidate.rrf_score }} rerank={{ candidate.rerank_score }}{{ candidate.selected ? ' · 已选中' : '' }}</small>
                    </div>
                  </div>
                </template>
                <div class="admin-section-title">处理</div>
                <div class="admin-feedback-triage">
                  <select v-model="state.adminFeedbackDetail.status">
                    <option v-for="item in statusOptions" :key="item[0]" :value="item[0]">{{ item[1] }}</option>
                  </select>
                  <select v-model="state.adminFeedbackDetail.triage_category">
                    <option value="">未分类</option>
                    <option v-for="item in categoryOptions" :key="item[0]" :value="item[0]">{{ item[1] }}</option>
                  </select>
                  <textarea v-model="state.adminFeedbackDetail.triage_note" placeholder="处理备注"></textarea>
                  <button class="primary-btn" type="button" @click="triageDetail">保存状态</button>
                </div>
              </template>
              <div v-else class="admin-empty">从左侧选择一条反馈查看详情。</div>
            </div>
          </div>
        </div>
        <div class="modal-footer">
          <button class="toolbar-btn" type="button" @click="loadAdminFeedback(state.adminFeedbackPage)">刷新列表</button>
          <button class="primary-btn" type="button" @click="state.adminFeedbackOpen = false">完成</button>
        </div>
      </div>
    </div>
  `,
}
