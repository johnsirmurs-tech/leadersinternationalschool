#!/bin/bash
python manage.py migrate && python manage.py setup_initial_data && gunicorn school_erp.wsgi:application --bind 0.0.0.0:${PORT:-8000}
