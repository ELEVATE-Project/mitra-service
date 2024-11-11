# -*- mode: python ; coding: utf-8 -*-
import os
import django
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

venv_path = '/Users/darshil/Desktop/shikshalokam-mohini-service/lib/python3.10/site-packages'
base_dir = '/Users/darshil/Desktop/Private/shikshalokam-mohini-service'
#base_dir = os.path.abspath(os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shikshalokam_mohini.settings')

django.setup()

datas = collect_data_files('coreschema')
datas += collect_data_files('chatbot/templates', 'templates')
datas += collect_data_files('chatbot/static', 'static')

hiddenimports =  [
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.authentication.JWTAuthentication'
    'celery.fixups',
    'celery.fixups.django',
    'kombu.utils',
    'django',
    'django.conf',
    'django.core',
    'django.db',
    'django.db.backends',
    'django.db.backends.sqlite3',
    'django.http',
    'django.urls',
    'django.utils',
    'importlib',
    'celery',
    'celery.app',
    'celery.app.task',
    'celery.loaders',
    'celery.loaders.app',
    'coreschema',
    'ssl',
    'urls',
    'channels_redis',
    'channels_redis.core',
    'channels_redis.client',
    'channels_redis.protocol',
    'channels_redis.persistence',
    'channels_redis.exceptions',
    'channels_redis.router',
    'chatbot.templatetags',
    'import_export.context_processors',
    'jazzmin.context_processors',
    'django.contrib.auth.templatetags',
    'django.contrib.admin.context_processors',
    'django_s3_storage.context_processors',
    'corsheaders.context_processors',
    'tailwind.context_processors',
    'django_countries.context_processors',
    'django.contrib.staticfiles.templatetags',
    'django.contrib.contenttypes.context_processors',
    'rest_framework.context_processors',
    'simple_history.context_processors',
    'daphne.context_processors',
    'daphne.templatetags',
    'mx.DateTime',
    'shikshalokam.templatetags',
    'shikshalokam.context_processors',
    'kombu',
    'django_extensions.mongodb.fields',
    'django.utils.autoreload',
    'shikshalokam_mohini.asgi'
]

a = Analysis(
    ['manage.py'],
    pathex=[base_dir, venv_path],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='manage',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='manage',
)
