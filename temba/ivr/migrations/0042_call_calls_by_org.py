from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models
from django.db.migrations.operations.models import AddIndex


class AddIndexConcurrentlyPlainReverse(AddIndexConcurrently):
    """
    Adds the index concurrently but reverses with a plain drop, so that migration tests - which roll the graph
    backwards inside a transaction - can unapply it.
    """

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        AddIndex.database_backwards(self, app_label, schema_editor, from_state, to_state)


class Migration(migrations.Migration):
    # the calls list pages by uuid (time ordered, as call uuids are v7) so that a page is an index-ordered read with
    # no tiebreak, the same as message folders. Created concurrently so the build doesn't hold ACCESS EXCLUSIVE on
    # the calls table. Installations large enough to care can build it by hand ahead of the deploy and fake this
    # migration:
    #
    #   CREATE INDEX CONCURRENTLY calls_by_org ON ivr_call (org_id, uuid DESC);
    #
    atomic = False

    dependencies = [
        ("ivr", "0041_alter_call_id"),
    ]

    operations = [
        AddIndexConcurrentlyPlainReverse(
            model_name="call",
            index=models.Index(name="calls_by_org", fields=["org", "-uuid"]),
        ),
    ]
