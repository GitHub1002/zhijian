"""按保留期清理旧轨迹、点击、审计和已归档的旧记忆。

示例：
  python scripts/cleanup_retention.py --dry-run
  python scripts/cleanup_retention.py
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import config, db, retention  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="保留期清理")
    parser.add_argument("--db-path", default=str(ROOT / "data" / "knowledge.db"))
    parser.add_argument("--trace-days", type=int, default=config.TRACE_RETENTION_DAYS)
    parser.add_argument("--click-days", type=int, default=180)
    parser.add_argument("--audit-days", type=int, default=365)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    db._DB_PATH = Path(args.db_path)
    counts = retention.cleanup(
        trace_days=args.trace_days,
        click_days=args.click_days,
        audit_days=args.audit_days,
        dry_run=args.dry_run,
    )
    print("RETENTION CLEANUP" + (" (dry-run)" if args.dry_run else ""))
    print("=" * 24)
    if not counts:
        print("  no matching tables")
    for table, count in counts.items():
        print(f"  {table:28} {count}")
    print(f"  db: {args.db_path}")


if __name__ == "__main__":
    main()
