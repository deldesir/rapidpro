"""
Bringing a help site over from Crisp.

Crisp's helpdesk is a flat set of categories with articles filed under them, which maps straight onto the helpdesk
here - a category becomes a section, an article an article under it. Each keeps its Crisp id as its uuid, so
links between articles resolve, an import can be run again over what it brought before, and the site's old
addresses can be pointed at their new pages.
"""

import logging
import re
import time
from urllib.parse import urlparse
from uuid import UUID, uuid5

import magic
import requests

from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils.translation import gettext_lazy as _

from temba.utils import languages

from .models import Article, ArticleImage, HelpSite

logger = logging.getLogger(__name__)


class CrispError(Exception):
    """
    Something Crisp said no to, with what a user can do about it.
    """

    pass


class CrispClient:
    """
    The few reads of Crisp's REST API an import needs, authenticated as a plugin - the kind of token a workspace makes
    for itself in Crisp's marketplace, as an identifier and a key.
    """

    BASE_URL = "https://api.crisp.chat/v1"

    STORAGE_URL = "https://storage.crisp.chat/"

    MAX_ATTEMPTS = 5
    TIMEOUT = 30

    def __init__(self, identifier: str, key: str):
        self.auth = (identifier, key)

    def get_websites(self) -> list:
        """
        The ids of the websites the token has access to.
        """
        return [w["website_id"] for w in self._get("/plugin/connect/websites/all")]

    def get_helpdesk(self, website_id: str) -> dict:
        """
        The website's helpdesk - its name and the public URL it's served on.
        """
        return self._get(f"/website/{website_id}/helpdesk")

    def get_locales(self, website_id: str) -> list:
        return self._paginate(f"/website/{website_id}/helpdesk/locales")

    def get_categories(self, website_id: str, locale: str) -> list:
        return self._paginate(f"/website/{website_id}/helpdesk/locale/{locale}/categories")

    def get_articles(self, website_id: str, locale: str) -> list:
        """
        Every article's metadata - listings carry everything but the body.
        """
        return self._paginate(f"/website/{website_id}/helpdesk/locale/{locale}/articles")

    def get_article(self, website_id: str, locale: str, article_id: str) -> dict:
        """
        An article in full - the only read that returns its body.
        """
        return self._get(f"/website/{website_id}/helpdesk/locale/{locale}/article/{article_id}")

    def download(self, url: str, max_size: int) -> tuple[bytes, str] | None:
        """
        Fetches one of the site's images from Crisp's storage, with its sniffed content type - or nothing if it
        can't be had or is too big.
        """
        try:
            response = requests.get(url, timeout=self.TIMEOUT, stream=True)
            if response.status_code != 200:
                return None

            content = b""
            for chunk in response.iter_content(chunk_size=64 * 1024):
                content += chunk
                if len(content) > max_size:
                    return None
        except requests.RequestException:
            return None

        return content, magic.from_buffer(content[:2048], mime=True)

    def _paginate(self, path: str) -> list:
        """
        Crisp pages by a number on the end of the path, and signals the end with an empty page.
        """
        items, page = [], 1
        while True:
            batch = self._get(f"{path}/{page}")
            if not batch:
                return items
            items.extend(batch)
            page += 1

    def _get(self, path: str):
        for attempt in range(self.MAX_ATTEMPTS):
            try:
                response = requests.get(
                    f"{self.BASE_URL}{path}",
                    auth=self.auth,
                    headers={"X-Crisp-Tier": "plugin"},
                    timeout=self.TIMEOUT,
                )
            except requests.RequestException:
                response = None

            # a rate limit or a wobble on their side is waited out, anything else is answered now
            if response is not None and response.status_code not in (429, 500, 502, 503):
                break

            time.sleep(2**attempt)
        else:
            raise CrispError(_("Crisp could not be reached. Please try again later."))

        if response.status_code in (401, 403):
            raise CrispError(_("Crisp did not accept the API key."))
        if response.status_code == 404:
            raise CrispError(_("Crisp has no helpdesk for that website."))
        if response.status_code not in (200, 206):
            raise CrispError(_("Crisp returned an unexpected response."))

        return response.json()["data"]


