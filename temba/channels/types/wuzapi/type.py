import requests
from django.urls import re_path
from django.utils.translation import gettext_lazy as _
from ...models import ChannelType
from .views import ClaimView, ConnectWuzapiView, LogoutWuzapiView, WuzapiStatusView

class ChannelError(Exception):
    pass

class WuzapiType(ChannelType):
    """
    Wuzapi WhatsApp integration
    """
    code = "WZ"
    category = ChannelType.Category.PHONE
    category = ChannelType.Category.PHONE
    name = "Wuzapi"
    
    courier_url = r"^c/wz/(?P<uuid>[a-z0-9\-]+)/(?P<action>receive|status)$"
    
    # We don't expose a unified courier URL pattern here because we use a specific view
    # But ChannelType requires get_urls() to return them.
    
    claim_blurb = _("Connect your WhatsApp Business account using Wuzapi.")
    


    claim_view = ClaimView

    menu_items = [
        dict(label=_("Connection Status"), view_name="channels.types.wuzapi.connect"),
        dict(label=_("Disconnect Session"), view_name="channels.types.wuzapi.logout"),
    ]
    
    def get_urls(self):
        return super().get_urls() + [
            re_path(r"^connect/(?P<uuid>[a-z0-9\-]+)/$", ConnectWuzapiView.as_view(), name="connect"),
            re_path(r"^logout/(?P<uuid>[a-z0-9\-]+)/$", LogoutWuzapiView.as_view(), name="logout"),
            re_path(r"^status/(?P<uuid>[a-z0-9\-]+)/$", WuzapiStatusView.as_view(), name="status"),
        ]

    def deactivate(self, channel):
        """
        Called when a channel is released. We should logout the Wuzapi session.
        """
        import logging
        logger = logging.getLogger(__name__)
        
        config = channel.config
        wuzapi_url = config.get("wuzapi_url")
        token = config.get("wuzapi_token")
        
        if wuzapi_url and token:
            try:
                # 1. Logout session
                requests.post(
                    f"{wuzapi_url}/session/logout",
                    headers={"Authorization": token},
                    timeout=5
                )
                logger.info(f"Deactivated Wuzapi channel {channel.uuid}: Session logged out.")
                
                # 2. Attempt to delete user if Admin Token is available (Optional but cleaner)
                from django.conf import settings
                admin_token = getattr(settings, "WUZAPI_ADMIN_TOKEN", None)
                if admin_token:
                    # We need the Wuzapi ID or name. 
                    # ClaimView creates name as: rp_{org.id}_{user.id}_{address}_{timestamp}
                    # We usually don't store the exact name in config, but we have the token.
                    # If we can't find the user by token easily, verifying via /admin/users list might be needed.
                    # For now, logout is the safe/reliable action.
                    pass

            except Exception as e:
                logger.error(f"Error deactivating Wuzapi channel {channel.uuid}: {e}")

# Register Signal to handle Hard Deletes (e.g. from Admin or "Delete" actions that skip release)
from django.db.models.signals import pre_delete
from django.dispatch import receiver
from ...models import Channel

@receiver(pre_delete, sender=Channel, dispatch_uid="wuzapi_channel_delete")
def on_channel_delete(sender, instance, **kwargs):
    if instance.channel_type == WuzapiType.code:
        # We reuse the deactivate logic which performs the safe logout
        # Note: We instantiate WuzapiType or just call the method if it was static, 
        # but here it's an instance method. However, looking at usage in Channel.release:
        # self.type.deactivate(self) -> type is property returning class or instance?
        # Channel.type returns class instance from TYPES dict.
        # So we should get the type instance the same way.
        
        try:
             # Cleanest way is to use the instance's type property if available, 
             # but instance.type accesses self.get_type_from_code. 
             # To avoid side verification effects during delete, let's just use our local class logic.
             # Actually, simpler:
             WuzapiType().deactivate(instance)
        except Exception as e:
             # Don't block deletion
             pass
