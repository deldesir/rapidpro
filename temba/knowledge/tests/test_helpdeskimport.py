import time
from unittest.mock import Mock, patch

from django.urls import reverse

from temba.knowledge.crisp import CrispClient, CrispError
from temba.knowledge.models import Article, HelpdeskImport, HelpSite, Knowledge
from temba.orgs.models import Org
from temba.tests import CRUDLTestMixin, TembaTest
from temba.tests.requests import MockJsonResponse

WEBSITE_ID = "2a810199-9469-490b-8be9-d3d994c3e788"
FLOWS_ID = "2023f00a-2a48-4884-bd1b-32256b1ed28b"
STARTING_ID = "69701b40-cc63-4a69-9877-26afe3f10b01"
HIDDEN_ID = "8fd1c1f0-5d4a-4e6b-9c1e-1d9c2f3a4b5c"

PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"

SHOT_URL = "https://storage.crisp.chat/users/helpdesk/website/abc/shot_1evbdfc.png"
MISSING_URL = "https://storage.crisp.chat/users/helpdesk/website/abc/gone_x1y2z3.png"

STARTING_BODY = f"""# Starting a flow

See [the flows category](/en/category/flows-6ogz7g/) and [this article](https://help.acme.com/en/article/starting-a-flow-9gcerd/#3-manually).

A link to [a hidden one](https://help.acme.com/en/article/hidden-abc123/) can't be followed, nor [elsewhere](https://example.com/en/article/other-9gcerd/).

![]({SHOT_URL} =600x400)

![small]({MISSING_URL} =100x100)
"""


class CrispMock:
    """
    A Crisp API of one website with a helpdesk of one category and two articles, answered as requests.get.
    """

    def __init__(self, *, key="secret", websites=None, categories=None, articles=None, details=None, fail=None):
        self.key = key
        self.websites = websites if websites is not None else [WEBSITE_ID]
        self.categories = (
            categories
            if categories is not None
            else [
                {
                    "category_id": FLOWS_ID,
                    "name": "Flows",
                    "description": "All about flows.",
                    "color": "#2f6391",
                    "url": "https://help.acme.com/en/category/flows-6ogz7g/",
                }
            ]
        )
        self.articles = (
            articles
            if articles is not None
            else [
                {
                    "article_id": STARTING_ID,
                    "title": "Starting a flow",
                    "status": "published",
                    "visibility": "visible",
                    "url": "https://help.acme.com/en/article/starting-a-flow-9gcerd/",
                    "updated_at": 1700000000000,
                    "category": {"category_id": FLOWS_ID, "name": "Flows"},
                },
                {
                    "article_id": HIDDEN_ID,
                    "title": "Hidden one",
                    "status": "published",
                    "visibility": "hidden",
                    "url": None,
                    "updated_at": 1700000000000,
                    "category": None,
                },
            ]
        )
        self.details = details or {
            STARTING_ID: {"title": "Starting a flow", "description": "How to start", "content": STARTING_BODY},
            HIDDEN_ID: {"title": "Hidden one", "description": "", "content": "Nothing to see"},
        }
        self.fail = fail or {}  # path fragment -> status code
        self.calls = []

    def __call__(self, url, **kwargs):
        self.calls.append(url)

        if url.startswith(CrispClient.STORAGE_URL):
            if url == SHOT_URL:
                return Mock(status_code=200, iter_content=lambda chunk_size: [PNG])
            return Mock(status_code=404)

        if kwargs.get("auth") != ("ident", self.key):
            return MockJsonResponse(401, {"error": True, "reason": "invalid_session"})

        path = url[len(CrispClient.BASE_URL) :]
        for fragment, status in self.fail.items():
            if fragment in path:
                return MockJsonResponse(status, {"error": True, "reason": "failed"})

        def page(items, number):
            return MockJsonResponse(206 if number == 1 else 200, {"data": items if number == 1 else []})

        if path.startswith("/plugin/connect/websites/all"):
            return MockJsonResponse(200, {"data": [{"website_id": w} for w in self.websites]})

        base = f"/website/{WEBSITE_ID}/helpdesk"
        if path == base:
            return MockJsonResponse(200, {"data": {"name": "Acme", "url": "https://help.acme.com/"}})
        if path.startswith(f"{base}/locales/"):
            return page([{"locale": "en", "url": "https://help.acme.com/en/"}], int(path.rsplit("/", 1)[1]))
        if path.startswith(f"{base}/locale/en/categories/"):
            return page(self.categories, int(path.rsplit("/", 1)[1]))
        if path.startswith(f"{base}/locale/en/articles/"):
            return page(self.articles, int(path.rsplit("/", 1)[1]))
        if path.startswith(f"{base}/locale/en/article/"):
            article_id = path.rsplit("/", 1)[1]
            return MockJsonResponse(200, {"data": {"article_id": article_id, **self.details[article_id]}})

        return MockJsonResponse(404, {"error": True, "reason": "not_found"})


