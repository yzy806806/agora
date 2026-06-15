"""Shared S3 mock fixtures for workspace S3 tests."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_SECURITY_TOKEN", "testing")
os.environ.setdefault("AWS_SESSION_TOKEN", "testing")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

from moto import mock_aws

BUCKET = "test-ws"
ENDPOINT = "http://localhost:5000"


@pytest.fixture()
def aws_mock():
    """Start moto mock S3 and create the test bucket."""
    with mock_aws():
        import boto3
        boto3.client("s3", endpoint_url=ENDPOINT).create_bucket(
            Bucket=BUCKET,
        )
        yield


@pytest.fixture()
def s3() -> "S3Backend":
    from agora.coordinator.workspace.s3_backend import S3Backend
    return S3Backend(
        endpoint_url=ENDPOINT, bucket=BUCKET,
        access_key="testing", secret_key="testing",
    )


@pytest.fixture()
def s3_prefixed() -> "S3Backend":
    from agora.coordinator.workspace.s3_backend import S3Backend
    return S3Backend(
        endpoint_url=ENDPOINT, bucket=BUCKET,
        access_key="testing", secret_key="testing", prefix="my-prefix",
    )
