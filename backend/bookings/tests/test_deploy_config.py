from pathlib import Path


def test_nginx_explicitly_denies_private_document_prefixes():
    repository_root = Path(__file__).resolve().parents[3]
    config = (repository_root / "deploy/almalinux/nginx-immploy.conf").read_text()
    catch_all = config.index("    location / {")

    for prefix in ("/media/", "/private-media/"):
        block = f"    location ^~ {prefix} {{\n        return 404;\n    }}"
        assert block in config
        assert config.index(block) < catch_all


def test_production_frontend_build_explicitly_disables_source_maps():
    repository_root = Path(__file__).resolve().parents[3]
    config = (repository_root / "frontend/vite.config.ts").read_text()

    assert "build: {" in config
    assert "sourcemap: false" in config


def test_nginx_denies_accidentally_deployed_source_files_and_maps():
    repository_root = Path(__file__).resolve().parents[3]
    config = (repository_root / "deploy/almalinux/nginx-immploy.conf").read_text()
    catch_all = config.index("    location / {")

    source_block = """    location ~* \\.(?:map|py|pyc|pyo|ts|tsx)$ {
        return 404;
    }"""
    hidden_file_block = """    location ~ /\\. {
        return 404;
    }"""
    assert source_block in config
    assert hidden_file_block in config
    assert config.index(source_block) < catch_all
    assert config.index(hidden_file_block) < catch_all


def test_nginx_balances_api_and_admin_across_two_local_backends_without_post_retry():
    repository_root = Path(__file__).resolve().parents[3]
    config = (repository_root / "deploy/almalinux/nginx-immploy.conf").read_text()

    assert "upstream immploy_app {" in config
    assert "least_conn;" in config
    assert "server 127.0.0.1:8001 max_fails=3 fail_timeout=10s;" in config
    assert "server 127.0.0.1:8002 max_fails=3 fail_timeout=10s;" in config
    assert "proxy_pass http://immploy_app;" in config
    assert "proxy_next_upstream error timeout http_502 http_503 http_504;" in config
    assert "proxy_next_upstream_tries 2;" in config
    assert "non_idempotent" not in config


def test_web_instance_template_preserves_total_concurrency_and_systemd_hardening():
    repository_root = Path(__file__).resolve().parents[3]
    service = (
        repository_root / "deploy/almalinux/immploy-web@.service"
    ).read_text()

    assert "User=immploy" in service
    assert "Group=immploy" in service
    assert "--bind 127.0.0.1:%i" in service
    assert "--workers 1 --threads 2" in service
    assert "NoNewPrivileges=true" in service
    assert "PrivateTmp=true" in service
    assert "ProtectSystem=full" in service
    assert "ProtectHome=true" in service


def test_installer_starts_balanced_instances_before_retiring_legacy_listener():
    repository_root = Path(__file__).resolve().parents[3]
    installer = (repository_root / "deploy/almalinux/install-server").read_text()

    assert 'install -m 0644 "${deploy_root}/immploy-web@.service"' in installer
    assert "immploy-web@8001.service immploy-web@8002.service" in installer
    assert "systemctl reload nginx" in installer
    assert "systemctl cat immploy.service" in installer
    assert "systemctl disable --now immploy.service" in installer
    assert installer.index("systemctl reload nginx") < installer.index(
        "systemctl disable --now immploy.service"
    )


def test_hostname_rollout_restarts_and_verifies_both_balanced_instances():
    repository_root = Path(__file__).resolve().parents[3]
    rollout = (
        repository_root / "deploy/almalinux/add-booking-hostname"
    ).read_text()

    assert "immploy-web@8001.service immploy-web@8002.service nginx.service" in rollout
    assert "systemctl restart immploy.service" not in rollout
    assert "systemctl is-active --quiet immploy.service" not in rollout


def test_sms_outbox_timer_uses_the_protected_application_environment():
    repository_root = Path(__file__).resolve().parents[3]
    deploy_root = repository_root / "deploy/almalinux"
    service = (deploy_root / "immploy-sms.service").read_text()
    timer = (deploy_root / "immploy-sms.timer").read_text()
    installer = (deploy_root / "install-server").read_text()

    assert "User=immploy" in service
    assert "Group=immploy" in service
    assert "EnvironmentFile=/etc/immploy/immploy.env" in service
    assert 'ExecCondition=/usr/bin/test -n "${SMS_MYMOBILEAPI_CLIENT_ID}"' in service
    assert 'ExecCondition=/usr/bin/test -n "${SMS_MYMOBILEAPI_SECRET}"' in service
    assert "manage.py send_sms_outbox --limit 100" in service
    assert "NoNewPrivileges=true" in service
    assert "ProtectSystem=full" in service
    assert "OnUnitActiveSec=1min" in timer
    assert "Persistent=true" in timer
    assert 'install -m 0644 "${deploy_root}/immploy-sms.service"' in installer
    assert 'install -m 0644 "${deploy_root}/immploy-sms.timer"' in installer
    assert "immploy-sms.timer" in installer
    assert "SMS_MYMOBILEAPI_CLIENT_ID=\\n" in installer
    assert "SMS_MYMOBILEAPI_SECRET=\\n" in installer
