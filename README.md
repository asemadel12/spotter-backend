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

Trip planning: `POST /api/trips/plan/`\n\nLocation autocomplete: `GET /api/locations/autocomplete/?q=...`

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

## Project structure

```text
config/                         # Django project/runtime configuration
docs/
└─ assumptions.md               # Explicit assessment/HOS assumptions

trips/
├─ api/
│  ├─ serializers.py            # HTTP request validation
│  ├─ errors.py                 # Controlled exception -> API response mapping
│  ├─ urls.py                   # Public API routes
│  └─ views.py                  # Thin HTTP transport layer
├─ application/
│  ├─ exceptions.py             # Use-case-level exceptions
│  └─ planning.py               # Trip-planning orchestration/use case
├─ services/
│  ├─ geocoding.py              # HeiGIT/Pelias location resolution + autocomplete
│  ├─ routing.py                # HGV road snapping + route retrieval + normalization
│  ├─ hos.py                    # Pure HOS scheduling engine
│  ├─ daily_logs.py             # 24-hour ELD log builder
│  └─ exceptions.py             # Controlled upstream routing errors
└─ tests/
   ├─ factories.py              # Shared deterministic route/schedule fixtures
   ├─ test_trip_plan_api.py     # HTTP contract/error behavior
   ├─ test_trip_planning_application.py
   ├─ test_hos_*.py             # HOS rule/constraint coverage
   ├─ test_daily_log_*.py       # ELD daily-log coverage
   ├─ test_geocoding.py
   └─ test_routing.py
```

### Layer boundaries

- `api/` owns HTTP concerns only: request validation, status codes, and public error payloads.
- `application/` coordinates the complete trip-planning use case without knowing about DRF responses.
- `services/geocoding.py` and `services/routing.py` isolate external HeiGIT/openrouteservice behavior and normalize upstream responses.
- Routing prefers the `driving-hgv` profile. If HeiGIT returns a client-side unroutable-point response for that profile, the backend retries once with `driving-car` so valid user locations do not fail solely because of HGV graph snapping. Upstream outages and server errors are never hidden by this fallback.
- `services/hos.py` owns HOS scheduling and route-progress consumption.
- `services/daily_logs.py` converts the generated schedule into complete 24-hour ELD logs.
- Domain engines do not call the API layer and do not depend on DRF.
- Tests are organized by behavioral boundary rather than mirroring implementation line-for-line.

## Architecture

```text
POST /api/trips/plan/
  -> request validation
  -> geocoding
  -> best-effort HGV road snapping
  -> HGV routing
  -> HOS scheduling
  -> daily ELD log generation
  -> normalized JSON response
```

The HTTP layer delegates to `trips/application/planning.py`, which coordinates the isolated services. HOS and daily-log engines remain independent of DRF and HTTP concerns.\n\nLocation autocomplete is an optional UX enhancement. It is proxied through the backend so the API key never reaches the browser, is limited to U.S. results, and degrades to an empty suggestion list if the upstream autocomplete service is unavailable or not configured. Free-text trip planning remains fully functional.

## HOS modeling notes

The assessment supplies current 70-hour-cycle usage but not the driver's previous eight days or current 11/14-hour clock state. The planner therefore uses the documented assumptions in `docs/assumptions.md`, including fresh daily clocks at trip start and a 34-hour restart when the modeled cycle budget is exhausted.

## Verification

```bash
python manage.py check
pytest
```
