#!/bin/bash
python manage.py migrate && gunicorn school_erp.wsgi:application --bind 0.0.0.0:${PORT:-8000}
