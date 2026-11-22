# 离线评测

这套脚本把“改检索/改切分/改 prompt 有没有变好”变成可复现的数字。运行时应用 `app/` 不依赖这里的任何包；评测依赖只放在 `evals/requirements-eval.txt`。

## 目录

```text
evals/
  datasets/seed_v1.jsonl      # 人工 golden set
  configs/thresholds.json     # 回归门槛
  lib/metrics.py              # Hit@k / Recall@k / Precision@k / MRR / NDCG / AP
  lib/dataset.py              # JSONL/JSON 加载与校验
  lib/runner.py               # 执行检索评测并汇总
  lib/report.py               # 报告输出与基线对比
  lib/ragas_adapter.py        # 可选 RAGAS 适配层
  run_retrieval_eval.py       # 检索评测
  run_ragas_eval.py           # 回答质量评测（默认 LLM Judge）
  check_thresholds.py         # 阈值门禁
  prepare_eval_env.py         # 复制 DB/Qdrant 快照
```

## Golden set 格式

一行一个 JSON：

```json
{
  "case_id": "golden-001",
  "question": "入职满 4 年的员工年假有多少天？",
  "library": "hr",
  "expected_sources": [
    {"source": "hr/请假制度.md", "heading": "员工请假管理制度 > 假期计算示例"}
  ],
  "reference_answer": "5 + 3 = 8 天。",
  "answerable": true,
  "hard_negative": false,
  "tags": ["hr", "numeric"],
  "label_source": "human",
  "notes": ""
}
```

- `expected_sources` 用 `source + heading`，因为重新切分后 `chunk_id` 会变。
- `answerable=false` 的样本要求系统拒答，用于统计 `correct_refusal_rate` 和 `false_answer_rate`。
- 当前 `seed_v1` 有 55 条：覆盖 6 个库、md/docx/pdf/txt、5 条不可回答样本。

## 常用命令

```bash
# 只验证 harness，不加载模型
python evals/run_retrieval_eval.py --dataset evals/datasets/seed_v1.jsonl --dry-run

# 真实检索评测
python evals/run_retrieval_eval.py \
  --dataset evals/datasets/seed_v1.jsonl --k 3,5,12 --name baseline

# 改参数后对比基线
python evals/run_retrieval_eval.py \
  --dataset evals/datasets/seed_v1.jsonl --k 5 \
  --config '{"RRF_K": 40}' --compare evals/reports/baseline.json

# 回答质量：默认用现有 DeepSeek 做 LLM Judge
python evals/run_ragas_eval.py \
  --dataset evals/datasets/seed_v1.jsonl --limit 20

# 安装 RAGAS 后可用
pip install -r evals/requirements-eval.txt
python evals/run_ragas_eval.py \
  --dataset evals/datasets/seed_v1.jsonl --limit 20 --provider ragas

# 阈值门禁
python evals/check_thresholds.py \
  --baseline evals/reports/baseline.json \
  --candidate evals/reports/latest.json
```

## 指标口径

| 指标 | 含义 |
|---|---|
| Hit@k | top-k 里至少有一个相关来源 |
| Recall@k | top-k 命中的相关来源 / 全部相关来源 |
| Precision@k | top-k 中相关来源占比 |
| MRR | 第一个相关来源排名的倒数 |
| NDCG@k | 考虑位置的排序质量 |
| correct_refusal_rate | 不可回答样本中正确拒答的比例 |
| false_answer_rate | 不可回答样本中仍然作答的比例 |
| false_refusal_rate | 可回答样本中被拒答的比例 |

RAG 指标（LLM Judge / RAGAS）：`faithfulness`、`answer_relevancy`、`context_precision`、`context_recall`。

## 评测隔离

- 真实评测建议先用 `python evals/prepare_eval_env.py` 复制一份 `data/eval/snapshot-.../`，再用 `--db-path` / `--qdrant-path` 指向快照。
- 首次真实运行会加载嵌入和重排模型；如果本机没有缓存，会触发下载。
- `--dry-run` 不导入 `app`，用于 CI 或快速检查脚本是否可用。
- 阈值先记录基线，稳定后再启用硬门禁；当前 `configs/thresholds.json` 是建议值，跑出第一版基线后按实际情况调整。

## 标注流程

1. 从 `answers` 导出真实问题，去重、脱敏。
2. 人工填写 `expected_sources`（source + heading）、`reference_answer`、`answerable`。
3. 20% 样本双人标注，计算一致性。
4. 冻结 `seed_v1`；后续只新增 `seed_v2`，不原地修改，避免评测漂移。
