"""
Railway startup script with verbose error catching.
Replaces direct gunicorn call temporarily for debugging.
"""

import os
import sys
import traceback

print("=" * 60)
print("STARTUP DEBUG SCRIPT")
print("=" * 60)

# Step 1: Check Python
print(f"\n✓ Python version: {sys.version}")

# Step 2: Check environment variables
print("\n── Environment Variables ──")
required_vars = ['SECRET_KEY', 'DATABASE_URL']
optional_vars = [
    'DEBUG', 'ALLOWED_HOSTS', 'OPENAI_API_KEY',
    'EMBEDDING_PROVIDER', 'AI_QUIZ_PROVIDER'
]

all_ok = True
for var in required_vars:
    val = os.environ.get(var)
    if val:
        # Show only first 20 chars for security
        preview = val[:20] + '...' if len(val) > 20 else val
        print(f"  ✓ {var} = {preview}")
    else:
        print(f"  ✗ {var} = NOT SET ← THIS WILL CRASH THE APP")
        all_ok = False

for var in optional_vars:
    val = os.environ.get(var, 'not set')
    preview = val[:30] + '...' if len(val) > 30 else val
    print(f"  ℹ {var} = {preview}")

# Step 3: Check Django settings import
print("\n── Django Settings Import ──")
try:
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'school_erp.settings')
    import django
    django.setup()
    print("  ✓ Django settings loaded successfully")
except Exception as e:
    print(f"  ✗ Django settings FAILED: {e}")
    traceback.print_exc()
    sys.exit(1)

# Step 4: Check database connection
print("\n── Database Connection ──")
try:
    from django.db import connection
    with connection.cursor() as cursor:
        cursor.execute("SELECT version();")
        version = cursor.fetchone()[0]
    print(f"  ✓ Database connected: {version[:50]}")
except Exception as e:
    print(f"  ✗ Database connection FAILED: {e}")
    traceback.print_exc()
    sys.exit(1)

# Step 5: Check migrations
print("\n── Migrations ──")
try:
    from django.db.migrations.executor import MigrationExecutor
    executor = MigrationExecutor(connection)
    plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
    if plan:
        pending = len(plan)
        print(f"  ⚠ {pending} pending migrations")
        # Run them
        from django.core.management import call_command
        call_command('migrate', '--noinput', verbosity=1)
        print("  ✓ Migrations completed")
    else:
        print("  ✓ No pending migrations")
except Exception as e:
    print(f"  ✗ Migration FAILED: {e}")
    traceback.print_exc()
    sys.exit(1)

# Step 6: Check static files
print("\n── Static Files ──")
try:
    from django.conf import settings
    static_root = getattr(settings, 'STATIC_ROOT', None)
    if static_root:
        print(f"  ✓ STATIC_ROOT = {static_root}")
    else:
        print("  ⚠ STATIC_ROOT not set")
except Exception as e:
    print(f"  ✗ Static files check FAILED: {e}")

# Step 7: All checks passed - start gunicorn
print("\n" + "=" * 60)
print("ALL CHECKS PASSED - Starting Gunicorn")
print("=" * 60 + "\n")

port = os.environ.get('PORT', '8000')
workers = 2

os.execv(
    sys.executable,
    [
        sys.executable,
        '-m', 'gunicorn',
        'school_erp.wsgi:application',
        '--bind', f'0.0.0.0:{port}',
        '--workers', str(workers),
        '--timeout', '120',
        '--log-level', 'info',
        '--access-logfile', '-',
        '--error-logfile', '-',
    ]
)
