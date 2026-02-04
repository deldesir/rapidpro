import openai

from django import forms
from django.http import HttpResponseRedirect
from django.utils.translation import gettext_lazy as _

from temba.ai.models import LLM
from temba.ai.views import BaseConnectWizard, ModelForm, NameForm
from temba.utils.fields import InputWidget


class CredentialsForm(BaseConnectWizard.Form):
    endpoint = forms.CharField(
        widget=InputWidget({"placeholder": "http://localhost:3030/v1", "widget_only": False, "label": "Endpoint URL", "value": "http://localhost:3030/v1"}),
        label="Endpoint URL",
        help_text=_("The base URL for the OpenClaw OpenAI-compatible endpoint (e.g. http://localhost:3030/v1)"),
        initial="http://localhost:3030/v1"
    )
    
    api_key = forms.CharField(
        widget=InputWidget({"placeholder": "API Token", "widget_only": False, "label": "API Token", "value": ""}),
        label="API Token",
        help_text=_("The Gateway Token or Password configured in OpenClaw."),
    )

    def clean(self):
        cleaned_data = super().clean()
        endpoint = cleaned_data.get("endpoint")
        api_key = cleaned_data.get("api_key")

        if endpoint and api_key:
            # Verify connection
            try:
                # OpenClaw's openai-http.e2e.test.ts uses /v1 base path
                client = openai.OpenAI(base_url=endpoint, api_key=api_key)
                
                # Try a lightweight call to list models or just correct auth check
                # Note: OpenClaw might not implement list models perfect, but chat completion is the gold standard
                # Let's try a simple completion to verify
                client.chat.completions.create(
                    model="openclaw", 
                    messages=[{"role": "user", "content": "Hello"}]
                )
            except Exception as e:
                # Basic error handling
                raise forms.ValidationError(_(f"Could not connect to OpenClaw: {str(e)}"))

        return cleaned_data


class ConnectView(BaseConnectWizard):
    form_list = [("credentials", CredentialsForm), ("model", ModelForm), ("name", NameForm)]

    def get_form_kwargs(self, step=None):
        kwargs = super().get_form_kwargs(step)

        if step == "model":
            # For OpenClaw, we just hardcode/allow "openclaw" or maybe fetch if list_models was supported
            # But based on our check, we'll just offer 'openclaw' or a free text field if we wanted
            # For consistency with other types, we'll provide what we defined in type settings
            kwargs["model_choices"] = ((m, m) for m in self.llm_type.settings["models"])

        if step == "name":
            step_data = self.storage.data["step_data"]
            # Default name
            kwargs["model_name"] = "OpenClaw"

        return kwargs

    def done(self, form_list, form_dict, **kwargs):
        creds = form_dict["credentials"].cleaned_data
        endpoint = creds["endpoint"]
        api_key = creds["api_key"]
        
        model = form_dict["model"].cleaned_data["model"]
        name = form_dict["name"].cleaned_data["name"]

        self.object = LLM.create(
            self.request.org,
            self.request.user,
            self.llm_type,
            model,
            name,
            {"endpoint": endpoint, "api_key": api_key},
        )

        return HttpResponseRedirect(self.get_success_url())
