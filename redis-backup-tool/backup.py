from __future__ import annotations

import json
import random
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from redis_utils import (
    build_cluster_config,
    make_cluster_client,
    key_type,
    pttl_safe,
)
from s3_utils import parse_s3_uri, get_s3_client, upload_file


def _gen_backup_id(env_profile: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = f"{random.randrange(16**4):04x}"
    return f"redis-backup-{env_profile}-{ts}-{suffix}"


def _write_jsonl_part(out_dir: Path, part_idx: int, rows: list[dict[str, Any]]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / f"keys-part-{part_idx:04d}.jsonl"
    with p.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return p


def _dump_key(r, key: str) -> dict[str, Any] | None:
    t = key_type(r, key)
    ttl = pttl_safe(r, key)
    row: dict[str, Any]
    if t == "string":
        row = {"type": t, "key": key, "value": r.get(key)}
    elif t == "hash":
        row = {"type": t, "key": key, "value": r.hgetall(key)}
    elif t == "list":
        row = {"type": t, "key": key, "value": r.lrange(key, 0, -1)}
    elif t == "set":
        row = {"type": t, "key": key, "value": sorted(r.smembers(key))}
    elif t == "zset":
        items = r.zrange(key, 0, -1, withscores=True)
        row = {"type": t, "key": key, "value": items}
    elif t == "stream":
        entries = r.xrange(key, min="-", max="+", count=None)
        try:
            groups = r.xinfo_groups(key)
        except Exception:
            groups = []
        row = {"type": t, "key": key, "value": entries, "groups": groups}
    else:
        return None
    if ttl is not None:
        row["pttl"] = ttl
    return row


def _tar_gz_folder(src_dir: Path, tar_path: Path) -> Path:
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(src_dir, arcname=src_dir.name)
    return tar_path


def run_backup(args) -> int:
    cfg = build_cluster_config(args.env_profile, args.redis_nodes)
    rc = make_cluster_client(cfg)

    backup_id = _gen_backup_id(cfg.env_profile)
    out_root = Path(args.out_dir).expanduser().resolve()
    out_dir = out_root / backup_id
    keys_dir = out_dir / "keys"
    keys_dir.mkdir(parents=True, exist_ok=True)

    part_rows: list[dict] = []
    part_idx = 0
    total = 0

    # Metadata
    meta = {
        "backup_id": backup_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "env_profile": cfg.env_profile,
        "match": args.match,
        "chunk_keys": args.chunk_keys,
    }

    # Iterate keys
    pattern = args.match or "*"
    for key in rc.scan_iter(match=pattern, count=1000):
        try:
            row = _dump_key(rc, key)
            if row is None:
                continue
            part_rows.append(row)
            total += 1
            if len(part_rows) >= args.chunk_keys:
                _write_jsonl_part(keys_dir, part_idx, part_rows)
                part_rows.clear()
                part_idx += 1
        except Exception as e:
            # Keep going for robustness
            print(f"WARN: failed dumping key {key}: {e}")

    if part_rows:
        _write_jsonl_part(keys_dir, part_idx, part_rows)

    meta["total_keys"] = total
    with (out_dir / "metadata.json").open("w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    # Create tar.gz next to folder
    tar_path = out_root / f"{backup_id}.tar.gz"
    _tar_gz_folder(out_dir, tar_path)
    print(f"Backup written: {out_dir}")
    print(f"Archive: {tar_path}")

    # Upload if requested
    if args.s3_uri:
        loc = parse_s3_uri(args.s3_uri)
        if not loc:
            raise SystemExit("Invalid S3 URI")
        s3 = get_s3_client()
        s3_uri = upload_file(s3, loc, str(tar_path), tar_path.name)
        print(f"Uploaded: {s3_uri}")

    return 0