class CrispImporter:
    """
    Walks a Crisp helpdesk and writes it into ours, reporting progress on the import it's doing.
    """

    # Crisp sizes an image with a trailing "=WxH" inside the link, which isn't markdown anywhere else - we carry a
    # size as a fragment, capped to the sizes the renderer knows
    SIZED_IMAGE = re.compile(r"!\[(?P<alt>[^\]]*)\]\((?P<url>[^)\s]+)\s*=(?P<width>\d*)x(?P<height>\d*)\)")
    STORAGE_URL = re.compile(r"https://storage\.crisp\.chat/[^)\s#\"'<>]+")

    # a page of the site, linked absolutely or relatively - its short id on the end of the slug is what's stable
    # across retitling, so that's what the link is resolved by
    SLUG_SHORT_ID = re.compile(r"-([a-z0-9]+)$")

    # an article keeps Crisp's id as its uuid where it can, so a re-import finds it again. Uuids are unique across
    # workspaces though, so when another has an article by that id already - the same site imported twice - the
    # id is derived from it and the workspace instead, just as findably
    UUID_NAMESPACE = UUID("6c1f0f1e-3b3a-4b0e-9f0e-1b2c3d4e5f60")

    UNCATEGORIZED = "Uncategorized"

    def __init__(self, imp):
        self.imp = imp
        self.helpdesk = imp.knowledge
        self.user = imp.created_by
        self.client = CrispClient(imp.identifier, imp.key)
        self.website_id = imp.website_id
        self.locale = imp.locale

    def run(self):
        site_url = self.client.get_helpdesk(self.website_id).get("url") or ""
        categories = self.client.get_categories(self.website_id, self.locale)
        listings = self.client.get_articles(self.website_id, self.locale)

        self.imp.set_total(len(categories) + len(listings))

        self.uuids = self._resolve_uuids([c["category_id"] for c in categories] + [a["article_id"] for a in listings])

        existing = {str(a.uuid) for a in self.helpdesk.articles.filter(is_active=True).only("uuid")}
        num_new = len([u for u in self.uuids.values() if u not in existing])
        if len(existing) + num_new > Article.MAX_ARTICLES:
            raise CrispError(_("The helpdesk would exceed its limit of %d articles.") % Article.MAX_ARTICLES)

        site = HelpSite.get_or_create(self.helpdesk, self.user)
        self.link_pattern = self._link_pattern(site_url)
        self.targets = self._targets(categories, listings)
        self.language = languages.alpha2_to_alpha3(self.locale) or self.helpdesk.org.flow_languages[0]

        sections = {}
        redirects = {}
        for category in categories:
            section = self._import_section(category)
            sections[category["category_id"]] = section
            if category.get("url"):
                redirects[HelpSite.normalize_path(urlparse(category["url"]).path)] = str(section.uuid)
            self.imp.advance()

        for listing in listings:
            category = listing.get("category") or {}
            section = sections.get(category.get("category_id")) or self._uncategorized(sections)
            article = self._import_article(listing, section)
            if listing.get("url"):
                redirects[HelpSite.normalize_path(urlparse(listing["url"]).path)] = str(article.uuid)
            self.imp.advance()

        site.redirects = {**site.redirects, **redirects}
        site.modified_by = self.user
        site.save(update_fields=("redirects", "modified_by", "modified_on"))

    def _import_section(self, category: dict) -> Article:
        section = self._existing(category["category_id"])
        title = self._title(category["name"])
        description = (category.get("description") or "")[: Article.MAX_DESCRIPTION_LEN]

        if section:
            section.parent = None
            section.title = title
            section.slug = Article.get_unique_slug(self.helpdesk, title, ignore=section)
            section.description = description
            section.is_active = True
            section.modified_by = self.user
            section.save()
        else:
            section = Article.create(self.helpdesk, self.user, title, description=description, language=self.language)
            section.uuid = self.uuids[category["category_id"]]
            section.save(update_fields=("uuid",))

        if section.status != Article.STATUS_PUBLISHED:
            section.publish(self.user)

        return section

    def _uncategorized(self, sections: dict) -> Article:
        """
        A section for the articles Crisp has in none - made once, and found again on a later import.
        """
        section = sections.get(None)
        if not section:
            section = self.helpdesk.articles.filter(parent=None, title=self.UNCATEGORIZED, is_active=True).first()
            if not section:
                section = Article.create(self.helpdesk, self.user, self.UNCATEGORIZED, language=self.language)
            sections[None] = section

        if section.status != Article.STATUS_PUBLISHED:
            section.publish(self.user)

        return section

    def _import_article(self, listing: dict, section: Article) -> Article:
        detail = self.client.get_article(self.website_id, self.locale, listing["article_id"])
        title = self._title(detail.get("title") or listing.get("title") or "")
        body = self._convert(detail.get("content") or "")

        article = self._existing(listing["article_id"])
        if article:
            article.parent = section
            article.title = title
            article.slug = Article.get_unique_slug(self.helpdesk, title, ignore=article)
            article.language = self.language
            article.is_active = True
            article.modified_by = self.user
        else:
            article = Article.create(self.helpdesk, self.user, title, parent=section, language=self.language)
            article.uuid = self.uuids[listing["article_id"]]

        article.body = self._localize_images(article, body)
        article.save()

        # Crisp keeps a published article hidden as its own state - here that's a draft
        published = listing.get("status") == "published" and listing.get("visibility", "visible") == "visible"
        if published and article.status != Article.STATUS_PUBLISHED:
            article.publish(self.user)
        elif not published and article.status == Article.STATUS_PUBLISHED:
            article.unpublish(self.user)

        return article

    def _existing(self, crisp_id: str) -> Article | None:
        """
        The article a Crisp one is here already, if it is - a deleted one included, which the import brings back.
        """
        return self.helpdesk.articles.filter(uuid=self.uuids[crisp_id]).first()

    def _resolve_uuids(self, crisp_ids: list) -> dict:
        """
        The uuid each Crisp id is or will be here: what it's under already if it's here, else Crisp's own id if no
        workspace has taken it, else one derived for this workspace.
        """
        derived = {i: str(uuid5(self.UUID_NAMESPACE, f"{self.helpdesk.org_id}:{i}")) for i in crisp_ids}
        taken = {
            str(a.uuid): a.knowledge_id
            for a in Article.objects.filter(uuid__in=set(crisp_ids) | set(derived.values())).only(
                "uuid", "knowledge_id"
            )
        }

        resolved = {}
        for crisp_id in crisp_ids:
            if taken.get(derived[crisp_id]) == self.helpdesk.id:
                resolved[crisp_id] = derived[crisp_id]
            elif crisp_id not in taken or taken[crisp_id] == self.helpdesk.id:
                resolved[crisp_id] = crisp_id
            else:
                resolved[crisp_id] = derived[crisp_id]
        return resolved

    def _title(self, title: str) -> str:
        return title.strip()[: Article.MAX_TITLE_LEN] or "Untitled"

    def _convert(self, body: str) -> str:
        """
        Crisp's markdown into ours - sized images carried as fragments, links between pages of the site resolved
        to the articles they'll be here.
        """
        body = self.SIZED_IMAGE.sub(self._resize_image, body)
        body = self.link_pattern.sub(self._resolve_link, body)
        return body[: Article.MAX_BODY_LEN]

    def _resize_image(self, match) -> str:
        largest = max(int(match["width"] or 0), int(match["height"] or 0))
        size = "small" if largest <= 200 else ("medium" if largest <= 400 else "large")
        url = match["url"]
        joiner = "&" if "#" in url else "#"
        return f"![{match['alt']}]({url}{joiner}size={size})"

    def _resolve_link(self, match) -> str:
        short_id = self.SLUG_SHORT_ID.search(match["slug"].strip("/"))
        target = self.targets.get((match["kind"], short_id[1])) if short_id else None
        return f"](article:{self.uuids[target]})" if target else match[0]

    @classmethod
    def _link_pattern(cls, site_url: str) -> re.Pattern:
        host = re.escape(urlparse(site_url).netloc) if site_url else None
        origin = rf"(?:https?://{host})?" if host else ""
        return re.compile(
            rf"\]\({origin}/[a-z]{{2}}(?:-[a-z]{{2}})?/(?P<kind>article|category)/(?P<slug>[^)\s?#]+)(?:[?#][^)\s]*)?\)"
        )

    @classmethod
    def _targets(cls, categories: list, listings: list) -> dict:
        """
        What the site's addresses link to, by kind and short id - only pages with a public address can be linked to.
        """
        targets = {}
        for kind, items, key in (("category", categories, "category_id"), ("article", listings, "article_id")):
            for item in items:
                path = urlparse(item.get("url") or "").path.strip("/")
                short_id = cls.SLUG_SHORT_ID.search(path.rsplit("/", 1)[-1])
                if short_id:
                    targets[(kind, short_id[1])] = item[key]
        return targets

    def _localize_images(self, article: Article, body: str) -> str:
        """
        Brings the body's images over from Crisp's storage into ours, rewriting each reference to the key it's kept
        under - the same thing the editor writes for an upload. One that can't be brought over stays where it was.
        """
        existing = {image.name: image for image in article.images.all()}
        num_images = len(existing)

        def localize(match) -> str:
            nonlocal num_images

            url = match[0]
            name = url.rsplit("/", 1)[-1]
            image = existing.get(name)

            if not image and num_images < ArticleImage.MAX_IMAGES:
                downloaded = self.client.download(url, ArticleImage.MAX_UPLOAD_SIZE)
                if downloaded and ArticleImage.is_allowed_type(downloaded[1]):
                    upload = SimpleUploadedFile(name, downloaded[0], content_type=downloaded[1])
                    image = existing[name] = ArticleImage.from_upload(article, self.user, upload)
                    num_images += 1

            return image.path if image else url

        return self.STORAGE_URL.sub(localize, body)
