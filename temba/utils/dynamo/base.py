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
    each use, since the resource itself can't be shared between threads. The thread's table handles are memoized by
    name alongside its client, so the per-item loops in the query helpers don't rebuild one on every access.
    """

    def __init__(self, suffix: str):
        self._suffix = suffix

    def __getattr__(self, name):
        table_name = settings.DYNAMO_TABLE_PREFIX + self._suffix
        tables = getattr(_local, "tables", None)
        if tables is None:
            tables = _local.tables = {}
        table = tables.get(table_name)
        if table is None:
            table = tables[table_name] = get_client().Table(table_name)
        return getattr(table, name)


MAIN = _Table("Main")
HISTORY = _Table("History")
