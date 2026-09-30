# Spotter Trip Planner — Backend

Django REST backend for the Spotter full-stack developer assessment. It resolves trip locations, calculates an HGV route, applies the assessment HOS planning model, and generates 24-hour daily ELD log data.

## Stack

- Python 3.11+
- Django 5.2
- Django REST Framework
- HeiGIT/openrouteservice geocoding and HGV directions
- Gunicorn for production WSGI serving
- WhiteNoise for Django static assets
- pytest + pytest-django

## Local setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Set `ORS_API_KEY` in `.env`, then run:

```powershell
python manage.py check
pytest
python manage.py runserver
```

API base URL: `http://127.0.0.1:8000/api`

Health check: `GET /api/health/`

Trip planning: `POST /api/trips/plan/`

## Environment variables

| Variable | Purpose |
| --- | --- |
| `DEBUG` | Django debug mode. Must be `False` in production. |
| `SECRET_KEY` | Django secret key. Use a unique production secret. |
| `ORS_API_KEY` | HeiGIT/openrouteservice API key. |
| `ALLOWED_HOSTS` | Comma-separated backend hostnames. |
| `CORS_ALLOWED_ORIGINS` | Comma-separated frontend origins including scheme. |
| `CSRF_TRUSTED_ORIGINS` | Trusted HTTPS origins when required. |
| `SECURE_SSL_REDIRECT` | Redirect HTTP to HTTPS when enabled. |
| `SESSION_COOKIE_SECURE` | Secure session cookies in production. |
| `CSRF_COOKIE_SECURE` | Secure CSRF cookies in production. |
| `SECURE_HSTS_SECONDS` | HSTS duration; `0` disables HSTS. |
| `WEB_CONCURRENCY` | Gunicorn worker count. Defaults to 2. |
| `GUNICORN_TIMEOUT` | Gunicorn request timeout. Defaults to 90 seconds. |
| `PORT` | Runtime HTTP port supplied by the hosting platform. |

Use `.env.example` for local development and `.env.production.example` as the production checklist. Do not commit a real `.env`.

## Production commands

Install dependencies and collect static assets:

```bash
pip install -r requirements.txt
python manage.py collectstatic --noinput
python manage.py check --deploy
```

Run the application:

```bash
gunicorn config.wsgi:application -c gunicorn.conf.py
```

The hosting-provider-specific build/start commands can be wired to these commands during deployment.

## Architecture

```text
POST /api/trips/plan/
  -> request validation
  -> geocoding
  -> HGV routing
  -> HOS scheduling
  -> daily ELD log generation
  -> normalized JSON response
```

Core domain services live in `trips/services/` and are independent of the HTTP layer wherever possible.

## HOS modeling notes

The assessment supplies current 70-hour-cycle usage but not the driver's previous eight days or current 11/14-hour clock state. The planner therefore uses the documented assumptions in `docs/assumptions.md`, including fresh daily clocks at trip start and a 34-hour restart when the modeled cycle budget is exhausted.

## Verification

```bash
python manage.py check
pytest
```
