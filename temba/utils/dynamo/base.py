from decimal import Rounded

import boto3
from boto3.dynamodb.types import DYNAMODB_CONTEXT
from botocore.client import Config

from django.conf import settings
from django.utils.functional import SimpleLazyObject

_client = None

# monkey patch until https://github.com/boto/boto3/issues/4693 resolved
DYNAMODB_CONTEXT.traps[Rounded] = False


def is_enabled():
    """Returns True if DynamoDB is configured and enabled."""
    return bool(getattr(settings, "DYNAMO_TABLE_PREFIX", ""))


def get_client():
    """
    Returns our shared DynamoDB resource service client, or None if disabled.
    """

    if not is_enabled():
        return None

    global _client

    if not _client:
        if settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY:
            session = boto3.Session(
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                region_name=settings.AWS_REGION,
            )
        else:  # pragma: no cover
            session = boto3.Session()

        _client = session.resource(
            "dynamodb", endpoint_url=settings.DYNAMO_ENDPOINT_URL, config=Config(retries={"max_attempts": 3})
        )

    return _client


def _get_table(suffix):
    client = get_client()
    if client is None:
        return None
    return client.Table(settings.DYNAMO_TABLE_PREFIX + suffix)


MAIN = SimpleLazyObject(lambda: _get_table("Main"))
HISTORY = SimpleLazyObject(lambda: _get_table("History"))
