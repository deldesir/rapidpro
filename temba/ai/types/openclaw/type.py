from django.utils.translation import gettext_lazy as _

from temba.ai.models import LLMType
from .views import ConnectView


class OpenClawType(LLMType):
    slug = "openclaw"
    name = "OpenClaw"
    
    # We allow configuring the endpoint and api_key
    # Default endpoint could be localhost for native integration
    settings = {
        "models": ["openclaw"],  # Default model name
        "exclusions": [],
    }

    connect_view = ConnectView
    form_blurb = _(
        """
        <div class="mb-4">
            <p>Connect to a local or remote <b>OpenClaw</b> instance to use it as an AI provider.</p>
            <div class="mt-3 p-3 bg-gray-100 border border-gray-300 rounded text-sm">
                <strong>Authentication Required:</strong><br/>
                Before connecting, ensure you have authenticated with Google Antigravity.
                <div class="mt-2">
                    <a href="http://localhost:3030/__openclaw__/canvas/" target="_blank" class="btn btn-sm btn-default">
                        Open Auth Dashboard ↗
                    </a>
                    <span class="ml-2 text-gray-500">or run <code>openclaw models auth login</code></span>
                </div>
            </div>
        </div>
        """
    )
