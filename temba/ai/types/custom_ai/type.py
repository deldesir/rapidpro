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
                <strong>Authentication Required:</strong><br/>
                Ensure you have authenticated with your AI provider and have a valid API token.
                <div class="mt-2">
                    <a href="http://localhost:3030/__openclaw__/canvas/" target="_blank" class="btn btn-sm btn-default">
                        Open Auth Dashboard ↗
                    </a>
                    <span class="ml-2 text-gray-500">or configure your endpoint and token below</span>
                </div>
            </div>
        </div>
        """
    )
