import importlib.util
import socket
from pathlib import Path

import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[3] / "start_booking.py"
SPEC = importlib.util.spec_from_file_location("start_booking", SCRIPT_PATH)
start_booking = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(start_booking)


def test_build_access_urls_includes_loopback_and_lan_https():
    urls = start_booking.build_access_urls("10.0.1.15", 5173)

    assert urls == [
        "https://127.0.0.1:5173",
        "https://localhost:5173",
        "https://10.0.1.15:5173",
    ]


def test_validate_lan_ip_accepts_private_ipv4_and_rejects_unsafe_addresses():
    assert start_booking.validate_lan_ip("10.0.1.15") == "10.0.1.15"

    for value in ("127.0.0.1", "8.8.8.8", "not-an-ip", "::1"):
        with pytest.raises(ValueError):
            start_booking.validate_lan_ip(value)


def test_build_backend_environment_trusts_only_promised_hosts_and_origins(tmp_path):
    secret_path = tmp_path / ".django-dev-key"
    secret_path.write_text("stable-test-secret", encoding="utf-8")

    environment = start_booking.build_backend_environment(
        "10.0.1.15",
        5173,
        secret_path,
        base_environment={"PATH": "/usr/bin"},
    )

    assert environment["DJANGO_DEBUG"] == "true"
    assert environment["DJANGO_ALLOWED_HOSTS"] == "127.0.0.1,localhost,10.0.1.15"
    assert environment["DJANGO_CSRF_TRUSTED_ORIGINS"] == (
        "https://127.0.0.1:5173,https://localhost:5173,https://10.0.1.15:5173"
    )
    assert environment["DJANGO_SECRET_KEY"] == "stable-test-secret"


def test_port_available_detects_an_existing_listener():
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    try:
        assert start_booking.port_available("127.0.0.1", port) is False
    finally:
        listener.close()

    assert start_booking.port_available("127.0.0.1", port) is True
