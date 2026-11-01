from pathlib import Path
import hashlib

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from packages.common.config import settings
from packages.common.utils import DomainError, file_hash


class Storage:
    def __init__(self):
        cfg = settings()
        args = dict(aws_access_key_id=cfg.s3_access_key, aws_secret_access_key=cfg.s3_secret_key,
                    region_name="us-east-1", config=Config(signature_version="s3v4", s3={"addressing_style": "path"}))
        self.client = boto3.client("s3", endpoint_url=cfg.s3_endpoint, **args)
        self.public = boto3.client("s3", endpoint_url=cfg.s3_public_endpoint, **args)
        self.bucket = cfg.s3_bucket

    def ensure_bucket(self):
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError as exc:
            if str(exc.response["Error"]["Code"]) not in ("404", "NoSuchBucket"):
                raise
            self.client.create_bucket(Bucket=self.bucket)
        try:
            self.client.put_bucket_cors(Bucket=self.bucket, CORSConfiguration={"CORSRules": [{
                "AllowedOrigins": [settings().web_origin], "AllowedMethods": ["GET", "PUT", "HEAD"],
                "AllowedHeaders": ["*"], "ExposeHeaders": ["ETag"], "MaxAgeSeconds": 3600}]})
        except ClientError as exc:
            # MinIO configures CORS through MINIO_API_CORS_ALLOW_ORIGIN, not this S3 operation.
            if exc.response["Error"]["Code"] != "NotImplemented":
                raise

    def download(self, key: str, target: Path):
        try:
            self.client.download_file(self.bucket, key, str(target))
        except ClientError as exc:
            if str(exc.response["Error"]["Code"]) in ("404", "NoSuchKey"):
                raise DomainError("E_UPLOAD_MISSING", "Uploaded object not found", 409) from exc
            raise

    def upload(self, path: Path, key: str, media_type: str, *, reuse_identical=False):
        # Conditional write ensures a run-scoped artifact is never overwritten.
        try:
            with path.open("rb") as stream:
                self.client.put_object(Bucket=self.bucket, Key=key, Body=stream,
                                       ContentType=media_type, IfNoneMatch="*",
                                       Metadata={"sha256": file_hash(path)})
        except ClientError as exc:
            if not reuse_identical or str(exc.response["Error"]["Code"]) not in ("412", "PreconditionFailed"):
                raise
            # Recovery after an object write but before the DB commit may reuse
            # identical bytes. Never replace an existing, different artifact.
            if hashlib.sha256(self.read(key)).hexdigest() != file_hash(path):
                raise DomainError("E_ARTIFACT_CONFLICT", "Existing immutable artifact has different content", 409) from exc
        head = self.client.head_object(Bucket=self.bucket, Key=key)
        if head["ContentLength"] != path.stat().st_size or head["Metadata"].get("sha256") != file_hash(path):
            raise DomainError("E_ARTIFACT_WRITE", "Stored artifact verification failed", 500)

    def upload_url(self, key: str, size: int):
        return self.public.generate_presigned_url("put_object", Params={"Bucket": self.bucket, "Key": key,
            "ContentLength": size, "IfNoneMatch": "*"}, ExpiresIn=900)

    def url(self, key: str):
        return self.public.generate_presigned_url("get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=3600)

    def read(self, key: str) -> bytes:
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()

