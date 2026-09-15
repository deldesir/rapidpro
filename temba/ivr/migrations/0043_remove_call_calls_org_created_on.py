from django.contrib.postgres.operations import RemoveIndexConcurrently
from django.db import migrations
from django.db.migrations.operations.models import RemoveIndex


class RemoveIndexConcurrentlyPlainReverse(RemoveIndexConcurrently):
    """
    Removes the index concurrently but reverses with a plain create, so that migration tests - which roll the graph
    backwards inside a transaction - can unapply it.
    """

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        RemoveIndex.database_backwards(self, app_label, schema_editor, from_state, to_state)


class Migration(migrations.Migration):
    # superseded by calls_by_org now that the calls list pages by uuid. Dropped concurrently as a plain drop would
    # hold ACCESS EXCLUSIVE on the calls table while waiting on every in-flight query against it.
    atomic = False

    dependencies = [
        ("ivr", "0042_call_calls_by_org"),
    ]

    operations = [
        RemoveIndexConcurrentlyPlainReverse(model_name="call", name="calls_org_created_on"),
    ]
