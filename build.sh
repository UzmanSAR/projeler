#!/usr/bin/env bash
# Barındırma hizmetinde her yayında çalışır.
set -o errexit
pip install -r requirements.txt
python manage.py collectstatic --no-input
python manage.py migrate --no-input
if [ "${SEED_DEMO:-0}" = "1" ]; then
  python manage.py seed_demo   # örnek dükkân; varsa tekrar oluşturmaz
fi
