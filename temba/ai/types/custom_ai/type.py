from django.utils.translation import gettext_lazy as _

from temba.ai.models import LLMType


class CustomAIType(LLMType):
    """
    Type for any OpenAI-compatible endpoint, e.g. a local AI gateway. The endpoint lives in the
    model's config (read by mailroom's openai service alongside api_key) and is set when the model
    is registered via the ORM; the generic connect wizard only collects the API key.
    """

    name = "Custom AI"
    slug = "custom_ai"
    api_key_help = _("The API token of your OpenAI-compatible endpoint.")

    def get_model_choices(self, api_key):
        # the endpoint isn't known at credential-validation time so there is nothing to probe —
        # offer the deployment-configured model names
        return [(m, m) for m in self.settings.get("models", {})]
