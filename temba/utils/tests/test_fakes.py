from contextlib import contextmanager
from unittest.mock import Mock, patch

from requests import Response

from django.core.exceptions import MiddlewareNotUsed
from django.http import HttpResponse
from django.test import RequestFactory, override_settings

from temba.ai.types import TYPES
from temba.channels.types.twilio.client import TwilioClient
from temba.channels.types.vonage.client import VonageClient
from temba.tests import TembaTest
from temba.utils import fakes
from temba.utils.fakes import ProviderFakeMiddleware


class ProviderFakesTest(TembaTest):
    def setUp(self):
        super().setUp()

        self.sent = []

    @contextmanager
    def faked(self, base_url: str):
        """
        Runs the code in a with block as though for a request with the given fake.
        """

        token = fakes._base_url.set(base_url)
        try:
            yield
        finally:
            fakes._base_url.reset(token)

    def send(self, adapter, request, **kwargs):
        """
        Answers a request as the fake would, recording where it was sent.
        """

        self.sent.append(request.url)

        response = Response()
        response.status_code = 200
        response.headers["Content-Type"] = "application/json"
        response._content = (
            b'{"sid": "AC4d3c2b1a", "auth_token": "9f8e7d6c", "type": "Trial", "value": 12.5, "autoReload": false}'
        )
        response.url = request.url
        response.request = request
        return response

    def test_middleware(self):
        seen = []

        def get_response(request):
            seen.append(fakes.fake_url("twilio"))
            return HttpResponse()

        middleware = ProviderFakeMiddleware(get_response)

        # a request without the header has no fake
        middleware(RequestFactory().get("/"))

        # one with it has its fake while it's handled, and only then
        middleware(RequestFactory().get("/", headers={"X-Provider-Fake": "http://fake:8000/"}))
        self.assertIsNone(fakes.fake_url("twilio"))

        self.assertEqual([None, "http://fake:8000/twilio"], seen)

        # and with the setting off, the middleware isn't used and nothing has a fake
        with override_settings(PROVIDER_FAKES=False):
            with self.assertRaises(MiddlewareNotUsed):
                ProviderFakeMiddleware(get_response)

            with self.faked("http://fake:8000"):
                self.assertIsNone(fakes.fake_url("twilio"))

    def test_requests(self):
        # a request reaches the app's provider clients through the middleware
        with patch("temba.channels.types.twilio.views.TwilioClient") as mock_client:
            mock_client.side_effect = lambda *args: Mock(api=Mock(account=Mock(fetch=self._record_fake)))

            self.login(self.admin)
            self.client.post(
                "/channels/types/twilio/connect/",
                {"account_sid": "AC4d3c2b1a", "account_token": "9f8e7d6c"},
                headers={"X-Provider-Fake": "http://fake:8000"},
            )
            self.client.post(
                "/channels/types/twilio/connect/", {"account_sid": "AC4d3c2b1a", "account_token": "9f8e7d6c"}
            )

        self.assertEqual(["http://fake:8000/twilio", None], self.sent)

    def _record_fake(self):
        self.sent.append(fakes.fake_url("twilio"))
        return Mock(sid="AC4d3c2b1a", auth_token="9f8e7d6c")

    @patch("requests.adapters.HTTPAdapter.send", autospec=True)
    def test_twilio(self, mock_send):
        mock_send.side_effect = self.send

        with self.faked("http://fake:8000"):
            account = TwilioClient("AC4d3c2b1a", "9f8e7d6c").api.account.fetch()

        self.assertEqual("Trial", account.type)
        self.assertEqual(["http://fake:8000/twilio/2010-04-01/Accounts/AC4d3c2b1a.json"], self.sent)

        # without a fake, it goes to Twilio
        TwilioClient("AC4d3c2b1a", "9f8e7d6c").api.account.fetch()

        self.assertEqual("https://api.twilio.com/2010-04-01/Accounts/AC4d3c2b1a.json", self.sent[1])

    @patch("requests.adapters.HTTPAdapter.send", autospec=True)
    def test_vonage(self, mock_send):
        mock_send.side_effect = self.send

        with self.faked("http://fake:8000"):
            self.assertTrue(VonageClient("4d3c2b1a", "9f8e7d6c").check_credentials())

        self.assertEqual(["http://fake:8000/vonage/account/get-balance"], [u.split("?")[0] for u in self.sent])

        # without a fake, it goes to Vonage
        VonageClient("4d3c2b1a", "9f8e7d6c").check_credentials()

        self.assertEqual("https://rest.nexmo.com/account/get-balance", self.sent[1].split("?")[0])

    @patch("openai.OpenAI")
    def test_openai(self, mock_client):
        mock_client.return_value.models.list.return_value = [Mock(id="gpt-5.4-mini")]

        with self.faked("http://fake:8000"):
            TYPES["openai"].get_model_choices("sk-4d3c2b1a")

        mock_client.assert_called_once_with(api_key="sk-4d3c2b1a", base_url="http://fake:8000/openai/v1")

        # without a fake, it uses OpenAI's own
        TYPES["openai"].get_model_choices("sk-4d3c2b1a")

        mock_client.assert_called_with(api_key="sk-4d3c2b1a", base_url=None)
