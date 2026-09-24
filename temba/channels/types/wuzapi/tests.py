from unittest.mock import call, patch

from requests import RequestException

from django.core.management import CommandError, call_command
from django.test import override_settings
from django.urls import reverse

from temba.tests import MockJsonResponse, TembaTest
from temba.tests.crudl import CRUDLTestMixin

from ...models import Channel
from .client import WuzapiClient, WuzapiError

BRIDGE = "http://bridge:8095"


def bridge_answers(mock_request, answers: dict):
    """
    Makes the mocked requests.request answer by (method, path), raising for anything unexpected
    """

    def side_effect(method, url, **kwargs):
        answer = answers.get((method, url.replace(BRIDGE, "")))
        if answer is None:
            raise AssertionError(f"unexpected bridge call: {method} {url}")
        if isinstance(answer, Exception):
            raise answer
        return answer

    mock_request.side_effect = side_effect


class WuzapiClientTest(TembaTest):
    @patch("requests.request")
    def test_calls(self, mock_request):
        client = WuzapiClient(BRIDGE + "/", "tok")
        bridge_answers(
            mock_request,
            {
                ("GET", "/session/status"): MockJsonResponse(200, {"data": {"connected": True, "loggedIn": "false"}}),
                ("GET", "/session/qr"): MockJsonResponse(200, {"data": {"QRCode": "data:image/png;base64,QR"}}),
                ("POST", "/session/pairphone"): MockJsonResponse(200, {"data": {"LinkingCode": "ABCD-1234"}}),
                ("POST", "/webhook"): MockJsonResponse(200, {"success": True}),
                ("POST", "/session/hmac/config"): MockJsonResponse(200, {"success": True}),
                ("POST", "/session/connect"): MockJsonResponse(200, {"success": True}),
                ("POST", "/session/logout"): MockJsonResponse(200, {"success": True}),
                ("POST", "/admin/users"): MockJsonResponse(200, {"success": True}),
            },
        )

        self.assertEqual((True, False), client.status())
        self.assertEqual("data:image/png;base64,QR", client.qr_code())
        self.assertEqual("ABCD-1234", client.pair_phone("12065551212"))
        client.set_webhook("http://courier:8080/c/wz/1234/receive")
        client.set_hmac_key("secret")
        client.connect()
        client.logout()
        WuzapiClient.create_user(BRIDGE, "admin-secret", name="1-12065551212", token="newtok")

        auth = {"Authorization": "tok"}
        mock_request.assert_has_calls(
            [
                call("GET", BRIDGE + "/session/status", json=None, headers=auth, timeout=10),
                call("GET", BRIDGE + "/session/qr", json=None, headers=auth, timeout=10),
                call("POST", BRIDGE + "/session/pairphone", json={"Phone": "12065551212"}, headers=auth, timeout=30),
                call(
                    "POST",
                    BRIDGE + "/webhook",
                    json={"webhookurl": "http://courier:8080/c/wz/1234/receive", "events": ["Message", "ReadReceipt"]},
                    headers=auth,
                    timeout=10,
                ),
                call("POST", BRIDGE + "/session/hmac/config", json={"hmac_key": "secret"}, headers=auth, timeout=10),
                call(
                    "POST",
                    BRIDGE + "/session/connect",
                    json={"Subscribe": ["Message", "ReadReceipt"], "Immediate": True},
                    headers=auth,
                    timeout=10,
                ),
                call("POST", BRIDGE + "/session/logout", json=None, headers=auth, timeout=10),
                call(
                    "POST",
                    BRIDGE + "/admin/users",
                    json={"name": "1-12065551212", "token": "newtok", "events": "Message,ReadReceipt"},
                    headers={"Authorization": "admin-secret"},
                    timeout=10,
                ),
            ]
        )

    @patch("requests.request")
    def test_errors(self, mock_request):
        client = WuzapiClient(BRIDGE, "tok")

        mock_request.side_effect = RequestException("connection refused")
        with self.assertRaises(WuzapiError):
            client.status()

        mock_request.side_effect = None
        mock_request.return_value = MockJsonResponse(500, {"error": "no session"})
        with self.assertRaises(WuzapiError):
            client.qr_code()

        mock_request.return_value = MockJsonResponse(200, {"data": {}})
        self.assertEqual("", client.qr_code())
        self.assertEqual("", client.pair_phone("12065551212"))


