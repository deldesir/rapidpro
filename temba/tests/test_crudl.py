from unittest.mock import patch

from smartmin.views import SmartUpdateView

from django.http import Http404
from django.test import RequestFactory
from django.urls import reverse

from temba.tests import CRUDLTestMixin, TembaTest
from temba.tests.crudl import ObjectModified


class CRUDLTestMixinTest(CRUDLTestMixin, TembaTest):
    def test_update_submit_checks_modified(self):
        label = self.create_label("Spam")
        update_url = reverse("msgs.label_update", args=[label.id])

        self.assertUpdateSubmit(update_url, self.admin, {"name": "Junk"})

        # a view which doesn't record who modified the object fails the check
        with patch.object(SmartUpdateView, "pre_save", lambda self, obj: obj):
            with self.assertRaisesRegex(AssertionError, "modified_by mismatch"):
                self.assertUpdateSubmit(update_url, self.admin, {"name": "Rubbish"})

    def test_update_submit_object_not_found(self):
        request = RequestFactory().get(reverse("msgs.label_update", args=[1234567]))
        request.user = self.admin
        request.org = self.org

        with self.assertRaisesRegex(Http404, "LabelCRUDL.Update couldn't find its object"):
            ObjectModified.get_object(request)
