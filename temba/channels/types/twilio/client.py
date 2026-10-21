from twilio.http.http_client import TwilioHttpClient
from twilio.rest import Client

from temba.utils import fakes


class TwilioClient(Client):
    """
    The Twilio client, sending its requests to a fake of Twilio when the current request has one.
    """

    def __init__(self, *args, **kwargs):
        if fake_url := fakes.fake_url("twilio"):
            http_client = TwilioHttpClient()
            http_client.session.mount("https://", fakes.FakeAdapter(fake_url))
            kwargs["http_client"] = http_client

        super().__init__(*args, **kwargs)
