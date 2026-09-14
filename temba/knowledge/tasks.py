from django.conf import settings
from django.utils import timezone

from temba.utils.crons import cron_task
from temba.utils.models import delete_in_batches

from .models import ArticleCount


@cron_task(lock_timeout=7200)
def squash_article_counts():
    ArticleCount.squash()


@cron_task()
def trim_article_counts():
    trim_before = (timezone.now() - settings.RETENTION_PERIODS["articlecount"]).date()

    num_deleted = delete_in_batches(ArticleCount.objects.filter(day__lt=trim_before))

    return {"deleted": num_deleted}
