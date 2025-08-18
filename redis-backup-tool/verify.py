from __future__ import annotations

import json
import random
from pathlib import Path

from redis_utils import build_cluster_config, make_cluster_client, pttl_safe


def _iter_rows(dir_path: Path):
    for p in sorted((dir_path / "keys").glob("keys-part-*.jsonl")):
        with p.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    yield json.loads(line)


def run_verify(args) -> int:
    cfg = build_cluster_config(args.env_profile, args.redis_nodes)
    rc = make_cluster_client(cfg)
    in_dir = Path(args.input)

    # Load up to N rows uniformly sampled across files
    all_rows = list(_iter_rows(in_dir))
    if not all_rows:
        print("No keys found in backup.")
        return 1
    sample = (
        all_rows
        if len(all_rows) <= args.sample
        else random.sample(all_rows, args.sample)
    )

    missing = 0
    ttl_mismatch = 0
    for row in sample:
        key = row["key"]
        if not rc.exists(key):
            missing += 1
            continue
        expected = row.get("pttl")
        if isinstance(expected, int):
            ttl = pttl_safe(rc, key)
            # Compare with a tolerance since time passes
            if ttl is None or abs(ttl - expected) > 5000:
                ttl_mismatch += 1

    print(
        f"Verify sample={len(sample)} -> missing={missing}, ttl_mismatch={ttl_mismatch}"
    )
    return 0 if missing == 0 else 1
