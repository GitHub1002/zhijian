"""把当前 SQLite 与 Qdrant 复制成一个只读评测快照。

示例：
  python evals/prepare_eval_env.py
  python evals/run_retrieval_eval.py --dataset evals/datasets/seed_v1.jsonl \
      --db-path data/eval/snapshot-.../knowledge.db \
      --qdrant-path data/eval/snapshot-.../qdrant
"""
import argparse
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description="准备评测快照")
    parser.add_argument("--db", default=str(ROOT / "data" / "knowledge.db"))
    parser.add_argument("--qdrant", default=str(ROOT / "data" / "qdrant"))
    parser.add_argument("--out", default=str(ROOT / "data" / "eval"))
    args = parser.parse_args()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = Path(args.out) / f"snapshot-{stamp}"
    target.mkdir(parents=True, exist_ok=True)

    source_db = Path(args.db)
    target_db = target / "knowledge.db"
    if source_db.exists():
        # 用 SQLite backup API，避免直接复制未 checkpoint 的 WAL。
        src = sqlite3.connect(str(source_db))
        dst = sqlite3.connect(str(target_db))
        src.backup(dst)
        dst.close()
        src.close()
        print(f"db:     {target_db}")

    source_qdrant = Path(args.qdrant)
    target_qdrant = target / "qdrant"
    if source_qdrant.exists():
        if target_qdrant.exists():
            shutil.rmtree(target_qdrant)
        # 不复制 Qdrant 本地锁文件，否则快照会被当成“已被其他进程占用”。
        shutil.copytree(
            source_qdrant,
            target_qdrant,
            ignore=shutil.ignore_patterns(".lock", "*.lock"),
        )
        print(f"qdrant: {target_qdrant}")

    print("\n运行评测：")
    print(
        f"  python evals/run_retrieval_eval.py --dataset evals/datasets/seed_v1.jsonl "
        f"--db-path {target_db} --qdrant-path {target_qdrant}"
    )


if __name__ == "__main__":
    main()
