import json

from django.template import Context, Template
from django.urls import clear_script_prefix, set_script_prefix

from temba.tests import TembaTest


class URLTagsTest(TembaTest):
    def render(self, source: str) -> str:
        return Template("{% load url_tags %}" + source).render(Context({}))

    def test_get_urls(self):
        urls = json.loads(self.render("{% get_urls %}"))

        self.assertEqual("/", urls["root"])
        self.assertEqual("/org/choose/", urls["orgs_org_choose"])
        self.assertEqual("/org/workspace/", urls["orgs_org_workspace"])
        self.assertEqual("/staff/org/service/", urls["staff_org_service"])

        # under a sub-path every URL carries the prefix, because reverse() does
        set_script_prefix("/rp/")
        try:
            urls = json.loads(self.render("{% get_urls %}"))
        finally:
            clear_script_prefix()

        self.assertEqual("/rp/", urls["root"])
        self.assertEqual("/rp/org/choose/", urls["orgs_org_choose"])
        self.assertEqual("/rp/staff/org/", urls["staff_org_list"])

    def test_script_prefix(self):
        self.assertEqual("/adminboundary/", self.render("{% script_prefix %}adminboundary/"))

        set_script_prefix("/rp/")
        try:
            self.assertEqual("/rp/adminboundary/", self.render("{% script_prefix %}adminboundary/"))
        finally:
            clear_script_prefix()

    def test_frame_hands_the_map_to_scripts(self):
        # the frame publishes the map for its scripts, with whatever prefix the request was served under
        self.login(self.admin)
        response = self.client.get("/org/workspace/")

        self.assertEqual(200, response.status_code)
        self.assertContains(response, 'window.URLS = {"root": "/", "orgs_org_choose": "/org/choose/"')
