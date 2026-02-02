import base64
import hashlib
import hmac
import json
import logging
import mimetypes
import os
import requests
import sys
import socket
import time
from uuid import uuid4

from django import forms
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.http import HttpResponse, HttpResponseRedirect
from django.urls import reverse
from django.utils.crypto import get_random_string
from django.utils.decorators import method_decorator
from django.utils.translation import gettext_lazy as _
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import View

from temba.channels.models import Channel
from temba.channels.views import ClaimViewMixin
from temba.contacts.models import Contact, URN
from temba import mailroom
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
        openclaw_url = forms.CharField(
            label=_("OpenClaw URL"),
            initial="http://localhost:3030",
            help_text=_("The URL where the OpenClaw service is running.")
        )
        openclaw_token = forms.CharField(
            label=_("Access Token"),
            required=False,
            help_text=_("The access token. Leave blank to generate a new user automatically.")
        )
        phone_number = forms.CharField(
            label=_("Phone Number"),
            help_text=_("The phone number associated with this OpenClaw instance (e.g. 50937000000).")
        )

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            from django.conf import settings
            if getattr(settings, "OPENCLAW_ADMIN_TOKEN", None):
                self.fields["openclaw_token"].widget = forms.HiddenInput()
                self.fields["openclaw_token"].label = ""
                self.fields["openclaw_token"].help_text = ""

    title = _("Connect OpenClaw")
    form_class = ClaimForm
    permission = "channels.channel_claim"
    success_url = "uuid@openclaw.connect"

    def form_valid(self, form):
        user = self.request.user
        org = self.request.org
        data = form.cleaned_data
        
        channel_type = self.channel_type
        address = data["phone_number"]
        openclaw_url = data["openclaw_url"].rstrip('/')
        token = data["openclaw_token"]

        # If token is missing, try to create a new user using the Admin API
        if not token:
            admin_token = getattr(settings, "OPENCLAW_ADMIN_TOKEN", None)
            
            if admin_token:
                try:
                    # Create unique username based on org and user
                    username = f"rp_{org.id}_{user.id}_{address}_{int(time.time())}"
                    new_token = f"tk_{org.id}_{user.id}_{address}_{int(time.time())}"
                    
                    # OpenClaw endpoint to add user
                    resp = requests.post(
                        f"{openclaw_url}/admin/users",
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
                    logger.error(f"Failed to create OpenClaw user: {e}")
                    form.add_error(None, _("Failed to auto-create OpenClaw user. Please provide a token manually."))
                    return self.form_invalid(form)
            else:
                form.add_error("openclaw_token", _("Admin token not configured. Please provide a token manually."))
                return self.form_invalid(form)
        
        # Safe to generate HMAC key
        hmac_key = get_random_string(32)

        # Native OpenClaw Channel (Go Handler)
        channel_type = self.channel_type

        # Configure Courier for OpenClaw (Native)
        # We only need the openclaw-specific keys. The "OC" handler in Courier knows what to do.
        config = {
            "openclaw_url": openclaw_url,
            "openclaw_token": token,
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
            logger.info(f"OpenClaw Channel created (Native): {self.object.uuid}")
            
            # Auto-configure OpenClaw webhook
            # Point to Courier: /c/oc/{uuid}/receive
            # Use localhost for native same-machine setup
            scheme = getattr(settings, 'ACCOUNT_DEFAULT_HTTP_PROTOCOL', 'http')
            server_ip = '127.0.0.1'
            
            webhook_url = f"{scheme}://{server_ip}:8080/c/oc/{self.object.uuid}/receive"
            openclaw_endpoint = f"{openclaw_url}/webhook"

            try:
                # Configure webhook with explicit event subscription
                response = requests.post(
                    openclaw_endpoint,
                    json={
                        "webhookurl": webhook_url,
                        "events": ["Message", "ReadReceipt"]
                    },
                    headers={"Authorization": token, "Content-Type": "application/json"},
                    timeout=10
                )
                response.raise_for_status()

                # Configure HMAC
                hmac_endpoint = f"{openclaw_url}/session/hmac/config"
                hmac_resp = requests.post(
                     hmac_endpoint,
                     json={"hmac_key": hmac_key},
                     headers={"Authorization": token, "Content-Type": "application/json"},
                     timeout=10
                )
                hmac_resp.raise_for_status()

            except Exception as e:
                logger.error(f"Failed to auto-configure OpenClaw webhook or HMAC: {e}")

        except Exception as e:
            logger.exception(f"Error creating OpenClaw channel: {e}")
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

class ConnectOpenClawView(OrgPermsMixin, SmartFormView):
    class ConnectForm(forms.Form):
        pass  # Just a button to finish or re-check

    title = _("Scan QR Code")
    form_class = ConnectForm
    template_name = "channels/types/openclaw/connect.html"
    permission = "channels.channel_claim"

    def get_context_data(self, **kwargs):
        # Ensure self.object is set for SmartView methods
        self.object = Channel.objects.get(uuid=self.kwargs['uuid'], org=self.request.org)
        
        context = super().get_context_data(**kwargs)
        channel = self.object
        config = channel.config
        
        
        context = super().get_context_data(**kwargs)
        channel = self.object
        config = channel.config

        
        openclaw_url = config.get("openclaw_url")
        token = config.get("openclaw_token")
        hmac_key = config.get("hmac_key")
        
        qr_code = None
        pairing_code = None
        status = "unknown"
        
        if openclaw_url and token:
            try:
                # Point to Courier: /c/oc/{uuid}/receive
                # Use localhost since user is running natively on the same machine.
                # This avoids firewall/DNS issues with interface IPs.
                # Use local IP detection
                scheme = getattr(settings, 'ACCOUNT_DEFAULT_HTTP_PROTOCOL', 'http')
                server_ip = get_server_ip()
                
                webhook_url = f"{scheme}://{server_ip}:8080/c/oc/{channel.uuid}/receive"
                
                # Update Webhook (non-blocking ideally, but short timeout)
                # Update Webhook (non-blocking ideally, but short timeout)
                try:
                    requests.post(
                        f"{openclaw_url}/webhook",
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
                             f"{openclaw_url}/session/hmac/config",
                             json={"hmac_key": hmac_key},
                             headers={"Authorization": token, "Content-Type": "application/json"},
                             timeout=2
                        )
                    except Exception:
                        pass # HMAC config is best-effort
            
                    
                # Check status
                try:
                    status_resp = requests.get(
                        f"{openclaw_url}/session/status",
                        headers={"Authorization": token},
                        timeout=2
                    )
                    if status_resp.status_code == 200:
                        data = status_resp.json().get('data', {})
                        
                        if is_true(data.get("loggedIn")):
                            status = "connected"
                        elif is_true(data.get("connected")):
                            status = "scancode"
                        else:
                            status = "connecting"
                except Exception as e:
                    logger.debug(f"OpenClaw status check failed: {e}")

                # Fetch QR if not connected
                if status != "connected":
                    try:
                        # Ensure session is connected first
                        requests.post(f"{openclaw_url}/session/connect", headers={"Authorization": token}, json={}, timeout=2)
                        
                        qr_resp = requests.get(
                            f"{openclaw_url}/session/qr",
                            headers={"Authorization": token},
                            timeout=2
                        )
                        if qr_resp.status_code == 200:
                            qr_data = qr_resp.json().get('data', {})
                            qr_code = qr_data.get("QRCode")

                        # Also try to get pairing code
                        pair_resp = requests.post(
                            f"{openclaw_url}/session/pairphone",
                            headers={"Authorization": token},
                            json={"phone": channel.address},
                            timeout=2
                        )
                        if pair_resp.status_code == 200:
                            pair_json = pair_resp.json()
                            pairing_code = pair_json.get("LinkingCode") or pair_json.get("data", {}).get("LinkingCode")

                    except Exception as e:
                        logger.debug(f"OpenClaw QR/Price check failed: {e}")
    
            except Exception as e:
                logger.error(f"Error updating OpenClaw status: {e}")

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

    def get_cancel_url(self):
        from django.urls import reverse
        return reverse("channels.channel_read", args=[self.kwargs['uuid']])

    def derive_breadcrumbs(self):
        from django.urls import reverse
        # Avoid SmartView auto-generating breadcrumbs for non-existent 'list' view
        return (
            (reverse("orgs.org_home"), _("Home")),
            (reverse("channels.channel_read", args=[self.kwargs['uuid']]), self.object.name),
            (None, _("Connect")),
        )

    def derive_list_url(self):
        from django.urls import reverse
        # Fallback to org home since no channel list exists
        return reverse("orgs.org_home")

class DashboardOpenClawView(OrgPermsMixin, View):
    permission = "channels.channel_read"
    
    def get(self, request, *args, **kwargs):
        channel = Channel.objects.get(uuid=kwargs['uuid'], org=request.org)
        config = channel.config
        openclaw_url = config.get("openclaw_url")
        
        if not openclaw_url:
             return HttpResponse("OpenClaw URL not configured", status=400)
             
        # Construct dashboard URL (assuming /openclaw/dashboard/ standard path)
        dashboard_url = f"{openclaw_url}/dashboard/"
        return HttpResponseRedirect(dashboard_url)

class LogoutOpenClawView(OrgPermsMixin, SmartFormView):
    class LogoutForm(forms.Form):
        pass # Confirmation button

    title = _("Disconnect Session")
    form_class = LogoutForm
    permission = "channels.channel_update"
    submit_button_name = _("Disconnect")

    def get_context_data(self, **kwargs):
        # Ensure object is available for breadcrumbs
        if 'uuid' in self.kwargs:
            self.object = Channel.objects.get(uuid=self.kwargs['uuid'], org=self.request.org)
        return super().get_context_data(**kwargs)

    
    def form_valid(self, form):
        channel = Channel.objects.get(uuid=self.kwargs['uuid'], org=self.request.org)
        config = channel.config
        openclaw_url = config.get("openclaw_url")
        token = config.get("openclaw_token")
        
        if openclaw_url and token:
            try:
                requests.post(
                    f"{openclaw_url}/session/logout",
                    headers={"Authorization": token},
                    timeout=5
                )
                logger.info(f"OpenClaw session logged out for channel {channel.uuid}")
            except Exception as e:
                logger.error(f"Failed to logout OpenClaw session: {e}")
                # Don't block the UI flow, just log it
                
        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        channel = Channel.objects.get(uuid=self.kwargs['uuid'], org=self.request.org)
        slug = Channel.get_type_from_code(channel.channel_type).slug
        return reverse(f"channels.types.{slug}.connect", args=[self.kwargs['uuid']])


class OpenClawStatusView(OrgPermsMixin, View):
    """
    Lightweight endpoint for polling OpenClaw status/QR code.
    Returns JSON: { "status": "connected"|"scancode"|"connecting", "qr": "base64...", "pairing_code": "..." }
    """
    permission = "channels.channel_claim"

    def get(self, request, *args, **kwargs):
        try:
            channel = Channel.objects.get(uuid=kwargs['uuid'], org=request.org)
            config = channel.config
            openclaw_url = config.get("openclaw_url")
            token = config.get("openclaw_token")

            if not openclaw_url or not token:
                return HttpResponse(json.dumps({"error": "Configuration missing"}), content_type="application/json", status=400)

            status = "unknown"
            qr_code = None
            pairing_code = None

            # 1. Check Status
            try:
                status_resp = requests.get(
                    f"{openclaw_url}/session/status",
                    headers={"Authorization": token},
                    timeout=3
                )
                if status_resp.status_code == 200:
                    data = status_resp.json().get('data', {})
                if status_resp.status_code == 200:
                    data = status_resp.json().get('data', {})
                    
                    # Robust boolean check
                    def is_true(val):
                         return str(val).lower() in ("true", "1", "yes", "on")

                    if is_true(data.get("loggedIn")):
                        status = "connected"
                    elif is_true(data.get("connected")):
                        status = "scancode"
                    else:
                        status = "connecting"
            except Exception:
                pass # Fail silently, keep status as unknown

            # 2. Get QR/Code if needed
            if status == "scancode":
                try:
                    # Refresh QR - Only if specifically requested or maybe just rely on session/qr being idempotent-ish
                    # Actually, OpenClaw seems to rotate QR on read. 
                    # Let's throttle it? Or just let it be for now but REMOVE PAIRING CODE.
                    qr_resp = requests.get(
                        f"{openclaw_url}/session/qr",
                        headers={"Authorization": token},
                        timeout=3
                    )
                    if qr_resp.status_code == 200:
                        qr_data = qr_resp.json().get('data', {})
                        qr_code = qr_data.get("QRCode")

                    if request.GET.get("gen_code"):
                         logger.info(f"Generating pairing code for channel {channel.uuid}")
                         try:
                             # Ensure session exists first
                             requests.post(
                                 f"{openclaw_url}/session/connect", 
                                 headers={"Authorization": token}, 
                                 json={}, 
                                 timeout=30
                             )
                             
                             pair_resp = requests.post(
                                  f"{openclaw_url}/session/pairphone",
                                  headers={"Authorization": token},
                                  json={"phone": channel.address},
                                  timeout=30
                             )
                             logger.info(f"Pairing code response: {pair_resp.status_code} {pair_resp.text}")
                             if pair_resp.status_code == 200:
                                  pair_json = pair_resp.json()
                                  pairing_code = pair_json.get("LinkingCode") or pair_json.get("data", {}).get("LinkingCode")
                             else:
                                  logger.error(f"OpenClaw failed to generate code: {pair_resp.text}")
                         except Exception as e:
                             logger.exception(f"Exception calling openclaw pairphone: {e}")
                    else:
                         pairing_code = None

                except Exception as e:
                    logger.debug(f"QR/Pairing check error: {e}")

            return HttpResponse(json.dumps({
                "status": status,
                "qr_code": qr_code,
                "pairing_code": pairing_code
            }), content_type="application/json")

        except Exception as e:
            logger.error(f"OpenClawStatusView error: {e}")
            return HttpResponse(json.dumps({"error": str(e)}), content_type="application/json", status=500)
