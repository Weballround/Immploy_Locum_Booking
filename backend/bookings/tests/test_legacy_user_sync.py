import pytest
from django.contrib.auth import authenticate, get_user_model
from django.core.management import call_command, CommandError

from bookings.models import LegacyAccessPreset, LegacyUserProfile


ACCESS_FLAGS = [
    "cap_ts",
    "link_ts",
    "approve_ts",
    "export_ts",
    "link_conf",
    "export_inv",
    "edit_clients",
    "edit_cand",
    "edit_cons",
    "update_client_rates",
    "update_cand_rates",
    "override_can_rates",
    "man_users",
    "view_cons_report",
    "view_client_report",
    "view_can_report",
    "view_com_report",
    "view_profit_report",
    "submit_cand_live",
    "delete_files",
    "set_compliance",
    "assign_cons",
]


def access_flags(**enabled):
    return {name: bool(enabled.get(name, False)) for name in ACCESS_FLAGS}


def test_legacy_user_dry_run_query_does_not_read_passwords():
    from bookings.management.commands.sync_legacy_users import Command

    assert "password AS plaintext_password" not in Command._users_sql(False)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("field", "value"),
    [("username", None), ("dormant", None), ("link_conf", "yes")],
)
def test_sync_legacy_users_rejects_malformed_security_fields(monkeypatch, field, value):
    from bookings.management.commands.sync_legacy_users import Command

    row = {
        "legacy_id": 1,
        "access_type": 0,
        "username": "valid-user",
        "plaintext_password": "valid-password",
        "dormant": False,
        "assigned_desk": 0,
        "first_name": "Valid",
        "last_name": "User",
        "email": "",
        **access_flags(link_conf=True),
    }
    row[field] = value
    monkeypatch.setattr(
        Command,
        "read_dataset",
        lambda self, path, **kwargs: {"presets": [], "users": [row]},
    )

    with pytest.raises(CommandError, match="invalid security data"):
        call_command("sync_legacy_users", config="/ignored")


@pytest.mark.django_db
def test_sync_legacy_users_rehashes_passwords_and_imports_access_rules(monkeypatch):
    from bookings.management.commands.sync_legacy_users import Command

    dataset = {
        "presets": [
            {
                "legacy_id": 2,
                "description": "Consultant",
                **access_flags(link_conf=True, edit_clients=True, edit_cand=True),
            }
        ],
        "users": [
            {
                "legacy_id": 99,
                "access_type": 2,
                "username": "LegacyConsultant",
                "plaintext_password": "LegacyPass9",
                "dormant": True,
                "assigned_desk": 4,
                "first_name": "Old",
                "last_name": "Record",
                "email": "old@example.test",
                **access_flags(),
            },
            {
                "legacy_id": 101,
                "access_type": 2,
                "username": "LegacyConsultant",
                "plaintext_password": "LegacyPass9",
                "dormant": False,
                "assigned_desk": 4,
                "first_name": "Legacy",
                "last_name": "Consultant",
                "email": "consultant@example.test",
                **access_flags(link_conf=True, edit_clients=True),
            },
            {
                "legacy_id": 102,
                "access_type": 2,
                "username": "LegacyConsultant",
                "plaintext_password": "WrongDuplicate",
                "dormant": False,
                "assigned_desk": 9,
                "first_name": "Duplicate",
                "last_name": "Record",
                "email": "duplicate@example.test",
                **access_flags(man_users=True),
            },
        ],
    }
    monkeypatch.setattr(Command, "read_dataset", lambda self, path, **kwargs: dataset)

    call_command("sync_legacy_users", config="/ignored")

    user = get_user_model().objects.get(username="LegacyConsultant")
    profile = LegacyUserProfile.objects.get(user=user)
    preset = LegacyAccessPreset.objects.get(legacy_mysql_id=2)
    assert user.is_active is True
    assert user.is_staff is True
    assert user.first_name == "Legacy"
    assert user.check_password("LegacyPass9") is True
    assert user.password != "LegacyPass9"
    assert profile.legacy_mysql_id == 101
    assert profile.preset == preset
    assert profile.link_conf is True
    assert profile.edit_clients is True
    assert profile.man_users is False
    assert authenticate(username="legacyconsultant", password="LegacyPass9") == user
    assert LegacyUserProfile.objects.count() == 1

    monkeypatch.setattr(
        Command,
        "read_dataset",
        lambda self, path, **kwargs: {"presets": dataset["presets"], "users": []},
    )
    call_command("sync_legacy_users", config="/ignored")

    user.refresh_from_db()
    assert user.is_active is False
    assert user.has_usable_password() is False


@pytest.mark.django_db
def test_sync_legacy_users_does_not_overwrite_unlinked_local_account(monkeypatch):
    from bookings.management.commands.sync_legacy_users import Command

    local = get_user_model().objects.create_user(
        username="LocalAdmin",
        password="local-only-password",
        is_staff=True,
    )
    dataset = {
        "presets": [],
        "users": [
            {
                "legacy_id": 500,
                "access_type": 0,
                "username": "localadmin",
                "plaintext_password": "legacy-password",
                "dormant": False,
                "assigned_desk": 0,
                "first_name": "Legacy",
                "last_name": "Collision",
                "email": "legacy@example.test",
                **access_flags(link_conf=True),
            }
        ],
    }
    monkeypatch.setattr(Command, "read_dataset", lambda self, path, **kwargs: dataset)

    call_command("sync_legacy_users", config="/ignored")

    local.refresh_from_db()
    assert local.check_password("local-only-password") is True
    assert LegacyUserProfile.objects.count() == 0