class HelpdeskImportTest(TembaTest):
    def setUp(self):
        super().setUp()

        self.helpdesk = self.org.knowledge.get(knowledge_type=Knowledge.TYPE_HELPDESK)

    def create_import(self, key="secret"):
        return HelpdeskImport.create(
            self.helpdesk,
            self.admin,
            HelpdeskImport.TYPE_CRISP,
            {
                HelpdeskImport.CONFIG_IDENTIFIER: "ident",
                HelpdeskImport.CONFIG_KEY: key,
                HelpdeskImport.CONFIG_WEBSITE_ID: WEBSITE_ID,
                HelpdeskImport.CONFIG_LOCALE: "en",
            },
        )

    @patch("temba.knowledge.crisp.requests.get")
    def test_perform(self, mock_get):
        crisp = mock_get.side_effect = CrispMock()

        # something already here stays, and the site's existing redirects are kept
        existing = Article.create(self.helpdesk, self.admin, "Ours")
        site = HelpSite.get_or_create(self.helpdesk, self.admin)
        site.redirects = {"/old": str(existing.uuid)}
        site.save()

        self.helpdesk.status = Knowledge.STATUS_READY
        self.helpdesk.save(update_fields=("status",))

        imp = self.create_import()
        self.assertFalse(imp.is_finished)
        self.assertEqual("Pending", imp.as_json()["status"])

        imp.perform()

        imp.refresh_from_db()
        self.assertEqual(HelpdeskImport.STATUS_COMPLETE, imp.status)
        self.assertIsNone(imp.error)
        self.assertIsNotNone(imp.started_on)
        self.assertIsNotNone(imp.finished_on)
        self.assertEqual(3, imp.num_articles)
        self.assertEqual(3, imp.num_imported)
        self.assertEqual({"total": 3, "current": 3}, imp.as_json()["progress"])  # the section and both articles

        # the key was lent for the import and isn't kept
        self.assertEqual({"identifier": "ident", "website_id": WEBSITE_ID, "locale": "en"}, imp.config)

        # the category is a section, with Crisp's id as its uuid
        flows = self.helpdesk.articles.get(uuid=FLOWS_ID)
        self.assertIsNone(flows.parent)
        self.assertEqual("Flows", flows.title)
        self.assertEqual("All about flows.", flows.description)
        self.assertEqual(Article.STATUS_PUBLISHED, flows.status)

        # a visible published article is published, filed under its section, in the locale's language
        starting = self.helpdesk.articles.get(uuid=STARTING_ID)
        self.assertEqual(flows, starting.parent)
        self.assertEqual("Starting a flow", starting.title)
        self.assertEqual("eng", starting.language)
        self.assertEqual(Article.STATUS_PUBLISHED, starting.status)

        # links to pages of the site are resolved to articles, others left alone; sized images carry the size as a
        # fragment, and those that could be fetched are ours now while one that couldn't stays where it was
        image = starting.images.get()
        self.assertEqual("shot_1evbdfc.png", image.name)
        self.assertEqual("image/png", image.content_type)
        self.assertEqual(
            f"""# Starting a flow

See [the flows category](article:{FLOWS_ID}) and [this article](article:{STARTING_ID}).

A link to [a hidden one](https://help.acme.com/en/article/hidden-abc123/) can't be followed, nor [elsewhere](https://example.com/en/article/other-9gcerd/).

![]({image.path}#size=large)

![small]({MISSING_URL}#size=small)
""",
            starting.body,
        )

        # a hidden article is a draft, in a section made for the ones Crisp has in none
        hidden = self.helpdesk.articles.get(uuid=HIDDEN_ID)
        self.assertEqual(Article.STATUS_DRAFT, hidden.status)
        self.assertEqual("Uncategorized", hidden.parent.title)
        self.assertEqual(Article.STATUS_PUBLISHED, hidden.parent.status)
        self.assertEqual("Nothing to see", hidden.body)

        # the site's old addresses lead to the new pages; the hidden article had none
        site.refresh_from_db()
        self.assertEqual(
            {
                "/old": str(existing.uuid),
                "/en/category/flows-6ogz7g": FLOWS_ID,
                "/en/article/starting-a-flow-9gcerd": STARTING_ID,
            },
            site.redirects,
        )

        # and the helpdesk is queued for reindexing
        self.helpdesk.refresh_from_db()
        self.assertEqual(Knowledge.STATUS_PENDING, self.helpdesk.status)

        self.assertEqual(5, self.helpdesk.articles.filter(is_active=True).count())
        self.assertEqual(1, len([url for url in crisp.calls if url == SHOT_URL]))

        # importing again updates what's here rather than making it twice, and doesn't fetch images it already has.
        # Only an article Crisp has touched since is fetched again - the other's listing is enough to republish it
        crisp.details[STARTING_ID]["content"] = f"Changed\n\n![]({SHOT_URL})"
        crisp.articles[0]["updated_at"] = int(time.time() * 1000) + 60_000
        crisp.articles[1]["visibility"] = "visible"
        crisp.categories[0]["name"] = "Flows!"
        crisp.calls.clear()

        imp2 = self.create_import()
        imp2.perform()

        imp2.refresh_from_db()
        self.assertEqual(HelpdeskImport.STATUS_COMPLETE, imp2.status)
        self.assertEqual(5, self.helpdesk.articles.filter(is_active=True).count())
        self.assertEqual(0, len([url for url in crisp.calls if url == SHOT_URL]))
        self.assertEqual([STARTING_ID], [url.rsplit("/", 1)[1] for url in crisp.calls if "/article/" in url])

        flows.refresh_from_db()
        self.assertEqual("Flows!", flows.title)
        starting.refresh_from_db()
        self.assertEqual(f"Changed\n\n![]({image.path})", starting.body)
        self.assertEqual(1, starting.images.count())
        hidden.refresh_from_db()
        self.assertEqual(Article.STATUS_PUBLISHED, hidden.status)
        self.assertEqual(1, self.helpdesk.articles.filter(title="Uncategorized", is_active=True).count())

        # a listing that doesn't say when it was touched is always fetched
        del crisp.articles[1]["updated_at"]
        crisp.details[HIDDEN_ID]["content"] = "Something to see"
        crisp.calls.clear()

        imp3 = self.create_import()
        imp3.perform()

        self.assertIn(HIDDEN_ID, [url.rsplit("/", 1)[1] for url in crisp.calls if "/article/" in url])
        hidden.refresh_from_db()
        self.assertEqual("Something to see", hidden.body)

    @patch("temba.knowledge.crisp.requests.get")
    def test_perform_uuids(self, mock_get):
        crisp = mock_get.side_effect = CrispMock()

        # another workspace has imported the same site, so its ids are taken there
        other_helpdesk = self.org2.knowledge.get(knowledge_type=Knowledge.TYPE_HELPDESK)
        other_flows = Article.create(other_helpdesk, self.admin2, "Flows")
        other_flows.uuid = FLOWS_ID
        other_flows.save(update_fields=("uuid",))

        # and one of ours by Crisp's id has been deleted
        deleted = Article.create(self.helpdesk, self.admin, "Hidden one")
        deleted.uuid = HIDDEN_ID
        deleted.save(update_fields=("uuid",))
        deleted.release(self.admin)

        imp = self.create_import()
        imp.perform()

        imp.refresh_from_db()
        self.assertEqual(HelpdeskImport.STATUS_COMPLETE, imp.status)

        # the section got an id of its own, which links to it resolve to
        flows = self.helpdesk.articles.get(title="Flows")
        self.assertNotEqual(FLOWS_ID, str(flows.uuid))
        starting = self.helpdesk.articles.get(uuid=STARTING_ID)
        self.assertEqual(flows, starting.parent)
        self.assertIn(f"[the flows category](article:{flows.uuid})", starting.body)
        self.assertIn(f"[this article](article:{STARTING_ID})", starting.body)

        # the deleted article is back
        deleted.refresh_from_db()
        self.assertTrue(deleted.is_active)
        self.assertEqual("Nothing to see", deleted.body)

        other_flows.refresh_from_db()
        self.assertEqual("Flows", other_flows.title)
        self.assertEqual(other_helpdesk, other_flows.knowledge)

        # importing again finds everything under the ids it has here
        crisp.categories[0]["name"] = "Flows!"
        imp = self.create_import()
        imp.perform()

        imp.refresh_from_db()
        self.assertEqual(HelpdeskImport.STATUS_COMPLETE, imp.status)
        self.assertEqual(4, self.helpdesk.articles.filter(is_active=True).count())
        flows.refresh_from_db()
        self.assertEqual("Flows!", flows.title)

    @patch("temba.knowledge.crisp.requests.get")
    def test_perform_failures(self, mock_get):
        # a key Crisp doesn't accept
        mock_get.side_effect = CrispMock(key="other")

        imp = self.create_import()
        imp.perform()

        imp.refresh_from_db()
        self.assertEqual(HelpdeskImport.STATUS_FAILED, imp.status)
        self.assertEqual("Crisp did not accept the API key.", imp.error)
        self.assertNotIn(HelpdeskImport.CONFIG_KEY, imp.config)
        self.assertEqual(0, self.helpdesk.articles.count())

        # a helpdesk bigger than ours can be
        mock_get.side_effect = CrispMock()

        with patch("temba.knowledge.models.Article.MAX_ARTICLES", 2):
            imp = self.create_import()
            imp.perform()

        imp.refresh_from_db()
        self.assertEqual(HelpdeskImport.STATUS_FAILED, imp.status)
        self.assertEqual("The helpdesk would exceed its limit of 2 articles.", imp.error)
        self.assertEqual(0, self.helpdesk.articles.count())

        # crisp falling over partway through
        mock_get.side_effect = CrispMock(fail={f"/article/{HIDDEN_ID}": 500})

        with patch("temba.knowledge.crisp.time.sleep") as mock_sleep:
            imp = self.create_import()
            imp.perform()

        imp.refresh_from_db()
        self.assertEqual(HelpdeskImport.STATUS_FAILED, imp.status)
        self.assertEqual("Crisp could not be reached. Please try again later.", imp.error)
        self.assertEqual(5, mock_sleep.call_count)
        self.assertEqual(2, imp.num_imported)  # what came before stays

        # its quota running out is said as such, and a run picking up after it doesn't refetch what it got
        crisp = mock_get.side_effect = CrispMock(fail={f"/article/{HIDDEN_ID}": 429})

        with patch("temba.knowledge.crisp.time.sleep"):
            imp = self.create_import()
            imp.perform()

        imp.refresh_from_db()
        self.assertEqual(HelpdeskImport.STATUS_FAILED, imp.status)
        self.assertEqual("Crisp's rate limit was reached. Please try again later.", imp.error)

        crisp.fail = {}
        crisp.calls.clear()
        imp = self.create_import()
        imp.perform()

        imp.refresh_from_db()
        self.assertEqual(HelpdeskImport.STATUS_COMPLETE, imp.status)
        self.assertEqual([HIDDEN_ID], [url.rsplit("/", 1)[1] for url in crisp.calls if "/article/" in url])
        self.assertEqual(4, self.helpdesk.articles.filter(is_active=True).count())

        # a website the token can't see
        mock_get.side_effect = CrispMock(fail={"/helpdesk": 404})

        imp = self.create_import()
        imp.perform()

        imp.refresh_from_db()
        self.assertEqual(HelpdeskImport.STATUS_FAILED, imp.status)
        self.assertEqual("Crisp has no helpdesk for that website.", imp.error)

        # something unexpected
        mock_get.side_effect = CrispMock(fail={"/helpdesk": 418})

        imp = self.create_import()
        imp.perform()

        imp.refresh_from_db()
        self.assertEqual(HelpdeskImport.STATUS_FAILED, imp.status)
        self.assertEqual("Crisp returned an unexpected response.", imp.error)

    @patch("temba.knowledge.crisp.requests.get")
    def test_client(self, mock_get):
        crisp = mock_get.side_effect = CrispMock(websites=["w1", "w2"])
        client = CrispClient("ident", "secret")

        self.assertEqual(["w1", "w2"], client.get_websites())
        self.assertEqual({"name": "Acme", "url": "https://help.acme.com/"}, client.get_helpdesk(WEBSITE_ID))
        self.assertEqual([{"locale": "en", "url": "https://help.acme.com/en/"}], client.get_locales(WEBSITE_ID))
        self.assertEqual(2, len(client.get_articles(WEBSITE_ID, "en")))

        # a rate limit is waited out
        crisp.fail = {"/categories/": 429}
        with patch("temba.knowledge.crisp.time.sleep") as mock_sleep:
            with self.assertRaises(CrispError):
                client.get_categories(WEBSITE_ID, "en")

        self.assertEqual([1, 2, 4, 8, 16], [c.args[0] for c in mock_sleep.call_args_list])

        # an image too big isn't downloaded
        self.assertIsNone(client.download(SHOT_URL, max_size=4))
        self.assertEqual((PNG, "image/png"), client.download(SHOT_URL, max_size=1024))
        self.assertIsNone(client.download(MISSING_URL, max_size=1024))

    def test_get_unfinished(self):
        self.assertIsNone(HelpdeskImport.get_unfinished(self.helpdesk))

        imp = self.create_import()
        self.assertEqual(imp, HelpdeskImport.get_unfinished(self.helpdesk))
        self.assertEqual(imp, HelpdeskImport.get_latest(self.helpdesk))

        # one that never finished in hours has died rather than still be running
        imp.created_on = imp.created_on - HelpdeskImport.UNFINISHED_WINDOW
        imp.save(update_fields=("created_on",))
        self.assertIsNone(HelpdeskImport.get_unfinished(self.helpdesk))

        imp = self.create_import()
        imp.status = HelpdeskImport.STATUS_COMPLETE
        imp.save(update_fields=("status",))
        self.assertIsNone(HelpdeskImport.get_unfinished(self.helpdesk))


