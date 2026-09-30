from pathlib import Path

from django.conf import settings


def test_whitenoise_follows_security_middleware():
    security_index = settings.MIDDLEWARE.index(
        "django.middleware.security.SecurityMiddleware"
    )
    whitenoise_index = settings.MIDDLEWARE.index(
        "whitenoise.middleware.WhiteNoiseMiddleware"
    )

    assert whitenoise_index == security_index + 1


def test_static_files_have_production_root_and_manifest_storage():
    assert settings.STATIC_URL == "/static/"
    assert settings.STATIC_ROOT == Path(settings.BASE_DIR) / "staticfiles"
    assert settings.STORAGES["staticfiles"]["BACKEND"] == (
        "whitenoise.storage.CompressedManifestStaticFilesStorage"
    )


def test_runtime_network_settings_are_env_driven_lists():
    assert isinstance(settings.ALLOWED_HOSTS, list)
    assert isinstance(settings.CORS_ALLOWED_ORIGINS, list)
    assert isinstance(settings.CSRF_TRUSTED_ORIGINS, list)
    assert all(isinstance(value, str) for value in settings.ALLOWED_HOSTS)
    assert all(isinstance(value, str) for value in settings.CORS_ALLOWED_ORIGINS)


def test_reverse_proxy_https_header_is_configured():
    assert settings.SECURE_PROXY_SSL_HEADER == (
        "HTTP_X_FORWARDED_PROTO",
        "https",
    )