@override_settings(WUZAPI_URL=BRIDGE, WUZAPI_ADMIN_TOKEN="admin-secret", WUZAPI_COURIER_URL="http://courier:8080/")
class WuzapiTypeTest(TembaTest, CRUDLTestMixin):
    def setUp(self):
        super().setUp()

        self.channel = self.create_channel(
            "WZ",
            "12065551212",
            "12065551212",
            schemes=["whatsapp"],
            config={"wuzapi_url": BRIDGE, "wuzapi_token": "tok", "hmac_key": "k" * 48},
        )
        self.connect_url = reverse("channels.types.wuzapi.connect", args=[self.channel.uuid])
        self.status_url = reverse("channels.types.wuzapi.status", args=[self.channel.uuid])
        self.pair_url = reverse("channels.types.wuzapi.pair", args=[self.channel.uuid])
        self.disconnect_url = reverse("channels.types.wuzapi.disconnect", args=[self.channel.uuid])

    @patch("requests.request")
    def test_claim(self, mock_request):
        claim_url = reverse("channels.types.wuzapi.claim")
        self.login(self.admin)

        response = self.client.get(claim_url)
        self.assertEqual(200, response.status_code)
        self.assertEqual(BRIDGE, response.context["form"].fields["wuzapi_url"].initial)
        self.assertFalse(response.context["form"].fields["wuzapi_token"].required)

        # a number that isn't a number
        response = self.client.post(claim_url, {"wuzapi_url": BRIDGE, "phone_number": "abc"})
        self.assertFormError(
            response.context["form"], "phone_number", "Enter the number with its country code, digits only."
        )

        # a number already claimed in this workspace
        response = self.client.post(claim_url, {"wuzapi_url": BRIDGE, "phone_number": "+1 (206) 555-1212"})
        self.assertFormError(
            response.context["form"], "phone_number", "A channel for this number already exists in this workspace."
        )

        # the bridge can't be reached to create the user
        mock_request.side_effect = RequestException("connection refused")
        response = self.client.post(claim_url, {"wuzapi_url": BRIDGE + "/", "phone_number": "12065551313"})
        self.assertFormError(
            response.context["form"],
            None,
            "Unable to set up the bridge: unable to reach the bridge: connection refused",
        )
        self.assertFalse(Channel.objects.filter(address="12065551313").exists())

        # the bridge refuses the webhook, so activation fails and the channel is released again
        bridge_answers(
            mock_request,
            {
                ("POST", "/admin/users"): MockJsonResponse(200, {"success": True}),
                ("POST", "/webhook"): MockJsonResponse(500, {"error": "no session"}),
                ("POST", "/session/logout"): MockJsonResponse(200, {"success": True}),
            },
        )
        response = self.client.post(claim_url, {"wuzapi_url": BRIDGE, "phone_number": "12065551313"})
        self.assertFormError(
            response.context["form"], None, "Unable to set up the bridge: the bridge answered 500 to POST /webhook"
        )
        self.assertFalse(Channel.objects.filter(address="12065551313", is_active=True).exists())

        # and a claim that works
        bridge_answers(
            mock_request,
            {
                ("POST", "/admin/users"): MockJsonResponse(200, {"success": True}),
                ("POST", "/webhook"): MockJsonResponse(200, {"success": True}),
                ("POST", "/session/hmac/config"): MockJsonResponse(200, {"success": True}),
            },
        )
        response = self.client.post(claim_url, {"wuzapi_url": BRIDGE + "/", "phone_number": "12065551313"})

        channel = Channel.objects.get(address="12065551313", is_active=True)
        self.assertEqual("WZ", channel.channel_type)
        self.assertEqual("12065551313", channel.name)
        self.assertEqual(["whatsapp"], channel.schemes)
        self.assertEqual(BRIDGE, channel.config["wuzapi_url"])
        self.assertEqual(40, len(channel.config["wuzapi_token"]))
        self.assertEqual(48, len(channel.config["hmac_key"]))
        self.assertRedirects(
            response, reverse("channels.types.wuzapi.connect", args=[channel.uuid]), fetch_redirect_response=False
        )

        token = channel.config["wuzapi_token"]
        mock_request.assert_has_calls(
            [
                call(
                    "POST",
                    BRIDGE + "/admin/users",
                    json={"name": f"{self.org.id}-12065551313", "token": token, "events": "Message,ReadReceipt"},
                    headers={"Authorization": "admin-secret"},
                    timeout=10,
                ),
                call(
                    "POST",
                    BRIDGE + "/webhook",
                    json={
                        "webhookurl": f"http://courier:8080/c/wz/{channel.uuid}/receive",
                        "events": ["Message", "ReadReceipt"],
                    },
                    headers={"Authorization": token},
                    timeout=10,
                ),
                call(
                    "POST",
                    BRIDGE + "/session/hmac/config",
                    json={"hmac_key": channel.config["hmac_key"]},
                    headers={"Authorization": token},
                    timeout=10,
                ),
            ]
        )

    @override_settings(WUZAPI_ADMIN_TOKEN=None)
    @patch("requests.request")
    def test_claim_without_admin_token(self, mock_request):
        claim_url = reverse("channels.types.wuzapi.claim")
        self.login(self.admin)

        # the token is then required, and the bridge user isn't created here
        response = self.client.post(claim_url, {"wuzapi_url": BRIDGE, "phone_number": "12065551313"})
        self.assertFormError(response.context["form"], "wuzapi_token", "This field is required.")

        bridge_answers(
            mock_request,
            {
                ("POST", "/webhook"): MockJsonResponse(200, {"success": True}),
                ("POST", "/session/hmac/config"): MockJsonResponse(200, {"success": True}),
            },
        )
        self.client.post(claim_url, {"wuzapi_url": BRIDGE, "wuzapi_token": "mine", "phone_number": "12065551313"})

        channel = Channel.objects.get(address="12065551313", is_active=True)
        self.assertEqual("mine", channel.config["wuzapi_token"])

    def test_connect(self):
        self.assertRequestDisallowed(self.connect_url, [None, self.agent, self.admin2])

        response = self.assertReadFetch(self.connect_url, [self.editor, self.admin], context_object=self.channel)
        self.assertContains(response, self.status_url)
        self.assertContains(response, self.pair_url)
        self.assertEqual(f"/settings/channels/{self.channel.uuid}", response.headers["temba_menu_selection"])

        # a released channel isn't found
        self.channel.is_active = False
        self.channel.save(update_fields=("is_active",))
        self.login(self.admin)
        self.assertEqual(404, self.client.get(self.connect_url).status_code)

    @patch("requests.request")
    def test_status(self, mock_request):
        self.assertRequestDisallowed(self.status_url, [None, self.agent, self.admin2])
        self.login(self.admin)

        # a linked phone
        bridge_answers(
            mock_request,
            {("GET", "/session/status"): MockJsonResponse(200, {"data": {"connected": True, "loggedIn": True}})},
        )
        self.assertEqual({"status": "connected"}, self.client.get(self.status_url).json())

        # connected to WhatsApp but no phone linked yet: the QR code comes along
        bridge_answers(
            mock_request,
            {
                ("GET", "/session/status"): MockJsonResponse(200, {"data": {"connected": True, "loggedIn": False}}),
                ("GET", "/session/qr"): MockJsonResponse(200, {"data": {"QRCode": "data:image/png;base64,QR"}}),
            },
        )
        self.assertEqual(
            {"status": "pairing", "qr_code": "data:image/png;base64,QR"}, self.client.get(self.status_url).json()
        )

        # not connected: the session is started
        bridge_answers(
            mock_request,
            {
                ("GET", "/session/status"): MockJsonResponse(200, {"data": {"connected": False, "loggedIn": False}}),
                ("POST", "/session/connect"): MockJsonResponse(200, {"success": True}),
            },
        )
        self.assertEqual({"status": "starting"}, self.client.get(self.status_url).json())
        mock_request.assert_called_with(
            "POST",
            BRIDGE + "/session/connect",
            json={"Subscribe": ["Message", "ReadReceipt"], "Immediate": True},
            headers={"Authorization": "tok"},
            timeout=10,
        )

        # the bridge is down
        mock_request.side_effect = RequestException("connection refused")
        response = self.client.get(self.status_url)
        self.assertEqual(502, response.status_code)
        self.assertEqual({"error": "unable to reach the bridge: connection refused"}, response.json())

        self.assertEqual(405, self.client.post(self.status_url).status_code)

    @patch("requests.request")
    def test_pair(self, mock_request):
        self.assertRequestDisallowed(self.pair_url, [None, self.agent, self.admin2])
        self.login(self.admin)

        bridge_answers(
            mock_request,
            {("POST", "/session/pairphone"): MockJsonResponse(200, {"data": {"LinkingCode": "ABCD-1234"}})},
        )
        self.assertEqual({"code": "ABCD-1234"}, self.client.post(self.pair_url).json())
        mock_request.assert_called_with(
            "POST",
            BRIDGE + "/session/pairphone",
            json={"Phone": "12065551212"},
            headers={"Authorization": "tok"},
            timeout=30,
        )

        bridge_answers(mock_request, {("POST", "/session/pairphone"): MockJsonResponse(200, {"data": {}})})
        response = self.client.post(self.pair_url)
        self.assertEqual(502, response.status_code)
        self.assertEqual({"error": "The bridge didn't return a code, try again."}, response.json())

        self.assertEqual(405, self.client.get(self.pair_url).status_code)

    @patch("requests.request")
    def test_disconnect(self, mock_request):
        self.assertRequestDisallowed(self.disconnect_url, [None, self.agent, self.admin2])

        response = self.assertReadFetch(self.disconnect_url, [self.admin], context_object=self.channel)
        self.assertContains(response, "12065551212")

        bridge_answers(mock_request, {("POST", "/session/logout"): MockJsonResponse(200, {"success": True})})
        response = self.client.post(self.disconnect_url, {})
        self.assertRedirects(response, self.connect_url, fetch_redirect_response=False)
        mock_request.assert_called_once_with(
            "POST", BRIDGE + "/session/logout", json=None, headers={"Authorization": "tok"}, timeout=10
        )

        # the channel is still there to be linked again
        self.channel.refresh_from_db()
        self.assertTrue(self.channel.is_active)

    @patch("requests.request")
    def test_release(self, mock_request):
        bridge_answers(mock_request, {("POST", "/session/logout"): MockJsonResponse(200, {"success": True})})

        self.channel.release(self.admin)

        self.channel.refresh_from_db()
        self.assertFalse(self.channel.is_active)
        mock_request.assert_called_once_with(
            "POST", BRIDGE + "/session/logout", json=None, headers={"Authorization": "tok"}, timeout=10
        )

        # a bridge that's down doesn't stop a release
        other = self.create_channel("WZ", "12065551313", "12065551313", config=self.channel.config)
        mock_request.side_effect = RequestException("connection refused")
        other.release(self.admin)
        other.refresh_from_db()
        self.assertFalse(other.is_active)

    @patch("requests.request")
    def test_webhooks_command(self, mock_request):
        released = self.create_channel("WZ", "12065551313", "12065551313", config=self.channel.config)
        released.is_active = False
        released.save(update_fields=("is_active",))

        bridge_answers(
            mock_request,
            {
                ("POST", "/webhook"): MockJsonResponse(200, {"success": True}),
                ("POST", "/session/hmac/config"): MockJsonResponse(200, {"success": True}),
            },
        )
        out = self.call_command("wuzapi_webhooks")
        self.assertEqual(f"{self.channel.uuid} (12065551212): OK\n", out)
        mock_request.assert_any_call(
            "POST",
            BRIDGE + "/webhook",
            json={
                "webhookurl": f"http://courier:8080/c/wz/{self.channel.uuid}/receive",
                "events": ["Message", "ReadReceipt"],
            },
            headers={"Authorization": "tok"},
            timeout=10,
        )

        mock_request.side_effect = RequestException("connection refused")
        out = self.call_command("wuzapi_webhooks", "--channel", str(self.channel.uuid))
        self.assertEqual(f"{self.channel.uuid} (12065551212): unable to reach the bridge: connection refused\n", out)

        with self.assertRaises(CommandError):
            call_command("wuzapi_webhooks", "--channel", str(released.uuid))

    def call_command(self, *args) -> str:
        from io import StringIO

        out = StringIO()
        call_command(*args, stdout=out)
        return out.getvalue()
