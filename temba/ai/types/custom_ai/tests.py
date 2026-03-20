from unittest.mock import MagicMock, patch

from django.test import override_settings
from django.urls import reverse

from temba.ai.models import LLM
from temba.ai.types.custom_ai.type import CustomAIType
from temba.tests import CRUDLTestMixin, TembaTest


@override_settings(
    LLM_TYPES={
        "temba.ai.types.custom_ai.CustomAIType": {"models": ["custom_ai"], "exclusions": []},
    }
)
class CustomAIConnectTest(TembaTest, CRUDLTestMixin):
    def test_connect(self):
        # 1. Start wizard
        connect_url = reverse("ai.types.custom_ai.connect")

        self.login(self.admin)
        response = self.client.get(connect_url)
        self.assertContains(response, "Endpoint URL")

        # 2. Submit credentials (mocking openai check)
        with patch("openai.OpenAI") as mock_openai:
            # Mock successful connection
            mock_client = MagicMock()
            mock_openai.return_value = mock_client

            # Step 1: Credentials
            response = self.client.post(
                connect_url,
                {
                    "connect_view-current_step": "credentials",
                    "credentials-endpoint": "http://test-endpoint:1234/v1",
                    "credentials-api_key": "secret-token",
                }
            )
            self.assertRedirect(response, connect_url)  # Next step

            # Step 2: Model selection
            response = self.client.post(
                connect_url,
                {
                    "connect_view-current_step": "model",
                    "model-model": "custom_ai",
                }
            )
            self.assertRedirect(response, connect_url)

            # Step 3: Name
            response = self.client.post(
                connect_url,
                {
                    "connect_view-current_step": "name",
                    "name-name": "My Custom AI",
                }
            )

            # Success!
            self.assertRedirect(response, reverse("ai.llm_list"))

            # Verify DB
            llm = LLM.objects.get(name="My Custom AI")
            self.assertEqual(llm.llm_type, "custom_ai")
            self.assertEqual(llm.config["endpoint"], "http://test-endpoint:1234/v1")
            self.assertEqual(llm.config["api_key"], "secret-token")
