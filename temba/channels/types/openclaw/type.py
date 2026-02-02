import requests
from django.urls import re_path
from django.utils.translation import gettext_lazy as _
from ...models import ChannelType
from .views import ClaimView, ConnectOpenClawView, LogoutOpenClawView, OpenClawStatusView

class ChannelError(Exception):
    pass

class OpenClawType(ChannelType):
    """
    OpenClaw WhatsApp integration
    """
    code = "OC"
    category = ChannelType.Category.PHONE
    name = "OpenClaw (WhatsApp)"
    
    courier_url = r"^c/oc/(?P<uuid>[a-z0-9\-]+)/(?P<action>receive|status)$"
    
    # We don't expose a unified courier URL pattern here because we use a specific view
    # But ChannelType requires get_urls() to return them.
    
    claim_blurb = _("Connect your WhatsApp Business account using OpenClaw.")
    
    claim_view = ClaimView

    menu_items = [
        dict(label=_("Connection Status"), view_name="channels.types.openclaw.connect"),
        dict(label=_("Disconnect Session"), view_name="channels.types.openclaw.logout"),
    ]
    
    def get_urls(self):
        return super().get_urls() + [
            re_path(r"^connect/(?P<uuid>[a-z0-9\-]+)/$", ConnectOpenClawView.as_view(), name="connect"),
            re_path(r"^logout/(?P<uuid>[a-z0-9\-]+)/$", LogoutOpenClawView.as_view(), name="logout"),
            re_path(r"^status/(?P<uuid>[a-z0-9\-]+)/$", OpenClawStatusView.as_view(), name="status"),
        ]

    def deactivate(self, channel):
        """
        Called when a channel is released. We should logout the OpenClaw session.
        """
        import logging
        logger = logging.getLogger(__name__)
        
        config = channel.config
        openclaw_url = config.get("openclaw_url")
        token = config.get("openclaw_token")
        
        if openclaw_url and token:
            try:
                # 1. Logout session
                requests.post(
                    f"{openclaw_url}/session/logout",
                    headers={"Authorization": token},
                    timeout=5
                )
                logger.info(f"Deactivated OpenClaw channel {channel.uuid}: Session logged out.")
                
            except Exception as e:
                logger.error(f"Error deactivating OpenClaw channel {channel.uuid}: {e}")

# Register Signal to handle Hard Deletes (e.g. from Admin or "Delete" actions that skip release)
from django.db.models.signals import pre_delete
from django.dispatch import receiver
from ...models import Channel

@receiver(pre_delete, sender=Channel, dispatch_uid="openclaw_channel_delete")
def on_channel_delete(sender, instance, **kwargs):
    if instance.channel_type == OpenClawType.code:
        try:
             OpenClawType().deactivate(instance)
        except Exception as e:
             # Don't block deletion
             pass
