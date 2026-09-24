from django.core.management import BaseCommand, CommandError

from temba.channels.models import Channel
from temba.channels.types.wuzapi.client import WuzapiError
from temba.channels.types.wuzapi.type import WuzapiType


class Command(BaseCommand):
    help = "Re-registers the courier webhook and signing key with the bridge for every active Wuzapi channel."

    def add_arguments(self, parser):
        parser.add_argument("--channel", help="the UUID of a single channel to re-register")

    def handle(self, channel: str, *args, **options):
        channels = Channel.objects.filter(channel_type=WuzapiType.code, is_active=True).order_by("id")
        if channel:
            channels = channels.filter(uuid=channel)
            if not channels.exists():
                raise CommandError(f"no active Wuzapi channel with UUID {channel}")

        channel_type = WuzapiType()
        for channel in channels:
            try:
                channel_type.activate(channel)
                self.stdout.write(f"{channel.uuid} ({channel.address}): OK")
            except WuzapiError as e:
                self.stdout.write(f"{channel.uuid} ({channel.address}): {e}")
