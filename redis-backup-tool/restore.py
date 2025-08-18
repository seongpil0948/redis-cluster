from __future__ import annotations

import json
import tarfile
from pathlib import Path
from typing import Any

from redis_utils import build_cluster_config, make_cluster_client
from s3_utils import parse_s3_uri, get_s3_client, list_backups, download_file


def _extract_tar(tar_path: Path, work_dir: Path) -> Path:
    with tarfile.open(tar_path, "r:gz") as tar:
        names = tar.getnames()
        root = names[0].split("/")[0]
        tar.extractall(path=work_dir)
    return work_dir / root


def _apply_row(rc, row: dict[str, Any], overwrite: bool, recreate_groups: bool) -> None:
    key = row["key"]
    t = row["type"]
    if not overwrite and rc.exists(key):
        return
    if t == "string":
        rc.set(key, row["value"])  # type: ignore[arg-type]
    elif t == "hash":
        if row["value"]:
            rc.hset(key, mapping=row["value"])  # type: ignore[arg-type]
    elif t == "list":
        vals = row["value"] or []
        if vals:
            rc.rpush(key, *vals)
    elif t == "set":
        vals = row["value"] or []
        if vals:
            rc.sadd(key, *vals)
    elif t == "zset":
        vals = row["value"] or []
        if vals:
            # redis-py 5 supports zadd with dict[name]=score
            rc.zadd(key, {m: s for m, s in vals})
    elif t == "stream":
        entries = row.get("value", [])
        for entry_id, fields in entries:
            # Use explicit IDs to preserve ordering and IDs when possible
            rc.xadd(key, fields, id=entry_id)
        if recreate_groups:
            for g in row.get("groups", []) or []:
                try:
                    rc.xgroup_create(
                        name=key,
                        groupname=g.get("name"),
                        id=g.get("last-delivered-id", "$"),
                        mkstream=True,
                    )
                except Exception:
                    pass
    else:
        return

    pttl = row.get("pttl")
    if isinstance(pttl, int):
        rc.pexpire(key, pttl)


def _iter_jsonl_parts(dir_path: Path):
    for p in sorted((dir_path / "keys").glob("keys-part-*.jsonl")):
        with p.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    yield json.loads(line)


def run_restore(args) -> int:
    cfg = build_cluster_config(args.env_profile, args.redis_nodes)
    rc = make_cluster_client(cfg)

    input_dir: Path

    if args.input:
        inp = Path(args.input)
        if inp.suffixes[-2:] == [".tar", ".gz"] or inp.suffix == ".tgz":
            input_dir = _extract_tar(inp, Path(args.work_dir))
        else:
            input_dir = inp
    elif args.from_s3:
        loc = parse_s3_uri(args.s3_uri)
        if not loc:
            raise SystemExit("S3_URI is required for --from-s3")
        s3 = get_s3_client()
        backups = list_backups(s3, loc)
        if not backups:
            raise SystemExit("No backups found in S3")
        chosen = backups[0] if args.from_s3 == "latest" else None
        if args.from_s3 == "by-id":
            if not args.backup_id:
                raise SystemExit("--backup-id is required when using --from-s3 by-id")
            match_key = (
                f"{loc.prefix}/{args.backup_id}.tar.gz"
                if loc.prefix
                else f"{args.backup_id}.tar.gz"
            )
            for item in backups:
                if item["key"] == match_key:
                    chosen = item
                    break
            if not chosen:
                raise SystemExit(f"Backup id not found: {args.backup_id}")
        # Download and extract
        tar_local = Path(args.work_dir) / Path(chosen["key"]).name
        print("Downloading backup from S3:", chosen["key"])
        download_file(s3, loc, Path(chosen["key"]).name, str(tar_local))
        input_dir = _extract_tar(tar_local, Path(args.work_dir))
    else:
        raise SystemExit("One of --input or --from-s3 is required")

    # Restore
    count = 0
    for row in _iter_jsonl_parts(input_dir):
        _apply_row(
            rc,
            row,
            overwrite=args.overwrite,
            recreate_groups=args.recreate_stream_groups,
        )
        count += 1
        if count % 1000 == 0:
            print(f"Restored {count} keys...")
    print(f"Restore complete. Restored {count} keys.")
    return 0
