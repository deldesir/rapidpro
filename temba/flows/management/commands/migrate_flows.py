import itertools
import time
import traceback

from packaging.version import Version

from django.core.management.base import BaseCommand

from temba.flows.models import Flow


class Command(BaseCommand):
    help = "Migrates forward all flows which are not current version."

    def add_arguments(self, parser):
        parser.add_argument(
            "--delay",
            type=int,
            action="store",
            dest="delay_ms",
            help="Delay in milliseconds between flow migrations",
            default=100,
        )
        parser.add_argument(
            "--noinput", "--no-input", action="store_false", dest="interactive", help="Do not prompt for confirmation."
        )

    def handle(self, delay_ms: int, interactive: bool, *args, **options):
        self.migrate_flows(delay_ms, interactive)

    def migrate_flows(self, delay_ms: int, interactive: bool):
        # flows can be saved at a newer spec version than ours so need to compare versions rather than just exclude
        current = Version(Flow.CURRENT_SPEC_VERSION)
        flow_ids = [
            flow_id
            for flow_id, version_number in Flow.objects.filter(is_active=True, org__is_active=True)
            .exclude(version_number=Flow.CURRENT_SPEC_VERSION)
            .order_by("org_id", "id")
            .values_list("id", "version_number")
            if Version(version_number) < current
        ]
        total = len(flow_ids)

        if total == 0:
            self.stdout.write("All flows up to date")
            return

        self.stdout.write(f"Found {total} flows to migrate")

        if interactive and input("Continue? [y/N]: ") != "y":
            return

        num_updated = 0
        num_errored = 0

        for id_batch in itertools.batched(flow_ids, 100):
            for flow in Flow.objects.filter(id__in=id_batch):
                try:
                    flow.ensure_current_version()
                    num_updated += 1
                except Exception:
                    self.stderr.write(f"Unable to migrate flow {str(flow.uuid)}:")
                    self.stderr.write(traceback.format_exc())
                    num_errored += 1

                time.sleep(delay_ms / 1000.0)  # don't DDOS mailroom

            self.stdout.write(f" > Flows migrated: {num_updated} of {total} ({num_errored} errored)")
