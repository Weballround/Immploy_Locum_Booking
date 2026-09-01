#!/usr/bin/env python3
"""Start the IMMploy Booking development system for local and trusted-LAN HTTPS access."""

from __future__ import annotations

import argparse
import ipaddress
import os
from pathlib import Path
import shutil
import signal
import socket
import ssl
import subprocess
import sys
import threading
import time
from typing import Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
BACKEND_DIR = ROOT / "backend"
FRONTEND_DIR = ROOT / "frontend"
DEFAULT_FRONTEND_PORT = 5173
DEFAULT_BACKEND_PORT = 8000


def validate_lan_ip(value: str) -> str:
    """Return a canonical private IPv4 LAN address or raise ValueError."""
    try:
        address = ipaddress.ip_address(value)
    except ValueError as error:
        raise ValueError(f"Invalid LAN IP address: {value}") from error
    if address.version != 4 or not address.is_private or address.is_loopback:
        raise ValueError("LAN IP must be a private, non-loopback IPv4 address.")
    return str(address)


def detect_lan_ip() -> str:
    """Discover the IPv4 address selected by the host's default route."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        try:
            probe.connect(("10.255.255.255", 1))
            detected = probe.getsockname()[0]
        except OSError as error:
            raise RuntimeError("Could not detect a LAN IP; pass --lan-ip explicitly.") from error
    return validate_lan_ip(detected)


def build_access_urls(lan_ip: str, frontend_port: int) -> list[str]:
    return [
        f"https://127.0.0.1:{frontend_port}",
        f"https://localhost:{frontend_port}",
        f"https://{lan_ip}:{frontend_port}",
    ]


def build_backend_environment(
    lan_ip: str,
    frontend_port: int,
    secret_path: Path,
    *,
    base_environment: Mapping[str, str] | None = None,
) -> dict[str, str]:
    try:
        secret_key = secret_path.read_text(encoding="utf-8").strip()
    except FileNotFoundError as error:
        raise RuntimeError(f"Missing development signing key: {secret_path}") from error
    if not secret_key:
        raise RuntimeError(f"Development signing key is empty: {secret_path}")

    environment = dict(base_environment if base_environment is not None else os.environ)
    origins = build_access_urls(lan_ip, frontend_port)
    environment.update({
        "DJANGO_DEBUG": "true",
        "DJANGO_ALLOWED_HOSTS": f"127.0.0.1,localhost,{lan_ip}",
        "DJANGO_CSRF_TRUSTED_ORIGINS": ",".join(origins),
        "DJANGO_SECRET_KEY": secret_key,
    })
    environment.pop("PYTHONPATH", None)
    return environment


def port_available(host: str, port: int) -> bool:
    connect_host = "127.0.0.1" if host == "0.0.0.0" else host
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.1)
        if probe.connect_ex((connect_host, port)) == 0:
            return False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            listener.bind((host, port))
        except OSError:
            return False
    return True


def certificate_paths(lan_ip: str) -> tuple[Path, Path]:
    certificate_dir = ROOT / ".lan-certs"
    return (
        certificate_dir / f"{lan_ip}-cert.pem",
        certificate_dir / f"{lan_ip}-key.pem",
    )


def validate_certificate(certificate: Path, private_key: Path, lan_ip: str) -> None:
    for path, label in ((certificate, "certificate"), (private_key, "private key")):
        if not path.is_file():
            raise RuntimeError(f"Missing HTTPS {label}: {path}")
    if private_key.stat().st_mode & 0o077:
        raise RuntimeError(f"HTTPS private key must be owner-only: {private_key}")

    decoded = ssl._ssl._test_decode_cert(str(certificate))  # type: ignore[attr-defined]
    names = set(decoded.get("subjectAltName", ()))
    required = {
        ("IP Address", "127.0.0.1"),
        ("IP Address", lan_ip),
        ("DNS", "localhost"),
    }
    missing = required - names
    if missing:
        formatted = ", ".join(value for _, value in sorted(missing))
        raise RuntimeError(f"HTTPS certificate is missing SAN coverage for: {formatted}")


def probe_url(url: str, *, certificate: Path | None = None, timeout: float = 2.0) -> int:
    context = ssl.create_default_context(cafile=str(certificate)) if certificate else None
    request = Request(url, headers={"User-Agent": "immploy-booking-launcher/1"})
    try:
        with urlopen(request, timeout=timeout, context=context) as response:
            return response.status
    except HTTPError as error:
        return error.code
    except (URLError, TimeoutError, OSError) as error:
        raise RuntimeError(f"Could not reach {url}: {error}") from error


def wait_until_ready(
    processes: list[subprocess.Popen[bytes]],
    lan_ip: str,
    frontend_port: int,
    backend_port: int,
    certificate: Path,
    timeout: float,
) -> None:
    checks = [
        (f"http://127.0.0.1:{backend_port}/api/session/", None),
        *[(f"{url}/", certificate) for url in build_access_urls(lan_ip, frontend_port)],
        (f"https://{lan_ip}:{frontend_port}/api/session/", certificate),
    ]
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        for process in processes:
            if process.poll() is not None:
                raise RuntimeError(
                    f"A server exited during startup with status {process.returncode}."
                )
        try:
            statuses = [(url, probe_url(url, certificate=cert)) for url, cert in checks]
            if all(status == 200 for _, status in statuses):
                return
            last_error = RuntimeError(
                "; ".join(f"{url} returned {status}" for url, status in statuses)
            )
        except RuntimeError as error:
            last_error = error
        time.sleep(0.25)
    raise RuntimeError(f"Servers were not ready within {timeout:g}s: {last_error}")


def stop_processes(processes: list[subprocess.Popen[bytes]]) -> None:
    for process in reversed(processes):
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
    deadline = time.monotonic() + 5
    for process in reversed(processes):
        remaining = max(0.0, deadline - time.monotonic())
        try:
            process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Start IMMploy Booking on loopback and the trusted LAN over HTTPS."
    )
    parser.add_argument("--lan-ip", help="Private LAN IPv4 address (auto-detected by default).")
    parser.add_argument("--frontend-port", type=int, default=DEFAULT_FRONTEND_PORT)
    parser.add_argument("--backend-port", type=int, default=DEFAULT_BACKEND_PORT)
    parser.add_argument("--startup-timeout", type=float, default=30.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        lan_ip = validate_lan_ip(args.lan_ip) if args.lan_ip else detect_lan_ip()
        certificate, private_key = certificate_paths(lan_ip)
        validate_certificate(certificate, private_key, lan_ip)

        python = ROOT / ".venv" / "bin" / "python"
        npm = shutil.which("npm")
        secret_path = BACKEND_DIR / ".django-dev-key"
        if not python.is_file():
            raise RuntimeError(f"Missing project Python environment: {python}")
        if npm is None:
            raise RuntimeError("npm is not installed or is not available on PATH.")
        if not (FRONTEND_DIR / "node_modules").is_dir():
            raise RuntimeError("Frontend dependencies are missing; run npm install in frontend/.")
        if not port_available("127.0.0.1", args.backend_port):
            raise RuntimeError(f"Backend port {args.backend_port} is already in use.")
        if not port_available("0.0.0.0", args.frontend_port):
            raise RuntimeError(f"Frontend port {args.frontend_port} is already in use.")

        backend_environment = build_backend_environment(
            lan_ip, args.frontend_port, secret_path
        )
        frontend_environment = dict(os.environ)
        frontend_environment.update({
            "VITE_LAN_HOST": "0.0.0.0",
            "VITE_HTTPS_CERT": str(certificate),
            "VITE_HTTPS_KEY": str(private_key),
        })

        subprocess.run(
            [str(python), "manage.py", "check"],
            cwd=BACKEND_DIR,
            env=backend_environment,
            check=True,
        )

        processes: list[subprocess.Popen[bytes]] = []
        stop_event = threading.Event()

        def request_stop(_signum: int, _frame: object) -> None:
            stop_event.set()

        previous_sigint = signal.signal(signal.SIGINT, request_stop)
        previous_sigterm = signal.signal(signal.SIGTERM, request_stop)
        try:
            print("Starting Django on http://127.0.0.1:%d" % args.backend_port, flush=True)
            processes.append(subprocess.Popen(
                [str(python), "manage.py", "runserver", f"127.0.0.1:{args.backend_port}", "--noreload"],
                cwd=BACKEND_DIR,
                env=backend_environment,
                start_new_session=True,
            ))
            print("Starting Vite HTTPS on 0.0.0.0:%d" % args.frontend_port, flush=True)
            processes.append(subprocess.Popen(
                [npm, "run", "dev", "--", "--port", str(args.frontend_port), "--strictPort"],
                cwd=FRONTEND_DIR,
                env=frontend_environment,
                start_new_session=True,
            ))

            wait_until_ready(
                processes,
                lan_ip,
                args.frontend_port,
                args.backend_port,
                certificate,
                args.startup_timeout,
            )
            print("\nIMMploy Booking is ready:", flush=True)
            for url in build_access_urls(lan_ip, args.frontend_port):
                print(f"  {url}/", flush=True)
            print("  API proxy: verified through the LAN HTTPS URL", flush=True)
            print("Press Ctrl+C to stop both servers.\n", flush=True)

            while not stop_event.wait(0.5):
                for process in processes:
                    if process.poll() is not None:
                        raise RuntimeError(
                            f"A server exited unexpectedly with status {process.returncode}."
                        )
        finally:
            stop_processes(processes)
            signal.signal(signal.SIGINT, previous_sigint)
            signal.signal(signal.SIGTERM, previous_sigterm)
            print("IMMploy Booking servers stopped.", flush=True)
    except (RuntimeError, ValueError, subprocess.CalledProcessError) as error:
        print(f"ERROR: {error}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
