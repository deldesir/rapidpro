from collections import OrderedDict

from django.conf import settings
from django.utils.module_loading import import_string

TYPES = OrderedDict({})  # thread-safe: populated once at import


def register_llm_type(type_class):
    """
    Registers an llm type
    """
    if not type_class.slug:  # pragma: no cover
        type_class.slug = type_class.__module__.split(".")[-2]

    assert type_class.slug not in TYPES, f"llm type slug {type_class.slug} already taken"

    TYPES[type_class.slug] = type_class()


def reload_llm_types():
    """
    Re-loads the dynamic llm types
    """
    from temba.ai.models import LLM

    global TYPES  # noqa: PLW0603 - rebuilt by reassignment so a concurrent reader never sees it half-built

    TYPES = OrderedDict({})
    for class_name, type_settings in settings.LLM_TYPES.items():
        for model, model_def in (type_settings.get("models") or {}).items():
            assert isinstance(model_def, dict), f"model {model} of {class_name} must be defined as a dict"

            roles = model_def.get("roles", LLM.ALL_ROLES)
            assert roles and set(roles) <= set(LLM.ALL_ROLES), f"model {model} of {class_name} has invalid roles"

        register_llm_type(import_string(class_name))


reload_llm_types()