class HelpdeskImportCRUDLTest(TembaTest, CRUDLTestMixin):
    def setUp(self):
        super().setUp()

        self.helpdesk = self.org.knowledge.get(knowledge_type=Knowledge.TYPE_HELPDESK)
        self.org.features = [Org.FEATURE_AGENTS]
        self.org.save(update_fields=("features",))

    @patch("temba.knowledge.crisp.requests.get")
    def test_create(self, mock_get):
        crisp = mock_get.side_effect = CrispMock()

        create_url = reverse("knowledge.helpdeskimport_create")
        self.assertEqual("/helpdeskimport/create/", create_url)

        self.assertRequestDisallowed(create_url, [None, self.agent])
        self.assertCreateFetch(create_url, [self.editor, self.admin], form_fields=("identifier", "key", "website_id"))

        # the key is checked with crisp before anything is queued
        self.assertCreateSubmit(
            create_url,
            self.admin,
            {"identifier": "ident", "key": "wrong"},
            form_errors={"__all__": "Crisp did not accept the API key."},
        )
        self.assertEqual(0, HelpdeskImport.objects.count())

        # a token that reaches several websites is asked which
        crisp.websites = [WEBSITE_ID, "other"]
        self.assertCreateSubmit(
            create_url,
            self.admin,
            {"identifier": "ident", "key": "secret"},
            form_errors={"__all__": "That token has access to several websites, so a website ID is needed."},
        )
        self.assertCreateSubmit(
            create_url,
            self.admin,
            {"identifier": "ident", "key": "secret", "website_id": "another"},
            form_errors={"__all__": "That token has no access to that website."},
        )
        crisp.websites = []
        self.assertCreateSubmit(
            create_url,
            self.admin,
            {"identifier": "ident", "key": "secret"},
            form_errors={"__all__": "That token has no access to any website."},
        )
        crisp.websites = [WEBSITE_ID]

        # with a good key the import is queued - and run, since tasks are eager in tests
        self.assertCreateSubmit(
            create_url,
            self.editor,
            {"identifier": "ident", "key": "secret"},
            new_obj_query=HelpdeskImport.objects.filter(
                org=self.org, knowledge=self.helpdesk, import_type=HelpdeskImport.TYPE_CRISP, created_by=self.editor
            ),
        )

        imp = HelpdeskImport.objects.get()
        self.assertEqual(HelpdeskImport.STATUS_COMPLETE, imp.status)
        self.assertEqual({"identifier": "ident", "website_id": WEBSITE_ID, "locale": "en"}, imp.config)
        self.assertEqual(4, self.helpdesk.articles.count())

        # while one is running, the dialog offers nothing but to wait
        imp.status = HelpdeskImport.STATUS_PROCESSING
        imp.save(update_fields=("status",))

        response = self.assertCreateFetch(create_url, [self.admin], form_fields=("identifier", "key", "website_id"))
        self.assertEqual("existing-import", response.context["blocker"])
        self.assertContains(response, "An import is already in progress.")

        response = self.requestView(
            create_url, self.admin, post_data={"identifier": "ident", "key": "secret"}, choose_org=self.org
        )
        self.assertEqual(200, response.status_code)
        self.assertContains(response, "An import is already in progress.")
        self.assertEqual(1, HelpdeskImport.objects.count())

    def test_status(self):
        status_url = reverse("knowledge.helpdeskimport_status")
        self.assertEqual("/helpdeskimport/status/", status_url)

        self.assertRequestDisallowed(status_url, [None, self.agent])

        response = self.requestView(status_url, self.editor)
        self.assertEqual({"results": []}, response.json())

        imp = HelpdeskImport.create(self.helpdesk, self.admin, HelpdeskImport.TYPE_CRISP, {})
        imp.set_total(10)
        imp.advance()

        response = self.requestView(status_url, self.editor)
        self.assertEqual(
            {
                "id": imp.id,
                "status": "Pending",
                "created_on": imp.created_on.isoformat(),
                "modified_on": imp.modified_on.isoformat(),
                "progress": {"total": 10, "current": 1},
                "error": None,
            },
            response.json()["results"][0],
        )

    def test_list_shows_import(self):
        list_url = reverse("knowledge.article_list")

        # nothing to say until there's an import
        response = self.requestView(list_url, self.admin)
        self.assertNotIn("helpdesk_import", response.context)
        self.assertNotContains(response, 'id="import-card"')

        # one underway is shown with its progress and kept current
        imp = HelpdeskImport.create(self.helpdesk, self.admin, HelpdeskImport.TYPE_CRISP, {})

        response = self.requestView(list_url, self.admin)
        self.assertEqual(imp, response.context["helpdesk_import"])
        self.assertEqual(reverse("knowledge.helpdeskimport_status"), response.context["import_status_url"])
        self.assertContains(response, "Importing from Crisp")
        self.assertContains(response, "pollHelpdeskImport(1)")

        # one that failed says why
        imp.status = HelpdeskImport.STATUS_FAILED
        imp.error = "Crisp did not accept the API key."
        imp.save(update_fields=("status", "error"))

        response = self.requestView(list_url, self.admin)
        self.assertEqual(imp, response.context["helpdesk_import"])
        self.assertEqual(reverse("knowledge.helpdeskimport_create"), response.context["import_url"])
        self.assertContains(response, "The import from Crisp did not finish.")
        self.assertContains(response, "Crisp did not accept the API key.")
        self.assertContains(response, "Try Again")
        self.assertNotContains(response, "pollHelpdeskImport(1)")

        # and one that finished is nothing to mention
        imp.status = HelpdeskImport.STATUS_COMPLETE
        imp.save(update_fields=("status",))

        response = self.requestView(list_url, self.admin)
        self.assertNotIn("helpdesk_import", response.context)
