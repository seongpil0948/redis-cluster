from __future__ import annotations

from dataclasses import dataclass

import boto3


@dataclass
class S3Location:
    bucket: str
    prefix: str


def parse_s3_uri(uri: str | None) -> S3Location | None:
    if not uri:
        return None
    if not uri.startswith("s3://"):
        raise ValueError("S3_URI must start with s3://")
    rest = uri[5:]
    if "/" in rest:
        bucket, prefix = rest.split("/", 1)
    else:
        bucket, prefix = rest, ""
    if prefix.endswith("/"):
        prefix = prefix[:-1]
    return S3Location(bucket=bucket, prefix=prefix)


def get_s3_client():
    # boto3 respects env vars, shared credentials, and role providers
    return boto3.client("s3")


def list_backups(s3: any, loc: S3Location) -> list[dict]:
    prefix = loc.prefix + "/" if loc.prefix else ""
    paginator = s3.get_paginator("list_objects_v2")
    items: list[dict] = []
    for page in paginator.paginate(Bucket=loc.bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.endswith(".tar.gz"):
                items.append(
                    {
                        "key": key,
                        "last_modified": obj["LastModified"],
                        "size": obj["Size"],
                    }
                )
    items.sort(key=lambda x: x["last_modified"], reverse=True)
    return items


def upload_file(s3: any, loc: S3Location, local_path: str, dest_name: str) -> str:
    key = f"{loc.prefix}/{dest_name}" if loc.prefix else dest_name
    s3.upload_file(local_path, loc.bucket, key)
    return f"s3://{loc.bucket}/{key}"


def download_file(s3: any, loc: S3Location, key_name: str, local_path: str) -> str:
    key = f"{loc.prefix}/{key_name}" if loc.prefix else key_name
    s3.download_file(loc.bucket, key, local_path)
    return local_path
