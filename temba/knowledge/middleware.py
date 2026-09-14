from django.conf import settings
from django.http.request import split_domain_port

from .models import HelpSite


class HelpSiteMiddleware:
    """
    Serves a help site on its own domain. A request whose host is a site's configured domain gets that site, and the
    site's URLs in place of the app's - so a CNAME'd domain answers for the help site at its root and for nothing else.
    """

    urlconf = "temba.knowledge.site_urls"

    def __init__(self, get_response=None):
        self.get_response = get_response

    def __call__(self, request):
        request.help_site = None

        # the app's own domain can never be a help site, and any other host is checked against the cached domains
        domain, _ = split_domain_port(request.get_host())
        if domain and domain.lower() != settings.BRAND["domain"]:
            site = HelpSite.get_for_host(domain)
            if site:
                request.help_site = site
                request.urlconf = self.urlconf

        return self.get_response(request)
