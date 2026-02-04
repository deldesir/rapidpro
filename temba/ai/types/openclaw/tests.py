from unittest.mock import MagicMock, patch

from django.test import override_settings
from django.urls import reverse

from temba.ai.models import LLM
from temba.ai.types.openclaw.type import OpenClawType
from temba.tests import CRUDLTestMixin, TembaTest


@override_settings(
    LLM_TYPES={
        "temba.ai.types.openclaw.OpenClawType": {"models": ["openclaw"], "exclusions": []},
    }
)
class OpenClawConnectTest(TembaTest, CRUDLTestMixin):
    def test_connect(self):
        # 1. Start wizard
        connect_url = reverse("ai.types.openclaw.connect")
        
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
                    "credentials-endpoint": "http://test-claw:1234/v1",
                    "credentials-api_key": "secret-token",
                }
            )
            self.assertRedirect(response, connect_url) # Next step
            
            # Step 2: Model selection
            response = self.client.post(
                connect_url,
                {
                    "connect_view-current_step": "model",
                    "model-model": "openclaw",
                }
            )
            self.assertRedirect(response, connect_url)
            
            # Step 3: Name
            response = self.client.post(
                connect_url,
                {
                    "connect_view-current_step": "name",
                    "name-name": "My OpenClaw",
                }
            )
            
            # Success!
            self.assertRedirect(response, reverse("ai.llm_list"))
            
            # Verify DB
            llm = LLM.objects.get(name="My OpenClaw")
            self.assertEqual(llm.llm_type, "openclaw")
            self.assertEqual(llm.config["endpoint"], "http://test-claw:1234/v1")
            self.assertEqual(llm.config["api_key"], "secret-token")
