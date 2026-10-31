"""
Backblaze B2 storage utility (S3-compatible API).

Install:
    pip install boto3 python-dotenv

Create a .env file beside this script:
    B2_KEY_ID=your_application_key_id
    B2_APPLICATION_KEY=your_application_key
    B2_BUCKET_NAME=savira-bucket
    B2_REGION=us-east-005
    B2_ENDPOINT_URL=https://s3.us-east-005.backblazeb2.com

Use an Application Key with access to this bucket and read/write/list permissions.
Keep the bucket private and never commit .env to Git.

Commands:
    python storage.py test
    python storage.py upload "F:/resume.pdf" --key "users/sajid/documents/resume.pdf"
    python storage.py list
    python storage.py list --prefix "users/sajid/"
    python storage.py download "users/sajid/documents/resume.pdf"
    python storage.py download "users/sajid/documents/resume.pdf" --output "F:/resume-downloaded.pdf"
    python storage.py read "documents/readme.txt"
    python storage.py delete "users/sajid/documents/resume.pdf"

The "read" command is for UTF-8 text files. Use "download" for PDFs, images,
Office documents, audio, and other binary files.
"""

from __future__ import annotations

import argparse
import mimetypes
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

import boto3
from botocore.config import Config
from botocore.exceptions import (
    BotoCoreError,
    ClientError,
    EndpointConnectionError,
    SSLError,
)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print(
        "python-dotenv is not installed. Install it with: "
        "pip install python-dotenv",
        file=sys.stderr,
    )


def get_required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(
            f"Missing {name}. Add it to the .env file beside storage.py."
        )
    return value


def get_config():
    endpoint_url = get_required_env("B2_ENDPOINT_URL")
    region = get_required_env("B2_REGION")

    if not endpoint_url.startswith(("https://", "http://")):
        endpoint_url = "https://" + endpoint_url

    parsed = urlparse(endpoint_url)
    if not parsed.netloc:
        raise RuntimeError(
            "Invalid B2_ENDPOINT_URL. Expected, for example: "
            "https://s3.us-east-005.backblazeb2.com"
        )

    return endpoint_url.rstrip("/"), region


def create_s3_client():
    endpoint_url, region = get_config()

    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=get_required_env("B2_KEY_ID"),
        aws_secret_access_key=get_required_env("B2_APPLICATION_KEY"),
        region_name=region,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            connect_timeout=30,
            read_timeout=60,
            retries={
                "max_attempts": 3,
                "mode": "standard",
            },
        ),
    )


def get_bucket_name() -> str:
    return get_required_env("B2_BUCKET_NAME")


def test_connection(s3, bucket: str) -> None:
    # HeadBucket checks that the bucket exists and this key can access it.
    s3.head_bucket(Bucket=bucket)
    print(f"Connection successful. Bucket is accessible: {bucket}")


def upload_file(
    s3,
    bucket: str,
    local_path: str,
    object_key: str | None = None,
) -> None:
    source = Path(local_path).expanduser()

    if not source.exists():
        raise FileNotFoundError(f"File does not exist: {source}")
    if not source.is_file():
        raise ValueError(f"Path is not a file: {source}")

    key = object_key or source.name
    content_type, _ = mimetypes.guess_type(source.name)

    extra_args = {}
    if content_type:
        extra_args["ContentType"] = content_type

    print(f"Uploading {source} to s3://{bucket}/{key} ...")
    s3.upload_file(
        Filename=str(source),
        Bucket=bucket,
        Key=key,
        ExtraArgs=extra_args,
    )
    print("Upload successful.")


def list_files(s3, bucket: str, prefix: str = "") -> None:
    paginator = s3.get_paginator("list_objects_v2")
    found = False

    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for item in page.get("Contents", []):
            found = True
            print(
                f'{item["Key"]}\t'
                f'{item["Size"]:,} bytes\t'
                f'{item["LastModified"]}'
            )

    if not found:
        print("No files found.")


def download_file(
    s3,
    bucket: str,
    object_key: str,
    output_path: str | None = None,
) -> None:
    filename = object_key.rsplit("/", 1)[-1] or "download"
    destination = Path(output_path).expanduser() if output_path else Path(filename)
    destination.parent.mkdir(parents=True, exist_ok=True)

    print(f"Downloading s3://{bucket}/{object_key} to {destination} ...")
    s3.download_file(bucket, object_key, str(destination))
    print(f"Download successful: {destination}")


def read_text_file(
    s3,
    bucket: str,
    object_key: str,
    encoding: str = "utf-8",
) -> None:
    response = s3.get_object(Bucket=bucket, Key=object_key)
    body = response["Body"]

    try:
        contents = body.read().decode(encoding)
    finally:
        body.close()

    print(contents)


def delete_file(s3, bucket: str, object_key: str) -> None:
    confirmation = input(
        f'Type "yes" to delete s3://{bucket}/{object_key}: '
    ).strip().lower()

    if confirmation != "yes":
        print("Delete cancelled.")
        return

    s3.delete_object(Bucket=bucket, Key=object_key)
    print("Delete request completed.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage files in a Backblaze B2 bucket."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("test", help="Test connection and bucket access.")

    upload_parser = commands.add_parser("upload", help="Upload a local file.")
    upload_parser.add_argument("local_path")
    upload_parser.add_argument(
        "--key",
        help="Object key in the bucket, e.g. users/123/document.pdf",
    )

    list_parser = commands.add_parser("list", help="List objects in the bucket.")
    list_parser.add_argument("--prefix", default="", help="Optional key prefix.")

    download_parser = commands.add_parser(
        "download", help="Download an object from the bucket."
    )
    download_parser.add_argument("object_key")
    download_parser.add_argument("--output", help="Local destination path.")

    read_parser = commands.add_parser(
        "read", help="Read a UTF-8 text object in the terminal."
    )
    read_parser.add_argument("object_key")
    read_parser.add_argument("--encoding", default="utf-8")

    delete_parser = commands.add_parser("delete", help="Delete an object.")
    delete_parser.add_argument("object_key")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        bucket = get_bucket_name()
        s3 = create_s3_client()

        if args.command == "test":
            test_connection(s3, bucket)
        elif args.command == "upload":
            upload_file(s3, bucket, args.local_path, args.key)
        elif args.command == "list":
            list_files(s3, bucket, args.prefix)
        elif args.command == "download":
            download_file(s3, bucket, args.object_key, args.output)
        elif args.command == "read":
            read_text_file(s3, bucket, args.object_key, args.encoding)
        elif args.command == "delete":
            delete_file(s3, bucket, args.object_key)

        return 0

    except FileNotFoundError as exc:
        print(f"File error: {exc}", file=sys.stderr)
    except EndpointConnectionError as exc:
        print(
            "Could not connect to Backblaze. Check your internet connection, "
            "endpoint URL, DNS, firewall, and proxy settings.\n"
            f"Details: {exc}",
            file=sys.stderr,
        )
    except SSLError as exc:
        print(
            "TLS/SSL connection failed. Check your system clock, proxy, "
            f"and network inspection settings.\nDetails: {exc}",
            file=sys.stderr,
        )
    except ClientError as exc:
        error = exc.response.get("Error", {})
        print(
            f'Backblaze returned {error.get("Code", "ClientError")}: '
            f'{error.get("Message", str(exc))}',
            file=sys.stderr,
        )
        print(
            "Check that the Application Key belongs to this account, has "
            "access to this bucket, and permits list/read/write as required.",
            file=sys.stderr,
        )
    except BotoCoreError as exc:
        print(f"AWS S3 SDK error: {exc}", file=sys.stderr)
    except (RuntimeError, ValueError) as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
