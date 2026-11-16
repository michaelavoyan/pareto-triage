from celery import shared_task


@shared_task
def rebuild_index():
    return 1
