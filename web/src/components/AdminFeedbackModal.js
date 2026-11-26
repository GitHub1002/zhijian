import { reactive } from 'vue'
import {
  state,
  notify,
  loadAdminFeedback,
  loadAdminFeedbackDetail,
  loadAdminAnalytics,
  loadAdminContentTasks,
  loadAdminCuratedExamples,
  loadAdminExperiments,
  loadExperimentResults,
  loadAdminEvalRuns,
  loadAdminEvalRun,
  loadAdminAudit,
  createExperiment,
  updateExperiment,
  updateCuratedExample,
  createTaskFromFeedback,
  updateContentTask,
  exportAdminFeedback,
  triageFeedback,
} from '../store.js'

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
const REASON_LABELS = {
  retrieval_miss: '没找到资料',
  wrong_info: '内容错误',
  incomplete: '不完整',
  outdated: '资料过时',
  citation_wrong: '引用不对',
  permission: '权限问题',
  formatting: '格式问题',
  unjustified_refusal: '不该拒答',
  other: '其他',
}
const CATEGORY_LABELS = Object.fromEntries(CATEGORY_OPTIONS)
const TASK_KIND_LABELS = {
  doc_fix: '文档修正',
  doc_update: '文档更新',
  doc_missing: '文档缺失',
  citation_fix: '引用修正',
  retrieval_gap: '检索缺口',
  other: '其他',
}
const TASK_PRIORITY_LABELS = { low: '低', medium: '中', high: '高' }
const TASK_STATUS_OPTIONS = [
  ['open', '待处理'],
  ['in_progress', '处理中'],
  ['resolved', '已解决'],
  ['dismissed', '已忽略'],
]
const TASK_PRIORITY_OPTIONS = [
  ['high', '高'],
  ['medium', '中'],
  ['low', '低'],
]
const CURATED_STATUS_OPTIONS = [
  ['candidate', '候选'],
  ['approved', '已通过'],
  ['rejected', '已否决'],
]
const EXPERIMENT_STATUS_OPTIONS = [
  ['draft', '草稿'],
  ['running', '运行中'],
  ['paused', '已暂停'],
  ['ended', '已结束'],
]

