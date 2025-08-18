from __future__ import annotations

from s3_utils import parse_s3_uri, get_s3_client, list_backups


def run_list(args) -> int:
    loc = parse_s3_uri(args.s3_uri)
    if not loc:
        raise SystemExit("S3_URI is required to list backups")
    s3 = get_s3_client()
    items = list_backups(s3, loc)
    if not items:
        print("No backups found.")
        return 0
    for it in items:
        print(f"{it['last_modified'].isoformat()}\t{it['size']:>10}\t{it['key']}")
    return 0
