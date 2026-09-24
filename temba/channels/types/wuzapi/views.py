import re

from smartmin.views import SmartFormView, SmartModelActionView

from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.urls import reverse
from django.utils.crypto import get_random_string
from django.utils.translation import gettext_lazy as _

from temba.orgs.views.mixins import OrgObjPermsMixin

from ...models import Channel
from ...views import ChannelTypeMixin, ClaimViewMixin
from .client import WuzapiClient, WuzapiError

# how the connect page describes the bridge's session to the browser
STATUS_STARTING = "starting"  # the bridge is connecting to WhatsApp
STATUS_PAIRING = "pairing"  # connected, waiting for a phone to scan the QR code or enter a code
STATUS_CONNECTED = "connected"  # a phone is linked


class ClaimView(ClaimViewMixin, SmartFormView):
    class Form(ClaimViewMixin.Form):
        wuzapi_url = forms.CharField(
            label=_("Bridge URL"),
            help_text=_("Where the Wuzapi bridge is listening, as seen from this server."),
        )
        wuzapi_token = forms.CharField(
            label=_("Bridge user token"),
            required=False,
            help_text=_("The token of an existing bridge user. Leave blank to have one created for this channel."),
        )
        phone_number = forms.CharField(
            label=_("Phone number"),
            help_text=_("The WhatsApp number the bridge will link, with country code, e.g. 12065551212."),
        )

        def __init__(self, **kwargs):
            super().__init__(**kwargs)

            self.fields["wuzapi_url"].initial = settings.WUZAPI_URL

            # without an admin token the bridge user can't be created here, so the token becomes mandatory
            if not settings.WUZAPI_ADMIN_TOKEN:
                self.fields["wuzapi_token"].required = True
                self.fields["wuzapi_token"].help_text = _("The token of a user on the bridge.")

        def clean_wuzapi_url(self):
            return self.cleaned_data["wuzapi_url"].strip().rstrip("/")

        def clean_phone_number(self):
            digits = re.sub(r"\D", "", self.cleaned_data["phone_number"])
            if not 8 <= len(digits) <= 15:
                raise ValidationError(_("Enter the number with its country code, digits only."))

            for channel in Channel.objects.filter(
                org=self.request.org, is_active=True, channel_type=self.channel_type.code
            ):
                if channel.address == digits:
                    raise ValidationError(_("A channel for this number already exists in this workspace."))

            return digits

    form_class = Form

    def form_valid(self, form):
        org = self.request.org
        url = form.cleaned_data["wuzapi_url"]
        token = form.cleaned_data["wuzapi_token"]
        address = form.cleaned_data["phone_number"]

        try:
            if not token:
                token = get_random_string(40)
                WuzapiClient.create_user(url, settings.WUZAPI_ADMIN_TOKEN, name=f"{org.id}-{address}", token=token)

            self.object = Channel.create(
                org,
                self.request.user,
                None,
                self.channel_type,
                name=address,
                address=address,
                config={"wuzapi_url": url, "wuzapi_token": token, "hmac_key": get_random_string(48)},
            )
        except WuzapiError as e:
            form.add_error(None, _("Unable to set up the bridge: %(error)s") % {"error": e})
            return self.form_invalid(form)

        return super().form_valid(form)

    def get_success_url(self):
        return reverse("channels.types.wuzapi.connect", args=[self.object.uuid])


class ChannelActionMixin(ChannelTypeMixin, OrgObjPermsMixin):
    """
    Base for the views that act on an existing channel of this type
    """

    model = Channel
    slug_url_kwarg = "uuid"
    fields = ()

    def get_queryset(self):
        return Channel.objects.filter(channel_type=self.channel_type.code, is_active=True)

    def derive_menu_path(self):
        return f"/settings/channels/{self.get_object().uuid}"

    def get_client(self) -> WuzapiClient:
        return self.channel_type.get_client(self.get_object())


class ConnectView(ChannelActionMixin, SmartModelActionView, SmartFormView):
    """
    Shows the link state of the bridge's session and, until a phone is linked, the QR code to scan. The page polls
    the status view; a submit is just a refresh.
    """

    class Form(forms.Form):
        pass

    form_class = Form
    permission = "channels.channel_claim"
    template_name = "channels/types/wuzapi/connect.html"
    title = _("Connect WhatsApp")
    success_url = "uuid@channels.types.wuzapi.connect"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["status_url"] = reverse("channels.types.wuzapi.status", args=[self.object.uuid])
        context["pair_url"] = reverse("channels.types.wuzapi.pair", args=[self.object.uuid])
        context["disconnect_url"] = reverse("channels.types.wuzapi.disconnect", args=[self.object.uuid])
        return context

    def execute_action(self):
        pass


class StatusView(ChannelActionMixin, SmartModelActionView):
    """
    JSON for the connect page: the session's state and, while pairing, the current QR code. Starts the session if
    the bridge isn't connected to WhatsApp yet.
    """

    permission = "channels.channel_claim"
    http_method_names = ["get"]

    def get(self, request, *args, **kwargs):
        client = self.get_client()

        try:
            connected, logged_in = client.status()
            if logged_in:
                return JsonResponse({"status": STATUS_CONNECTED})
            if connected:
                return JsonResponse({"status": STATUS_PAIRING, "qr_code": client.qr_code()})

            client.connect()
            return JsonResponse({"status": STATUS_STARTING})
        except WuzapiError as e:
            return JsonResponse({"error": str(e)}, status=502)


class PairView(ChannelActionMixin, SmartModelActionView):
    """
    Asks WhatsApp for a linking code for the channel's number. Only ever called from the connect page's button,
    because every request makes the phone show a prompt.
    """

    permission = "channels.channel_claim"
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        try:
            code = self.get_client().pair_phone(self.get_object().address)
        except WuzapiError as e:
            return JsonResponse({"error": str(e)}, status=502)

        if not code:
            return JsonResponse({"error": str(_("The bridge didn't return a code, try again."))}, status=502)

        return JsonResponse({"code": code})


class DisconnectView(ChannelActionMixin, SmartModelActionView, SmartFormView):
    """
    Logs the bridge's session out so the phone is unlinked; the channel stays and can be linked again
    """

    class Form(forms.Form):
        pass

    form_class = Form
    permission = "channels.channel_update"
    template_name = "channels/types/wuzapi/disconnect.html"
    title = _("Disconnect WhatsApp")
    submit_button_name = _("Disconnect")
    success_url = "uuid@channels.types.wuzapi.connect"

    def execute_action(self):
        self.get_client().logout()