export default {
  setup() {
    const experimentForm = reactive({
      open: false,
      key: '',
      name: '',
      controlKey: 'control',
      treatmentKey: 'treatment',
      traffic: 50,
      config: '{"MIN_RERANK_SCORE": 0.5}',
    })

    function applyFilters() {
      loadAdminFeedback(1)
    }

    function formatTime(value) {
      return value ? value.replace('T', ' ').slice(0, 16) : ''
    }

    function percent(value) {
      return `${Math.round((Number(value) || 0) * 100)}%`
    }

    function reasonLabel(value) {
      return REASON_LABELS[value] || value
    }

    function categoryLabel(value) {
      return CATEGORY_LABELS[value] || value
    }

    function refreshAll() {
      loadAdminFeedback(1)
      loadAdminAnalytics()
      if (state.adminQualityTab === 'tasks') loadAdminContentTasks(1)
      if (state.adminQualityTab === 'curated') loadAdminCuratedExamples(1)
      if (state.adminQualityTab === 'experiments') loadAdminExperiments()
      if (state.adminQualityTab === 'eval') loadAdminEvalRuns(1)
      if (state.adminQualityTab === 'audit') loadAdminAudit(1)
    }

    function switchTab(tab) {
      state.adminQualityTab = tab
      if (tab === 'overview') loadAdminAnalytics()
      if (tab === 'tasks') {
        loadAdminContentTasks(1)
        loadAdminEvalRuns(1)
      }
      if (tab === 'curated') {
        loadAdminCuratedExamples(1)
        loadAdminEvalRuns(1)
      }
      if (tab === 'experiments') loadAdminExperiments()
    }

    function loadCurated(page) {
      loadAdminCuratedExamples(page)
    }

    function saveCurated(example) {
      updateCuratedExample(example.id, {
        status: example.status,
        use_as_few_shot: example.use_as_few_shot,
        eval_passed: example.eval_passed,
        eval_run_id: Number(example.eval_run_id) || 0,
      })
    }

    function loadEvals(page) {
      loadAdminEvalRuns(page)
    }

    function showEvalRun(runId) {
      loadAdminEvalRun(runId)
    }

    function datasetName(path) {
      return String(path || '').split(/[\\/]/).pop() || path || ''
    }

    function loadAudits(page) {
      loadAdminAudit(page)
    }

    function formatDetail(detail) {
      try {
        return JSON.stringify(detail || {})
      } catch (error) {
        return ''
      }
    }

    function toggleExperimentForm() {
      experimentForm.open = !experimentForm.open
    }

    async function createExperimentFromForm() {
      let config = {}
      try {
        config = JSON.parse(experimentForm.config || '{}')
      } catch (error) {
        notify('实验配置不是合法 JSON', 'error')
        return
      }
      const key = experimentForm.key.trim()
      if (!key) {
        notify('请填写实验 key', 'warn')
        return
      }
      const traffic = Math.max(1, Math.min(99, Number(experimentForm.traffic) || 50))
      const created = await createExperiment({
        key,
        name: experimentForm.name.trim() || key,
        variants: [
          {
            variant_key: experimentForm.controlKey.trim() || 'control',
            name: '对照',
            config: {},
            traffic_pct: 100 - traffic,
            is_control: true,
          },
          {
            variant_key: experimentForm.treatmentKey.trim() || 'treatment',
            name: '实验',
            config,
            traffic_pct: traffic,
            is_control: false,
          },
        ],
      })
      if (created) {
        experimentForm.open = false
        experimentForm.key = ''
        experimentForm.name = ''
      }
    }

    function saveExperiment(experiment) {
      updateExperiment(experiment.key, { status: experiment.status })
    }

    function showExperimentResults(key) {
      loadExperimentResults(key)
    }

    function loadExperiments() {
      loadAdminExperiments()
    }

    function rate(value) {
      return value === null || value === undefined ? '—' : percent(value)
    }

    function variantSummary(experiment) {
      return (experiment.variants || [])
        .map(item => `${item.variant_key}:${item.traffic_pct}%`)
        .join(' / ')
    }

    function loadTasks(page) {
      loadAdminContentTasks(page)
    }

    function saveTask(task) {
      updateContentTask(task.id, {
        status: task.status,
        priority: task.priority,
        eval_run_id: Number(task.eval_run_id) || 0,
      })
    }

    function makeTask() {
      const detail = state.adminFeedbackDetail
      if (detail) createTaskFromFeedback(detail.id)
    }

    function taskKindLabel(value) {
      return TASK_KIND_LABELS[value] || value
    }

    function taskPriorityLabel(value) {
      return TASK_PRIORITY_LABELS[value] || value
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
      exportAdminFeedback,
      formatTime,
      percent,
      reasonLabel,
      categoryLabel,
      refreshAll,
      switchTab,
      loadTasks,
      saveTask,
      loadCurated,
      saveCurated,
      loadEvals,
      showEvalRun,
      datasetName,
      loadAudits,
      formatDetail,
      experimentForm,
      toggleExperimentForm,
      createExperimentFromForm,
      saveExperiment,
      showExperimentResults,
      loadExperiments,
      rate,
      variantSummary,
      makeTask,
      taskKindLabel,
      taskPriorityLabel,
      triageDetail,
      statusOptions: STATUS_OPTIONS,
      categoryOptions: CATEGORY_OPTIONS,
      sentimentOptions: SENTIMENT_OPTIONS,
      taskStatusOptions: TASK_STATUS_OPTIONS,
      taskPriorityOptions: TASK_PRIORITY_OPTIONS,
      curatedStatusOptions: CURATED_STATUS_OPTIONS,
      experimentStatusOptions: EXPERIMENT_STATUS_OPTIONS,
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
          <div class="admin-quality-tabs">
            <button type="button" :class="{ active: state.adminQualityTab === 'overview' }" @click="switchTab('overview')">概览</button>
            <button type="button" :class="{ active: state.adminQualityTab === 'feedback' }" @click="switchTab('feedback')">反馈队列</button>
            <button type="button" :class="{ active: state.adminQualityTab === 'tasks' }" @click="switchTab('tasks')">内容任务<span v-if="state.adminContentTaskTotal"> · {{ state.adminContentTaskTotal }}</span></button>
            <button type="button" :class="{ active: state.adminQualityTab === 'curated' }" @click="switchTab('curated')">精选正例<span v-if="state.adminCuratedTotal"> · {{ state.adminCuratedTotal }}</span></button>
            <button type="button" :class="{ active: state.adminQualityTab === 'experiments' }" @click="switchTab('experiments')">实验<span v-if="state.adminExperiments.length"> · {{ state.adminExperiments.length }}</span></button>
            <button type="button" :class="{ active: state.adminQualityTab === 'eval' }" @click="switchTab('eval')">评测<span v-if="state.adminEvalTotal"> · {{ state.adminEvalTotal }}</span></button>
            <button type="button" :class="{ active: state.adminQualityTab === 'audit' }" @click="switchTab('audit')">审计<span v-if="state.adminAuditTotal"> · {{ state.adminAuditTotal }}</span></button>
          </div>
          <div v-if="state.adminQualityTab === 'overview'">
          <p class="admin-copy">近 30 天的回答、拒答、反馈和引用点击概览。数据按 UTC 时间窗口聚合。</p>
          <div class="admin-analytics-shell">
          <div v-if="state.adminAnalyticsState" class="admin-users-state">{{ state.adminAnalyticsState }}</div>
          <div v-else-if="state.adminAnalyticsOverview" class="admin-analytics">
            <div class="admin-analytics-cards">
              <div class="admin-stat"><span>回答</span><strong>{{ state.adminAnalyticsOverview.answers }}</strong></div>
              <div class="admin-stat"><span>Grounded 率</span><strong>{{ percent(state.adminAnalyticsOverview.grounded_rate) }}</strong></div>
              <div class="admin-stat"><span>拒答率</span><strong>{{ percent(state.adminAnalyticsOverview.refusal_rate) }}</strong></div>
              <div class="admin-stat"><span>反馈覆盖</span><strong>{{ percent(state.adminAnalyticsOverview.feedback_coverage) }}</strong></div>
              <div class="admin-stat"><span>点踩率</span><strong>{{ percent(state.adminAnalyticsOverview.negative_rate) }}</strong></div>
              <div class="admin-stat"><span>引用点击率</span><strong>{{ percent(state.adminAnalyticsOverview.citation_click_rate) }}</strong></div>
            </div>
            <div class="admin-analytics-grid">
              <div>
                <div class="admin-section-title">按知识库</div>
                <table class="admin-analytics-table">
                  <thead><tr><th>库</th><th>回答</th><th>点踩</th><th>点击</th></tr></thead>
                  <tbody>
                    <tr v-for="item in state.adminAnalyticsLibraries" :key="item.library">
                      <td>{{ item.library }}</td>
                      <td>{{ item.answers }}</td>
                      <td>{{ item.negative }}</td>
                      <td>{{ item.clicks }}</td>
                    </tr>
                  </tbody>
                </table>
                <div v-if="!state.adminAnalyticsLibraries.length" class="admin-empty">近 30 天没有可统计的检索结果。</div>
              </div>
              <div>
                <div class="admin-section-title">点踩原因</div>
                <div class="admin-reason-list">
                  <span v-for="item in state.adminAnalyticsReasons" :key="item.reason" class="reason-chip">{{ reasonLabel(item.reason) }} · {{ item.count }}</span>
                </div>
                <div v-if="!state.adminAnalyticsReasons.length" class="admin-empty">近 30 天还没有点踩原因。</div>
                <div class="admin-section-title">分流分布</div>
                <div class="admin-reason-list">
                  <span v-for="item in state.adminAnalyticsCategories" :key="item.category" class="reason-chip">{{ categoryLabel(item.category) }} · {{ item.count }}</span>
                </div>
                <div class="admin-section-title">问题聚类</div>
                <div class="admin-cluster-list">
                  <div v-for="item in state.adminAnalyticsClusters" :key="item.label" class="admin-cluster-row">
                    <strong>{{ item.label }}</strong>
                    <small>{{ item.size }} 条 · {{ (item.reasons || []).map(reason => reasonLabel(reason.reason)).join('、') || '未分类' }}</small>
                  </div>
                  <div v-if="!state.adminAnalyticsClusters.length" class="admin-empty">近 30 天没有可聚类的点踩问题。</div>
                </div>
              </div>
            </div>
          </div>
          </div>
          </div>
          <div v-else-if="state.adminQualityTab === 'feedback'">
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
            <button class="toolbar-btn" type="button" @click="exportAdminFeedback">导出 CSV</button>
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
                  <button v-if="state.adminFeedbackDetail.sentiment === 'negative'" class="toolbar-btn" type="button" @click="makeTask">建内容任务</button>
                </div>
              </template>
              <div v-else class="admin-empty">从左侧选择一条反馈查看详情。</div>
            </div>
          </div>
          </div>
          <div v-else-if="state.adminQualityTab === 'tasks'" class="admin-tasks">
            <div class="admin-feedback-filters">
              <select v-model="state.adminContentTaskFilters.status" @change="loadTasks(1)">
                <option value="">全部状态</option>
                <option v-for="item in taskStatusOptions" :key="item[0]" :value="item[0]">{{ item[1] }}</option>
              </select>
              <select v-model="state.adminContentTaskFilters.priority" @change="loadTasks(1)">
                <option value="">全部优先级</option>
                <option v-for="item in taskPriorityOptions" :key="item[0]" :value="item[0]">{{ item[1] }}</option>
              </select>
              <button class="toolbar-btn" type="button" @click="loadTasks(1)">刷新</button>
            </div>
            <div v-if="state.adminContentTaskState" class="admin-users-state">{{ state.adminContentTaskState }}</div>
            <div class="admin-task-list">
              <div v-if="!state.adminContentTasks.length" class="admin-empty">还没有内容任务。到反馈详情里点“建内容任务”。</div>
              <div v-for="task in state.adminContentTasks" :key="task.id" class="admin-task-row">
                <div class="admin-task-main">
                  <strong>#{{ task.id }} {{ task.title }}</strong>
                  <small>{{ taskKindLabel(task.kind) }} · {{ taskPriorityLabel(task.priority) }} · {{ task.source }}{{ task.heading ? ' > ' + task.heading : '' }} · 关联反馈 {{ task.feedback_count }}</small>
                  <p v-if="task.resolution_note" class="admin-feedback-comment">{{ task.resolution_note }}</p>
                </div>
                <select v-model="task.eval_run_id" @change="saveTask(task)">
                  <option :value="0">未关联评测</option>
                  <option v-for="run in state.adminEvalRuns" :key="run.id" :value="run.id">#{{ run.id }} {{ run.name }}</option>
                </select>
                <select v-model="task.status" @change="saveTask(task)">
                  <option v-for="item in taskStatusOptions" :key="item[0]" :value="item[0]">{{ item[1] }}</option>
                </select>
              </div>
            </div>
            <div class="admin-feedback-pagination">
              <button type="button" :disabled="state.adminContentTaskPage <= 1" @click="loadTasks(state.adminContentTaskPage - 1)">上一页</button>
              <span>第 {{ state.adminContentTaskPage }} / {{ state.adminContentTaskPages }} 页 · 共 {{ state.adminContentTaskTotal }} 条</span>
              <button type="button" :disabled="state.adminContentTaskPage >= state.adminContentTaskPages" @click="loadTasks(state.adminContentTaskPage + 1)">下一页</button>
            </div>
          </div>
          <div v-else-if="state.adminQualityTab === 'curated'" class="admin-curated">
            <p class="admin-copy">点赞回答会进入候选池。只有状态“已通过”、勾选“评测通过”和“用于 few-shot”，同时服务端 CURATED_FEWSHOT_ENABLED=1 时，示例才会进入提示词；示例不作为事实来源。</p>
            <div class="admin-feedback-filters">
              <select v-model="state.adminCuratedFilters.status" @change="loadCurated(1)">
                <option value="">全部状态</option>
                <option v-for="item in curatedStatusOptions" :key="item[0]" :value="item[0]">{{ item[1] }}</option>
              </select>
              <button class="toolbar-btn" type="button" @click="loadCurated(1)">刷新</button>
            </div>
            <div v-if="state.adminCuratedState" class="admin-users-state">{{ state.adminCuratedState }}</div>
            <div class="admin-task-list">
              <div v-if="!state.adminCuratedExamples.length" class="admin-empty">还没有候选。用户点👍后会自动出现。</div>
              <div v-for="item in state.adminCuratedExamples" :key="item.id" class="admin-task-row admin-curated-row">
                <div class="admin-task-main">
                  <strong>{{ item.question }}</strong>
                  <small>{{ item.library || '未标注库' }} · 反馈 #{{ item.feedback_id }} · {{ item.reviewer_name || '未审核' }}</small>
                  <pre class="admin-curated-answer">{{ item.answer }}</pre>
                </div>
                <div class="admin-curated-actions">
                  <select v-model="item.eval_run_id" @change="saveCurated(item)">
                    <option :value="0">未关联评测</option>
                    <option v-for="run in state.adminEvalRuns" :key="run.id" :value="run.id">#{{ run.id }} {{ run.name }}</option>
                  </select>
                  <select v-model="item.status" @change="saveCurated(item)">
                    <option v-for="option in curatedStatusOptions" :key="option[0]" :value="option[0]">{{ option[1] }}</option>
                  </select>
                  <label class="admin-curated-toggle">
                    <input type="checkbox" v-model="item.eval_passed" @change="saveCurated(item)" />
                    评测通过
                  </label>
                  <label class="admin-curated-toggle">
                    <input type="checkbox" v-model="item.use_as_few_shot" @change="saveCurated(item)" />
                    用于 few-shot
                  </label>
                </div>
              </div>
            </div>
            <div class="admin-feedback-pagination">
              <button type="button" :disabled="state.adminCuratedPage <= 1" @click="loadCurated(state.adminCuratedPage - 1)">上一页</button>
              <span>第 {{ state.adminCuratedPage }} / {{ state.adminCuratedPages }} 页 · 共 {{ state.adminCuratedTotal }} 条</span>
              <button type="button" :disabled="state.adminCuratedPage >= state.adminCuratedPages" @click="loadCurated(state.adminCuratedPage + 1)">下一页</button>
            </div>
          </div>
          <div v-else-if="state.adminQualityTab === 'experiments'" class="admin-experiments">
            <p class="admin-copy">实验默认关闭。服务端 EXPERIMENTS_ENABLED=1 时才会按用户分桶；这里只能覆盖检索参数，可随时暂停或因护栏暂停。</p>
            <div class="admin-feedback-filters">
              <button class="toolbar-btn" type="button" @click="toggleExperimentForm">新建实验</button>
              <button class="toolbar-btn" type="button" @click="loadExperiments">刷新</button>
            </div>
            <div v-if="experimentForm.open" class="admin-experiment-form">
              <input v-model="experimentForm.key" placeholder="key（小写字母/数字/-）" />
              <input v-model="experimentForm.name" placeholder="实验名称" />
              <input v-model="experimentForm.controlKey" placeholder="对照变体 key" />
              <input v-model="experimentForm.treatmentKey" placeholder="实验变体 key" />
              <input v-model.number="experimentForm.traffic" type="number" min="1" max="99" placeholder="实验流量 %" />
              <textarea v-model="experimentForm.config" placeholder='实验组检索参数 JSON，例如 {"MIN_RERANK_SCORE": 0.5}'></textarea>
              <button class="primary-btn" type="button" @click="createExperimentFromForm">创建</button>
            </div>
            <div v-if="state.adminExperimentState" class="admin-users-state">{{ state.adminExperimentState }}</div>
            <div class="admin-task-list">
              <div v-if="!state.adminExperiments.length" class="admin-empty">还没有实验。</div>
              <div v-for="experiment in state.adminExperiments" :key="experiment.key" class="admin-task-row admin-experiment-row">
                <div class="admin-task-main">
                  <strong>{{ experiment.key }} · {{ experiment.name }}</strong>
                  <small>{{ variantSummary(experiment) }} · {{ experiment.status }}</small>
                </div>
                <div class="admin-curated-actions">
                  <select v-model="experiment.status" @change="saveExperiment(experiment)">
                    <option v-for="item in experimentStatusOptions" :key="item[0]" :value="item[0]">{{ item[1] }}</option>
                  </select>
                  <button class="toolbar-btn" type="button" @click="showExperimentResults(experiment.key)">看结果</button>
                </div>
              </div>
            </div>
            <div v-if="state.adminExperimentResultsState" class="admin-users-state">{{ state.adminExperimentResultsState }}</div>
            <div v-else-if="state.adminExperimentResults" class="admin-experiment-results">
              <div class="admin-section-title">实验结果 · {{ state.adminExperimentResults.experiment.key }}</div>
              <table class="admin-analytics-table">
                <thead>
                  <tr><th>变体</th><th>用户</th><th>回答</th><th>拒答率</th><th>点踩率</th><th>p95 ms</th><th>护栏</th></tr>
                </thead>
                <tbody>
                  <tr v-for="item in state.adminExperimentResults.variants" :key="item.variant_key">
                    <td>{{ item.variant_key }}{{ item.is_control ? '（对照）' : '' }}</td>
                    <td>{{ item.assignments }}</td>
                    <td>{{ item.answers }}</td>
                    <td>{{ rate(item.refusal_rate) }}</td>
                    <td>{{ rate(item.negative_rate) }}</td>
                    <td>{{ item.p95_latency_ms ?? '—' }}</td>
                    <td>{{ item.guardrail_breached ? item.guardrail_flags.join('；') : '正常' }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
          <div v-else-if="state.adminQualityTab === 'eval'" class="admin-eval">
            <p class="admin-copy">评测记录来自 run_retrieval_eval --save。这里只读展示，不在线跑模型。</p>
            <div class="admin-feedback-filters">
              <button class="toolbar-btn" type="button" @click="loadEvals(1)">刷新</button>
            </div>
            <div v-if="state.adminEvalState" class="admin-users-state">{{ state.adminEvalState }}</div>
            <div class="admin-task-list">
              <div v-if="!state.adminEvalRuns.length" class="admin-empty">还没有评测记录。运行评测时加 --save。</div>
              <div v-for="run in state.adminEvalRuns" :key="run.id" class="admin-task-row admin-eval-row">
                <div class="admin-task-main">
                  <strong>#{{ run.id }} {{ run.name }} · {{ datasetName(run.dataset) }}</strong>
                  <small>{{ formatTime(run.created_at) }} · hit@5={{ run.aggregate['hit@5'] ?? '—' }} · false_answer={{ run.aggregate.false_answer_rate ?? '—' }}</small>
                </div>
                <button class="toolbar-btn" type="button" @click="showEvalRun(run.id)">详情</button>
              </div>
            </div>
            <div class="admin-feedback-pagination">
              <button type="button" :disabled="state.adminEvalPage <= 1" @click="loadEvals(state.adminEvalPage - 1)">上一页</button>
              <span>第 {{ state.adminEvalPage }} / {{ state.adminEvalPages }} 页 · 共 {{ state.adminEvalTotal }} 条</span>
              <button type="button" :disabled="state.adminEvalPage >= state.adminEvalPages" @click="loadEvals(state.adminEvalPage + 1)">下一页</button>
            </div>
            <div v-if="state.adminEvalDetailState" class="admin-users-state">{{ state.adminEvalDetailState }}</div>
            <div v-else-if="state.adminEvalDetail" class="admin-eval-detail">
              <div class="admin-section-title">评测详情 · {{ state.adminEvalDetail.name }}</div>
              <table class="admin-analytics-table">
                <thead><tr><th>case</th><th>可回答</th><th>grounded</th><th>hit@5</th><th>错误</th></tr></thead>
                <tbody>
                  <tr v-for="item in state.adminEvalDetail.results" :key="item.id">
                    <td>{{ item.case_id }}</td>
                    <td>{{ item.answerable ? '是' : '否' }}</td>
                    <td>{{ item.grounded === null ? '—' : (item.grounded ? '是' : '否') }}</td>
                    <td>{{ item.metrics['hit@5'] ?? '—' }}</td>
                    <td>{{ item.error || '' }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
          <div v-else class="admin-audit">
            <p class="admin-copy">管理端操作审计：记录谁在什么时候改了什么，不保存问题、回答或评论正文。</p>
            <div class="admin-feedback-filters">
              <button class="toolbar-btn" type="button" @click="loadAudits(1)">刷新</button>
            </div>
            <div v-if="state.adminAuditState" class="admin-users-state">{{ state.adminAuditState }}</div>
            <div class="admin-task-list">
              <div v-if="!state.adminAuditEvents.length" class="admin-empty">还没有审计记录。</div>
              <div v-for="event in state.adminAuditEvents" :key="event.id" class="admin-task-row admin-audit-row">
                <div class="admin-task-main">
                  <strong>{{ event.action }} · {{ event.target_type }} {{ event.target_id }}</strong>
                  <small>{{ formatTime(event.created_at) }} · {{ event.actor_name || '系统' }}</small>
                  <pre class="admin-curated-answer">{{ formatDetail(event.detail) }}</pre>
                </div>
              </div>
            </div>
            <div class="admin-feedback-pagination">
              <button type="button" :disabled="state.adminAuditPage <= 1" @click="loadAudits(state.adminAuditPage - 1)">上一页</button>
              <span>第 {{ state.adminAuditPage }} / {{ state.adminAuditPages }} 页 · 共 {{ state.adminAuditTotal }} 条</span>
              <button type="button" :disabled="state.adminAuditPage >= state.adminAuditPages" @click="loadAudits(state.adminAuditPage + 1)">下一页</button>
            </div>
          </div>
        </div>
        <div class="modal-footer">
          <button class="toolbar-btn" type="button" @click="refreshAll">刷新</button>
          <button class="primary-btn" type="button" @click="state.adminFeedbackOpen = false">完成</button>
        </div>
      </div>
    </div>
  `,
}
