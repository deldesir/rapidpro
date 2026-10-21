from django.db import migrations

from temba.knowledge.models import inspect_body


def backfill_article_info(apps, schema_editor):  # pragma: no cover
    Article = apps.get_model("knowledge", "Article")

    num_updated = 0

    # every article gets the info saving it would give it. Updated rather than saved so modified_on stays put and
    # nothing looks stale to the indexer.
    for article in Article.objects.filter(info={}).only("id", "body").order_by("id").iterator():
        Article.objects.filter(id=article.id).update(info=inspect_body(article.body))
        num_updated += 1

    if num_updated:
        print(f"Backfilled info for {num_updated} articles")


def apply_manual():  # pragma: no cover
    from django.apps import apps

    backfill_article_info(apps, None)


class Migration(migrations.Migration):
    dependencies = [
        ("knowledge", "0012_article_info"),
    ]

    operations = [
        migrations.RunPython(backfill_article_info, migrations.RunPython.noop),
    ]
