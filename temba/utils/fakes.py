"""
A development-only way for a request to have the calls it makes to outside providers answered by a fake of them,
e.g. to capture screenshots of pages that need an account with a provider, without one.

With PROVIDER_FAKES enabled, a request with an X-Provider-Fake header giving a fake's base URL has the OpenAI, Twilio
and Vonage clients it makes send their requests there, under a path for each provider (/openai, /twilio, /vonage)
followed by the provider's own path. Requests without the header, and every request with the setting off (as it is
outside of development), are untouched.
"""

from contextvars import ContextVar
from urllib.parse import urlsplit, urlunsplit

from requests.adapters import HTTPAdapter

from django.conf import settings
from django.core.exceptions import MiddlewareNotUsed

HEADER = "X-Provider-Fake"

_base_url = ContextVar("provider_fake_base_url", default=None)


class ProviderFakeMiddleware:
    """
    Makes the fake named by a request's header the one its provider clients use, for that request only.
    """

    def __init__(self, get_response):
        if not settings.PROVIDER_FAKES:
            raise MiddlewareNotUsed()

        self.get_response = get_response

    def __call__(self, request):
        token = _base_url.set(request.headers.get(HEADER) or None)
        try:
            return self.get_response(request)
        finally:
            _base_url.reset(token)


def fake_url(provider: str) -> str | None:
    """
    The base URL a provider's client should use in place of the provider's, if the current request has a fake.
    """

    base_url = _base_url.get()
    if not settings.PROVIDER_FAKES or not base_url:
        return None

    return f"{base_url.rstrip('/')}/{provider}"


class FakeAdapter(HTTPAdapter):
    """
    A requests adapter which sends every request to a fake, keeping its path and query.
    """

    def __init__(self, base_url: str):
        super().__init__()

        self.base_url = urlsplit(base_url)

    def send(self, request, **kwargs):
        url = urlsplit(request.url)
        request.url = urlunsplit(
            (self.base_url.scheme, self.base_url.netloc, self.base_url.path + url.path, url.query, "")
        )
        return super().send(request, **kwargs)
