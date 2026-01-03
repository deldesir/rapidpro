import requests
from django.urls import re_path
from django.utils.translation import gettext_lazy as _
from ...models import ChannelType
from .views import ClaimView, ConnectWuzapiView, WuzapiIncomingView, DashboardWuzapiView, LogoutWuzapiView

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
        dict(label=_("Wuzapi Dashboard"), view_name="channels.types.wuzapi.dashboard"),
        dict(label=_("Disconnect Session"), view_name="channels.types.wuzapi.logout"),
    ]
    
    def get_urls(self):
        return super().get_urls() + [
            re_path(r"^receive/(?P<uuid>[a-z0-9\-]+)/$", WuzapiIncomingView.as_view(), name="receive"),
            re_path(r"^connect/(?P<uuid>[a-z0-9\-]+)/$", ConnectWuzapiView.as_view(), name="connect"),
            re_path(r"^dashboard/(?P<uuid>[a-z0-9\-]+)/$", DashboardWuzapiView.as_view(), name="dashboard"),
            re_path(r"^logout/(?P<uuid>[a-z0-9\-]+)/$", LogoutWuzapiView.as_view(), name="logout"),
        ]
