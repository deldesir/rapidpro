import threading
from decimal import Rounded

import boto3
from boto3.dynamodb.types import DYNAMODB_CONTEXT
from botocore.client import Config

from django.conf import settings

# boto3 sessions and resources aren't thread-safe, so rather than sharing one module-wide each thread gets its own,
# created lazily on first use and kept for the life of the thread
_local = threading.local()

# monkey patch until https://github.com/boto/boto3/issues/4693 resolved
DYNAMODB_CONTEXT.traps[Rounded] = False


def get_client():
    """
    Returns the DynamoDB resource service client for the current thread
    """

    client = getattr(_local, "client", None)
    if client is None:
        if settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY:
            session = boto3.Session(
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                region_name=settings.AWS_REGION,
            )
        else:  # pragma: no cover
            session = boto3.Session()

        client = _local.client = session.resource(
            "dynamodb", endpoint_url=settings.DYNAMO_ENDPOINT_URL, config=Config(retries={"max_attempts": 3})
        )

    return client


class _Table:
    """
    A stand-in for a table resource which can be imported once but resolves to the current thread's resource on
    each use, since the resource itself can't be shared between threads.
    """

    def __init__(self, suffix: str):
        self._suffix = suffix

    def __getattr__(self, name):
        return getattr(get_client().Table(settings.DYNAMO_TABLE_PREFIX + self._suffix), name)


MAIN = _Table("Main")
HISTORY = _Table("History")
