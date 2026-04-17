from django.utils.translation import gettext_lazy as _

from temba.ai.models import LLMType
from .views import ConnectView


class CustomAIType(LLMType):
    slug = "custom_ai"
    name = "Custom AI"

    # Allows configuring any OpenAI-compatible endpoint and api_key
    settings = {
        "models": ["custom_ai"],  # Default model name
        "exclusions": [],
    }

    connect_view = ConnectView
    form_blurb = _(
        """
        <div class="mb-4">
            <p>Connect to any <b>OpenAI-compatible</b> endpoint to use it as an AI provider.</p>
            <div class="mt-3 p-3 bg-gray-100 border border-gray-300 rounded text-sm">
                <strong>IIAB AI Gateway:</strong><br/>
                Set the endpoint to <code>http://localhost:8086/v1</code> and use your LiteLLM master key as the API token.
                <div class="mt-2 text-gray-500">
                    Find your key in <code>/etc/iiab/local_vars.yml</code> under <code>litellm_master_key</code>.
                </div>
            </div>
        </div>
        """
    )
