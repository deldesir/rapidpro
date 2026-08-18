from temba.ai.types.custom_ai.type import CustomAIType
from temba.tests import TembaTest


class CustomAITypeTest(TembaTest):
    def test_get_model_choices(self):
        # choices come from the deployment settings, no remote probe
        choices = CustomAIType().get_model_choices("sesame")

        self.assertEqual([("custom_ai", "custom_ai")], choices)
