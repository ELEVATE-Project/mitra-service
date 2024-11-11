from celery import Celery
import os

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shikshalokam_mohini.settings')

app = Celery('shikshalokam_mohini', backend='redis://localhost', broker='redis://localhost')

# Load configuration from Django settings.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Load task modules from all registered Django app configs.
app.autodiscover_tasks()
if __name__ == '__main__':
    app.start(argv=['-A', 'shikshalokam_mohini.celery_config', 'worker', '--loglevel=info'])
