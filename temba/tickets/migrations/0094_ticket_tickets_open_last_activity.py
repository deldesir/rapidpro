from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    # a plain index build would block writes to the tickets table for its duration, so it's created concurrently
    atomic = False

    dependencies = [
        ("tickets", "0093_audit_fields_cleanup"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="ticket",
            index=models.Index(
                condition=models.Q(("status", "O")),
                fields=["last_activity_on"],
                name="tickets_open_last_activity",
            ),
        ),
    ]
