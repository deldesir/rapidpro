from unittest.mock import call

from django.conf import settings
from django.test import override_settings

from temba.ai.models import LLM
from temba.ai.types import reload_llm_types
from temba.ai.types.openai.type import OpenAIType
from temba.ai.types.openai_azure.type import OpenAIAzureType
from temba.tests import TembaTest, mock_mailroom

OPENAI_TYPE = "temba.ai.types.openai.type.OpenAIType"
AZURE_TYPE = "temba.ai.types.openai_azure.type.OpenAIAzureType"


class LLMTest(TembaTest):
    def test_model(self):
        openai = LLM.create(self.org, self.admin, OpenAIType(), "gpt-5.4-mini", "GPT-4", {"api_key": "sesame"})
        LLM.create(self.org, self.admin, OpenAIAzureType(), "gpt-35-turbo", "Azure", {})

        self.assertEqual(openai.name, "GPT-4")
        self.assertEqual(openai.type.slug, OpenAIType.slug)
        self.assertEqual(openai.config, {"api_key": "sesame"})
        self.assertEqual("TGC", openai.roles)

        openai.release(self.admin)

        self.assertFalse(openai.is_active)
        self.assertEqual(1, LLM.objects.filter(is_active=True).count())
        self.assertEqual(1, LLM.objects.filter(is_active=False).count())
        self.assertEqual(2, LLM.objects.count())

    def test_roles(self):
        azure_settings = {
            "models": {
                "gpt-35-turbo": {"max_output_tokens": 4_096},
                "gpt-classify": {"max_output_tokens": 1_024, "roles": LLM.ROLE_CLASSIFY},
            }
        }

        with override_settings(LLM_TYPES={**settings.LLM_TYPES, AZURE_TYPE: azure_settings}):
            # roles and max output tokens come from the model definition
            classifier = LLM.create(self.org, self.admin, OpenAIAzureType(), "gpt-classify", "Classifier", {})
            self.assertEqual("C", classifier.roles)
            self.assertEqual(1_024, classifier.max_output_tokens)

            # all roles if the definition doesn't limit them
            general = LLM.create(self.org, self.admin, OpenAIAzureType(), "gpt-35-turbo", "General", {})
            self.assertEqual("TGC", general.roles)

            # an edit that keeps the model keeps the roles
            LLM.objects.filter(id=general.id).update(roles=LLM.ROLE_GENERATE)
            general.refresh_from_db()
            general.update_config(self.admin, OpenAIAzureType(), "gpt-35-turbo", "Renamed", {})
            self.assertEqual("G", general.roles)

            # but they're updated when the model changes
            classifier.update_config(self.admin, OpenAIAzureType(), "gpt-35-turbo", "Classifier", {})
            self.assertEqual("TGC", classifier.roles)
            self.assertEqual(4_096, classifier.max_output_tokens)

            general.update_config(self.admin, OpenAIAzureType(), "gpt-classify", "General", {})
            self.assertEqual("C", general.roles)

        # models of types which don't list any get all roles and the default max output tokens
        with override_settings(LLM_TYPES={**settings.LLM_TYPES, OPENAI_TYPE: {}}):
            anything = LLM.create(self.org, self.admin, OpenAIType(), "gpt-anything", "Anything", {})
            self.assertEqual("TGC", anything.roles)
            self.assertEqual(4_096, anything.max_output_tokens)

    def test_settings_validation(self):
        def assert_invalid(model_def):
            with override_settings(LLM_TYPES={**settings.LLM_TYPES, OPENAI_TYPE: {"models": {"gpt-x": model_def}}}):
                with self.assertRaises(AssertionError):
                    reload_llm_types()

        self.addCleanup(reload_llm_types)

        assert_invalid(128_000)  # old format of just max output tokens
        assert_invalid({"max_output_tokens": 1_024, "roles": ""})
        assert_invalid({"max_output_tokens": 1_024, "roles": "CX"})

        with override_settings(LLM_TYPES={**settings.LLM_TYPES, OPENAI_TYPE: {"models": {"gpt-x": {"roles": "GC"}}}}):
            reload_llm_types()

    def test_release_system(self):
        system = LLM.create(self.org, self.admin, OpenAIType(), "gpt-5.4-mini", "System", {})
        system.is_system = True
        system.save(update_fields=("is_system",))

        with self.assertRaises(AssertionError):
            system.release(self.admin)

        system.refresh_from_db()
        self.assertTrue(system.is_active)

    def test_is_available_to(self):
        # by default available to any user
        self.assertTrue(OpenAIType().is_available_to(self.org, self.admin))
        self.assertTrue(OpenAIType().is_available_to(self.org, self.editor))

    @mock_mailroom
    def test_translate(self, mr_mocks):
        openai = LLM.create(self.org, self.admin, OpenAIType(), "gpt-5.4-mini", "GPT-4", {})

        items = {"a1:text": ["Hello"]}
        translated = {"a1:text": ["Hola"]}

        mr_mocks.llm_translate(translated)
        self.assertEqual(openai.translate("eng", "spa", items), translated)

        self.assertEqual(call(openai, "eng", "spa", items), mr_mocks.calls["llm_translate"][-1])
