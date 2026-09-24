import json

from django import template
from django.urls import get_script_prefix, reverse
from django.utils.safestring import mark_safe

register = template.Library()


@register.simple_tag
def script_prefix() -> str:
    """
    The prefix the app is served under - "/" unless it lives at a sub-path - for the few places a template builds a
    URL that no view name resolves to
    """
    return get_script_prefix()


@register.simple_tag
def get_urls() -> str:
    """
    The URLs the frame's scripts need, as a JSON object. reverse() includes the prefix the app is served under, so
    scripts read these instead of assembling paths from the root.
    """
    urls = {
        "root": get_script_prefix(),
        "orgs_org_choose": reverse("orgs.org_choose"),
        "orgs_org_create": reverse("orgs.org_create"),
        "orgs_org_workspace": reverse("orgs.org_workspace"),
        "staff_org_list": reverse("staff.org_list"),
        "staff_org_service": reverse("staff.org_service"),
    }
    return mark_safe(json.dumps(urls))
