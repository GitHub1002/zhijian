"""检索指标：Hit@k、Recall@k、Precision@k、MRR、NDCG@k、AP。

默认按 `source + heading` 匹配，因为重新切分后 chunk_id 会变化；
需要按当前切块评估时传 `match="chunk_id"`。
"""
import math


def _key(item, match):
    if match == "chunk_id":
        return str(item.get("chunk_id") or item.get("id") or "")
    return (str(item.get("source") or ""), str(item.get("heading") or ""))


def _keys(items, match):
    return {_key(item, match) for item in (items or [])}


def hit_at_k(retrieved, expected, k=5, match="source_heading"):
    expected_keys = _keys(expected, match)
    if not expected_keys:
        return None
    return 1.0 if any(_key(item, match) in expected_keys for item in (retrieved or [])[:k]) else 0.0


def recall_at_k(retrieved, expected, k=5, match="source_heading"):
    expected_keys = _keys(expected, match)
    if not expected_keys:
        return None
    found = {
        key
        for key in (_key(item, match) for item in (retrieved or [])[:k])
        if key in expected_keys
    }
    return len(found) / len(expected_keys)


def _first_hit_ranks(retrieved, expected_keys, k, match):
    """同一个 source+heading 可能对应多个切块，只按第一次命中计一次。"""
    seen = set()
    ranks = []
    for rank, item in enumerate((retrieved or [])[:k], start=1):
        key = _key(item, match)
        if key in expected_keys and key not in seen:
            seen.add(key)
            ranks.append(rank)
    return ranks


def precision_at_k(retrieved, expected, k=5, match="source_heading"):
    if k <= 0:
        return 0.0
    expected_keys = _keys(expected, match)
    if not expected_keys:
        return 0.0
    return len(_first_hit_ranks(retrieved, expected_keys, k, match)) / k


def mrr_at_k(retrieved, expected, k=10, match="source_heading"):
    expected_keys = _keys(expected, match)
    if not expected_keys:
        return None
    ranks = _first_hit_ranks(retrieved, expected_keys, k, match)
    return 1.0 / ranks[0] if ranks else 0.0


def ndcg_at_k(retrieved, expected, k=10, match="source_heading"):
    expected_keys = _keys(expected, match)
    if not expected_keys:
        return None
    ranks = _first_hit_ranks(retrieved, expected_keys, k, match)
    dcg = sum(1.0 / math.log2(rank + 1) for rank in ranks)
    ideal = sum(
        1.0 / math.log2(rank + 1)
        for rank in range(1, min(len(expected_keys), k) + 1)
    )
    return dcg / ideal if ideal else 0.0


def average_precision(retrieved, expected, k=10, match="source_heading"):
    expected_keys = _keys(expected, match)
    if not expected_keys:
        return None
    ranks = _first_hit_ranks(retrieved, expected_keys, k, match)
    total = sum((index + 1) / rank for index, rank in enumerate(ranks))
    return total / len(expected_keys)


def evaluate_case(retrieved, expected, k_values=(3, 5, 12), match="source_heading"):
    result = {}
    for k in k_values:
        result[f"hit@{k}"] = hit_at_k(retrieved, expected, k, match)
        result[f"recall@{k}"] = recall_at_k(retrieved, expected, k, match)
        result[f"precision@{k}"] = precision_at_k(retrieved, expected, k, match)
        result[f"ndcg@{k}"] = ndcg_at_k(retrieved, expected, k, match)
    top_k = max(k_values)
    result["mrr"] = mrr_at_k(retrieved, expected, top_k, match)
    result["ap"] = average_precision(retrieved, expected, top_k, match)
    return result
