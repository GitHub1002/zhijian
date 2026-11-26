"""手动重建全文索引。

正常入库时 `replace_search_chunks` 会增量维护 FTS，只有升级分词规则或
怀疑索引不一致时才需要执行本脚本。
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import db  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="重建全文索引")
    parser.add_argument("--db-path", default=str(ROOT / "data" / "knowledge.db"))
    args = parser.parse_args()

    db._DB_PATH = Path(args.db_path)
    db.rebuild_fts()
    print(f"FTS rebuilt: {args.db_path}")


if __name__ == "__main__":
    main()
