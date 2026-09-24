from django.core.management import BaseCommand
from django.db import connection

# The indexes mailroom's Postgres-backed search relies on when Elasticsearch isn't deployed. They live here rather
# than in migrations because upstream's migration numbering advances every release, and a fork-only migration in the
# same app collides with it at each sync. Every statement is idempotent, so the command runs after every migrate.
STATEMENTS = [
    ("pg_trgm extension", "CREATE EXTENSION IF NOT EXISTS pg_trgm"),
    (
        "contacts_contact_name_trgm_idx",
        "CREATE INDEX IF NOT EXISTS contacts_contact_name_trgm_idx ON contacts_contact USING gin (name gin_trgm_ops)",
    ),
    (
        "msgs_msg.text_search",
        "ALTER TABLE msgs_msg ADD COLUMN IF NOT EXISTS text_search tsvector "
        "GENERATED ALWAYS AS (to_tsvector('simple', text)) STORED",
    ),
    (
        "msgs_msg_text_search_idx",
        "CREATE INDEX IF NOT EXISTS msgs_msg_text_search_idx ON msgs_msg USING gin (text_search)",
    ),
]


class Command(BaseCommand):
    help = "Creates the Postgres indexes used by contact and message search when Elasticsearch isn't deployed."

    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            for label, statement in STATEMENTS:
                cursor.execute(statement)
                self.stdout.write(f"{label}: OK")
