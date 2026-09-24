from django.conf import settings
from django.urls import re_path
from django.utils.translation import gettext_lazy as _

from temba.contacts.models import URN

from ...models import ChannelType
from .client import WuzapiClient
from .views import ClaimView, ConnectView, DisconnectView, PairView, StatusView

CONFIG_URL = "wuzapi_url"
CONFIG_TOKEN = "wuzapi_token"
CONFIG_HMAC_KEY = "hmac_key"


class WuzapiType(ChannelType):
    """
    A WhatsApp channel through Wuzapi, a bridge that links a phone's WhatsApp account and exposes it over HTTP. The
    bridge runs next to courier, which is why webhooks go to a local courier URL rather than the brand domain.
    """

    code = "WZ"
    name = "WhatsApp (Wuzapi)"
    category = ChannelType.Category.SOCIAL_MEDIA
    schemes = [URN.WHATSAPP_SCHEME]
    async_activation = False

    claim_blurb = _("Connect a WhatsApp account through a Wuzapi bridge running alongside this workspace.")
    claim_view = ClaimView

    menu_items = [
        dict(label=_("Connection"), view_name="channels.types.wuzapi.connect"),
        dict(label=_("Disconnect"), view_name="channels.types.wuzapi.disconnect"),
    ]

    def get_urls(self):
        return super().get_urls() + [
            re_path(r"^connect/(?P<uuid>[a-z0-9\-]+)/$", ConnectView.as_view(channel_type=self), name="connect"),
            re_path(r"^status/(?P<uuid>[a-z0-9\-]+)/$", StatusView.as_view(channel_type=self), name="status"),
            re_path(r"^pair/(?P<uuid>[a-z0-9\-]+)/$", PairView.as_view(channel_type=self), name="pair"),
            re_path(
                r"^disconnect/(?P<uuid>[a-z0-9\-]+)/$", DisconnectView.as_view(channel_type=self), name="disconnect"
            ),
        ]

    def activate(self, channel):
        """
        Points the bridge at courier for this channel and gives it the key it signs webhooks with. Raises if the
        bridge can't be configured, so the claim fails rather than leaving a channel that never receives.
        """
        client = self.get_client(channel)
        client.set_webhook(self.courier_receive_url(channel))
        client.set_hmac_key(channel.config[CONFIG_HMAC_KEY])

    def deactivate(self, channel):
        self.get_client(channel).logout()

    @staticmethod
    def get_client(channel) -> WuzapiClient:
        return WuzapiClient(channel.config[CONFIG_URL], channel.config[CONFIG_TOKEN])

    @staticmethod
    def courier_receive_url(channel) -> str:
        return f"{settings.WUZAPI_COURIER_URL.rstrip('/')}/c/wz/{channel.uuid}/receive"
