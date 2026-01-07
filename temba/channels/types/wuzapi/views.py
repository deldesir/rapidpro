import base64
import hashlib
import hmac
import json
import logging
import mimetypes
import os
import requests
import sys
import time
from uuid import uuid4

from django import forms
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.crypto import get_random_string
from django.utils.decorators import method_decorator
from django.utils.translation import gettext_lazy as _
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import View

from temba.channels.models import Channel
from temba.channels.views import ClaimViewMixin
from temba.contacts.models import Contact, URN
from temba.msgs.models import Msg
from temba.orgs.views.mixins import OrgPermsMixin
from smartmin.views import SmartFormView

def get_server_ip():
    """Detects the primary IP address of the server."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # doesn't even have to be reachable
        s.connect(('10.255.255.255', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP

logger = logging.getLogger(__name__)

class ClaimView(ClaimViewMixin, SmartFormView):
    class ClaimForm(ClaimViewMixin.Form):
        wuzapi_url = forms.CharField(
            label=_("Wuzapi URL"),
            initial="http://localhost:8095",
            help_text=_("The URL where the Wuzapi service is running.")
        )
        wuzapi_token = forms.CharField(
            label=_("Access Token"),
            required=False,
            help_text=_("The access token. Leave blank to generate a new user automatically.")
        )
        phone_number = forms.CharField(
            label=_("Phone Number"),
            help_text=_("The phone number associated with this Wuzapi instance (e.g. 50937000000).")
        )

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            from django.conf import settings
            if getattr(settings, "WUZAPI_ADMIN_TOKEN", None):
                self.fields["wuzapi_token"].widget = forms.HiddenInput()
                self.fields["wuzapi_token"].label = ""
                self.fields["wuzapi_token"].help_text = ""

    title = _("Connect Wuzapi")
    form_class = ClaimForm
    permission = "channels.channel_claim"
    success_url = "uuid@wuzapi.connect"

    def form_valid(self, form):
        user = self.request.user
        org = self.request.org
        data = form.cleaned_data
        
        channel_type = self.channel_type
        address = data["phone_number"]
        wuzapi_url = data["wuzapi_url"].rstrip('/')
        token = data["wuzapi_token"]

        # If token is missing, try to create a new user using the Admin API
        if not token:
            admin_token = getattr(settings, "WUZAPI_ADMIN_TOKEN", None)
            
            if admin_token:
                try:
                    # Create unique username based on org and user
                    username = f"rp_{org.id}_{user.id}_{address}_{int(time.time())}"
                    new_token = f"tk_{org.id}_{user.id}_{address}_{int(time.time())}"
                    
                    # Wuzapi endpoint to add user
                    resp = requests.post(
                        f"{wuzapi_url}/admin/users",
                        json={
                            "name": username, 
                            "token": new_token,
                            "events": "Message,ReadReceipt"
                        },
                        headers={"Authorization": admin_token, "Content-Type": "application/json"},
                        timeout=10
                    )
                    resp.raise_for_status()
                    token = new_token
                    
                except Exception as e:
                    logger.error(f"Failed to create Wuzapi user: {e}")
                    form.add_error(None, _("Failed to auto-create Wuzapi user. Please provide a token manually."))
                    return self.form_invalid(form)
            else:
                form.add_error("wuzapi_token", _("Admin token not configured. Please provide a token manually."))
                return self.form_invalid(form)
        
        # Safe to generate HMAC key
        hmac_key = get_random_string(32)

        # Native Wuzapi Channel (Go Handler)
        channel_type = self.channel_type

        # Configure Courier for Wuzapi (Native)
        # We only need the wuzapi-specific keys. The "WZ" handler in Courier knows what to do.
        config = {
            "wuzapi_url": wuzapi_url,
            "wuzapi_token": token,
            "hmac_key": hmac_key,
        }
        
        try:
            # Create the channel
            self.object = Channel.create(
                org=org,
                user=user,
                country=None,
                channel_type=channel_type,
                address=address,
                config=config,
                role=Channel.ROLE_SEND + Channel.ROLE_RECEIVE,
                schemes=[URN.WHATSAPP_SCHEME]
            )
            logger.info(f"Wuzapi Channel created (Native): {self.object.uuid}")
            
            # Auto-configure Wuzapi webhook
            # Point to Courier: /c/wz/{uuid}/receive
            # Use localhost for native same-machine setup
            scheme = getattr(settings, 'ACCOUNT_DEFAULT_HTTP_PROTOCOL', 'http')
            server_ip = '127.0.0.1'
            
            webhook_url = f"{scheme}://{server_ip}:8080/c/wz/{self.object.uuid}/receive"
            wuzapi_endpoint = f"{wuzapi_url}/webhook"

            try:
                # Configure webhook with explicit event subscription
                response = requests.post(
                    wuzapi_endpoint,
                    json={
                        "webhookurl": webhook_url,
                        "events": ["Message", "ReadReceipt"]
                    },
                    headers={"Authorization": token, "Content-Type": "application/json"},
                    timeout=10
                )
                response.raise_for_status()

                # Configure HMAC
                hmac_endpoint = f"{wuzapi_url}/session/hmac/config"
                hmac_resp = requests.post(
                     hmac_endpoint,
                     json={"hmac_key": hmac_key},
                     headers={"Authorization": token, "Content-Type": "application/json"},
                     timeout=10
                )
                hmac_resp.raise_for_status()

            except Exception as e:
                logger.error(f"Failed to auto-configure Wuzapi webhook or HMAC: {e}")

        except Exception as e:
            logger.exception(f"Error creating Wuzapi channel: {e}")
            form.add_error(None, f"Internal Error: {e}")
            return self.form_invalid(form)

        
        redirect_url = self.get_success_url()
        
        # Handle AJAX requests (RapidPro uses AJAX forms)
        if self.request.META.get('HTTP_X_REQUESTED_WITH') == 'XMLHttpRequest':
             return HttpResponse(json.dumps({'status': 302, 'location': redirect_url}), content_type='application/json')
        
        return HttpResponseRedirect(redirect_url)

    def get_success_url(self):
        # Use simple URL resolution
        slug = self.channel_type.slug
        return reverse(f"channels.types.{slug}.connect", args=[self.object.uuid])

class ConnectWuzapiView(OrgPermsMixin, SmartFormView):
    class ConnectForm(forms.Form):
        pass  # Just a button to finish or re-check

    title = _("Scan QR Code")
    form_class = ConnectForm
    template_name = "channels/types/wuzapi/connect.html"
    permission = "channels.channel_claim"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        channel = get_object_or_404(Channel, uuid=self.kwargs['uuid'], org=self.request.org)
        config = channel.config
        
        wuzapi_url = config.get("wuzapi_url")
        token = config.get("wuzapi_token")
        hmac_key = config.get("hmac_key")
        
        qr_code = None
        pairing_code = None
        status = "unknown"
        
        if wuzapi_url and token:
            try:
                # Point to Courier: /c/wz/{uuid}/receive
                # Use localhost since user is running natively on the same machine.
                # This avoids firewall/DNS issues with interface IPs.
                scheme = getattr(settings, 'ACCOUNT_DEFAULT_HTTP_PROTOCOL', 'http')
                server_ip = '127.0.0.1'
                
                webhook_url = f"{scheme}://{server_ip}:8080/c/wz/{channel.uuid}/receive"
                
                # Update Webhook (non-blocking ideally, but short timeout)
                try:
                    requests.post(
                        f"{wuzapi_url}/webhook",
                        json={
                            "webhookurl": webhook_url,
                            "events": ["Message", "ReadReceipt"]
                        },
                        headers={"Authorization": token, "Content-Type": "application/json"},
                        timeout=2
                    )
                except Exception:
                     pass # Webhook update is best-effort

                # Self-Heal HMAC Key if missing
                if not hmac_key:
                    hmac_key = get_random_string(32)
                    channel.config["hmac_key"] = hmac_key
                    channel.save(update_fields=["config"])
                    logger.info(f"Generated missing HMAC key for channel {channel.uuid}")

                if hmac_key:
                    try:
                        requests.post(
                             f"{wuzapi_url}/session/hmac/config",
                             json={"hmac_key": hmac_key},
                             headers={"Authorization": token, "Content-Type": "application/json"},
                             timeout=2
                        )
                    except Exception:
                        pass # HMAC config is best-effort
            except Exception as e:
                logger.warning(f"Failed to auto-repair Wuzapi webhook: {e}")

             # Check status
            try:
                status_resp = requests.get(
                    f"{wuzapi_url}/session/status",
                    headers={"Authorization": token},
                    timeout=2
                )
                if status_resp.status_code == 200:
                    data = status_resp.json().get('data', {})
                    
                    if data.get("loggedIn"):
                        status = "connected"
                    elif data.get("connected"):
                        status = "scancode"
                    else:
                        status = "connecting"
            except Exception as e:
                logger.debug(f"Wuzapi status check failed: {e}")

            # Fetch QR if not connected
            if status != "connected":
                try:
                    # Ensure session is connected first
                    requests.post(f"{wuzapi_url}/session/connect", headers={"Authorization": token}, json={}, timeout=2)
                    
                    qr_resp = requests.get(
                        f"{wuzapi_url}/session/qr",
                        headers={"Authorization": token},
                        timeout=2
                    )
                    if qr_resp.status_code == 200:
                        qr_data = qr_resp.json().get('data', {})
                        qr_code = qr_data.get("QRCode")

                    # Also try to get pairing code
                    pair_resp = requests.post(
                        f"{wuzapi_url}/session/pairphone",
                        headers={"Authorization": token},
                        json={"phone": channel.address},
                        timeout=2
                    )
                    if pair_resp.status_code == 200:
                        pair_json = pair_resp.json()
                        pairing_code = pair_json.get("LinkingCode") or pair_json.get("data", {}).get("LinkingCode")

                except Exception as e:
                    logger.debug(f"Wuzapi QR/Price check failed: {e}")

        context['channel'] = channel
        context['qr_code'] = qr_code
        context['pairing_code'] = pairing_code
        context['status'] = status
        return context

    def form_valid(self, form):
        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
         from django.urls import reverse
         # Redirect to the main channel dashboard/read view
         # Note: 'channels.channel_read' is the standard view name for seeing channel details
         return reverse("channels.channel_read", args=[self.kwargs['uuid']])

class DashboardWuzapiView(OrgPermsMixin, View):
    permission = "channels.channel_read"
    
    def get(self, request, *args, **kwargs):
        channel = get_object_or_404(Channel, uuid=kwargs['uuid'], org=request.org)
        config = channel.config
        wuzapi_url = config.get("wuzapi_url")
        
        if not wuzapi_url:
             return HttpResponse("Wuzapi URL not configured", status=400)
             
        # Construct dashboard URL (assuming /wuzapi/dashboard/ standard path)
        dashboard_url = f"{wuzapi_url}/dashboard/"
        return HttpResponseRedirect(dashboard_url)

class LogoutWuzapiView(OrgPermsMixin, SmartFormView):
    class LogoutForm(forms.Form):
        pass # Confirmation button

    title = _("Disconnect Session")
    form_class = LogoutForm
    permission = "channels.channel_update"
    
    def form_valid(self, form):
        channel = get_object_or_404(Channel, uuid=self.kwargs['uuid'], org=self.request.org)
        config = channel.config
        wuzapi_url = config.get("wuzapi_url")
        token = config.get("wuzapi_token")
        
        if wuzapi_url and token:
            try:
                requests.post(
                    f"{wuzapi_url}/session/logout",
                    headers={"Authorization": token},
                    timeout=5
                )
                logger.info(f"Wuzapi session logged out for channel {channel.uuid}")
            except Exception as e:
                logger.error(f"Failed to logout Wuzapi session: {e}")
                # Don't block the UI flow, just log it
                
        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        channel = get_object_or_404(Channel, uuid=self.kwargs['uuid'], org=self.request.org)
        slug = Channel.get_type_from_code(channel.channel_type).slug
        return reverse(f"channels.types.{slug}.connect", args=[self.kwargs['uuid']])


class WuzapiStatusView(OrgPermsMixin, View):
    """
    Lightweight endpoint for polling Wuzapi status/QR code.
    Returns JSON: { "status": "connected"|"scancode"|"connecting", "qr": "base64...", "pairing_code": "..." }
    """
    permission = "channels.channel_claim"

    def get(self, request, *args, **kwargs):
        try:
            channel = get_object_or_404(Channel, uuid=kwargs['uuid'], org=request.org)
            config = channel.config
            wuzapi_url = config.get("wuzapi_url")
            token = config.get("wuzapi_token")

            if not wuzapi_url or not token:
                return HttpResponse(json.dumps({"error": "Configuration missing"}), content_type="application/json", status=400)

            status = "unknown"
            qr_code = None
            pairing_code = None

            # 1. Check Status
            try:
                status_resp = requests.get(
                    f"{wuzapi_url}/session/status",
                    headers={"Authorization": token},
                    timeout=3
                )
                if status_resp.status_code == 200:
                    data = status_resp.json().get('data', {})
                    if data.get("loggedIn"):
                        status = "connected"
                    elif data.get("connected"):
                        status = "scancode"
                    else:
                        status = "connecting"
            except Exception:
                pass # Fail silently, keep status as unknown

            # 2. Get QR/Code if needed
            if status == "scancode":
                try:
                    # Refresh QR
                    qr_resp = requests.get(
                        f"{wuzapi_url}/session/qr",
                        headers={"Authorization": token},
                        timeout=3
                    )
                    if qr_resp.status_code == 200:
                        qr_data = qr_resp.json().get('data', {})
                        qr_code = qr_data.get("QRCode")

                    # Refresh Pairing Code
                    pair_resp = requests.post(
                        f"{wuzapi_url}/session/pairphone",
                        headers={"Authorization": token},
                        json={"phone": channel.address},
                        timeout=3
                    )
                    if pair_resp.status_code == 200:
                        pair_json = pair_resp.json()
                        pairing_code = pair_json.get("LinkingCode") or pair_json.get("data", {}).get("LinkingCode")
                except Exception:
                    pass

            return HttpResponse(json.dumps({
                "status": status,
                "qr_code": qr_code,
                "pairing_code": pairing_code
            }), content_type="application/json")

        except Exception as e:
            logger.error(f"WuzapiStatusView error: {e}")
            return HttpResponse(json.dumps({"error": str(e)}), content_type="application/json", status=500)
