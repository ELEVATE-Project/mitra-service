# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

datas = collect_data_files('coreschema')
hiddenimports =  ['rest_framework_simplejwt', 'rest_framework_simplejwt.authentication.JWTAuthentication'
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
    'urls','shikshalokam_mohini.asgi', 'shikshalokam_mohini.urls','channels_redis',
    'channels_redis.core',
    'channels_redis.client',
    'channels_redis.protocol',
    'channels_redis.persistence',
    'channels_redis.exceptions',
    'channels_redis.router',
]

a = Analysis(
    ['/home/ubuntu/shikshalokam-mohini-service/shikshalokam-mohini-service/manage.py'],
    pathex=['/home/ubuntu/shikshalokam-mohini-service/shikshalokam-mohini-service'],
    binaries=[],
    datas=datas,
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
    a.binaries,
    a.datas,
    [],
    name='manage',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
