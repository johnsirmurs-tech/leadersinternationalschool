import os
import sys

print(">>> STARTUP BEGINNING", flush=True)
print(f">>> Python: {sys.version}", flush=True)
print(f">>> Working dir: {os.getcwd()}", flush=True)

# Print ALL environment variables (safe ones)
print(">>> Environment check:", flush=True)
for key in ['DATABASE_URL', 'SECRET_KEY', 'DEBUG',
            'ALLOWED_HOSTS', 'PORT', 'DJANGO_SETTINGS_MODULE']:
    val = os.environ.get(key, 'NOT SET')
    if key == 'SECRET_KEY' and val != 'NOT SET':
        val = val[:8] + '...(hidden)'
    if key == 'DATABASE_URL' and val != 'NOT SET':
        val = val[:30] + '...(hidden)'
    print(f"    {key} = {val}", flush=True)

# Step 1: Test Django import
print("\n>>> Testing Django import...", flush=True)
try:
    os.environ.setdefault(
        'DJANGO_SETTINGS_MODULE', 'school_erp.settings'
    )
    import django
    print(f">>> Django version: {django.get_version()}", flush=True)
except Exception as e:
    print(f">>> FAILED importing Django: {e}", flush=True)
    sys.exit(1)

# Step 2: Test settings load
print("\n>>> Loading Django settings...", flush=True)
try:
    django.setup()
    from django.conf import settings
    print(f">>> Settings loaded OK", flush=True)
    print(f">>> DATABASES engine: {settings.DATABASES['default']['ENGINE']}", flush=True)
    db_name = settings.DATABASES['default'].get('NAME', 'unknown')
    if hasattr(db_name, '__str__'):
        db_name = str(db_name)
    print(f">>> DATABASES name: {db_name[:30]}", flush=True)
except Exception as e:
    print(f">>> FAILED loading settings: {e}", flush=True)
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Step 3: Test database connection
print("\n>>> Testing database connection...", flush=True)
try:
    from django.db import connection
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
    print(">>> Database connection OK", flush=True)
except Exception as e:
    print(f">>> FAILED database connection: {e}", flush=True)
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Step 4: Run migrations
print("\n>>> Running migrations...", flush=True)
try:
    from django.core.management import call_command
    call_command('migrate', '--noinput', verbosity=2)
    print(">>> Migrations OK", flush=True)
except Exception as e:
    print(f">>> FAILED migrations: {e}", flush=True)
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Step 5: Collect static files
print("\n>>> Collecting static files...", flush=True)
try:
    call_command('collectstatic', '--noinput', verbosity=0)
    print(">>> Static files OK", flush=True)
except Exception as e:
    print(f">>> WARNING static files: {e}", flush=True)
    # Don't exit - static files failing shouldn't stop the app

# Step 6: Start gunicorn
port = os.environ.get('PORT', '8000')
print(f"\n>>> Starting Gunicorn on port {port}...", flush=True)
print(">>> All checks passed!", flush=True)

os.execvp('gunicorn', [
    'gunicorn',
    'school_erp.wsgi:application',
    '--bind', f'0.0.0.0:{port}',
    '--workers', '2',
    '--timeout', '120',
    '--log-level', 'debug',
    '--access-logfile', '-',
    '--error-logfile', '-',
    '--capture-output',
])
