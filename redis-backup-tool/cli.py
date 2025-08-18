import argparse
import os
import sys

from backup import run_backup
from restore import run_restore
from listing import run_list
from verify import run_verify


def add_common_env_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--env-profile",
        dest="env_profile",
        default=os.environ.get("ENV_PROFILE", "local"),
        help="Environment profile: local|dev|prd (default: %(default)s)",
    )
    parser.add_argument(
        "--redis-nodes",
        dest="redis_nodes",
        default=os.environ.get("REDIS_NODES"),
        help="Override node list, e.g. host1:port,host2:port",
    )
    parser.add_argument(
        "--s3-uri",
        dest="s3_uri",
        default=os.environ.get("S3_URI"),
        help="S3 URI for uploads/downloads (e.g., s3://bucket/prefix)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="redis-backup-tool",
        description="Logical backup/restore for Redis Cluster with S3 integration",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # backup
    p_b = sub.add_parser(
        "backup", help="Create logical backup and optionally upload to S3"
    )
    add_common_env_args(p_b)
    p_b.add_argument("--match", default="*", help="Key pattern to match (default: *)")
    p_b.add_argument("--chunk-keys", type=int, default=5000, help="Keys per JSONL part")
    p_b.add_argument(
        "-o",
        "--out-dir",
        default=os.environ.get("BACKUP_DIR", "/data/backups"),
        help="Local output dir",
    )
    p_b.set_defaults(func=run_backup)

    # restore
    p_r = sub.add_parser("restore", help="Restore from local backup or S3")
    add_common_env_args(p_r)
    src = p_r.add_mutually_exclusive_group()
    src.add_argument("--input", "-i", help="Local backup directory or .tar.gz path")
    src.add_argument(
        "--from-s3",
        choices=["latest", "by-id"],
        help="Download backup from S3. Use 'by-id' with --backup-id, or 'latest'",
    )
    p_r.add_argument("--backup-id", help="Backup ID when using --from-s3 by-id")
    p_r.add_argument(
        "--overwrite", action="store_true", help="Overwrite existing keys on restore"
    )
    p_r.add_argument(
        "--recreate-stream-groups",
        action="store_true",
        help="Recreate stream consumer groups metadata",
    )
    p_r.add_argument(
        "--work-dir", default="/tmp", help="Working directory for downloads/extracts"
    )
    p_r.set_defaults(func=run_restore)

    # list
    p_l = sub.add_parser("list", help="List backups available in S3")
    add_common_env_args(p_l)
    p_l.set_defaults(func=run_list)

    # verify
    p_v = sub.add_parser(
        "verify", help="Verify a backup directory against a live cluster"
    )
    add_common_env_args(p_v)
    p_v.add_argument(
        "-i", "--input", required=True, help="Local backup directory (extracted)"
    )
    p_v.add_argument("--sample", type=int, default=500, help="Number of keys to sample")
    p_v.set_defaults(func=run_verify)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(bool(args.func(args)))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
