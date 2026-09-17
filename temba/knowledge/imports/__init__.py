from collections import OrderedDict

from django.conf import settings
from django.utils.module_loading import import_string

TYPES = OrderedDict({})  # thread-safe: populated once at import


def register_import_type(type_class):
    """
    Registers a helpdesk import type
    """
    assert type_class.slug, f"import type {type_class.__name__} has no slug"
    assert type_class.slug not in TYPES, f"import type slug {type_class.slug} already taken"

    TYPES[type_class.slug] = type_class()


def reload_import_types():
    """
    Re-loads the dynamic helpdesk import types
    """
    global TYPES  # noqa: PLW0603 - rebuilt by reassignment so a concurrent reader never sees it half-built

    TYPES = OrderedDict({})
    for class_name in settings.HELPDESK_IMPORT_TYPES:
        register_import_type(import_string(class_name))


reload_import_types()
