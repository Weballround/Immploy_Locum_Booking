from datetime import date
from decimal import Decimal
import importlib
import json

import pytest
from django.core.management import CommandError, call_command
from django.apps import apps

from bookings.models import (
    Candidate,
    CandidateProfileOption,
    Client,
    ClientProfessionRate,
    FacilityExperience,
    Profession,
)


def test_rate_constraint_migration_preflights_existing_negative_values():
    migration = importlib.import_module(
        "bookings.migrations.0014_add_client_rate_checks"
    )

    class ExistingRates:
        def filter(self, *args, **kwargs):
            return self

        def exists(self):
            return True

    class RateModel:
        objects = ExistingRates()

    class HistoricalApps:
        def get_model(self, app_label, model_name):
            assert (app_label, model_name) == ("bookings", "ClientProfessionRate")
            return RateModel

    with pytest.raises(RuntimeError, match="negative legacy rates"):
        migration.validate_nonnegative_rates(HistoricalApps(), None)


def test_legacy_experience_query_excludes_future_completed_rows():
    from bookings.management.commands.sync_legacy_mysql import Command

    assert "item.date <= CURRENT_DATE" in Command._experiences_sql()


def test_legacy_candidate_query_uses_the_latest_worked_population_from_august_2025():
    from bookings.management.commands.sync_legacy_mysql import Command

    sql = Command._candidates_sql()

    assert "MAX(timesheet.date_from) AS max_date" in sql
    assert "timesheet.date_from >= '2025-08-01'" in sql
    assert "timesheet.date_from <= CURRENT_DATE" in sql
    assert "GROUP BY timesheet.cand_no" in sql
    assert "latest.cand_no = candidate.no" in sql
    assert "WHERE candidate.is_locum" not in sql
    assert "WHERE candidate.dormant" not in sql
    assert "timesheet.desk IN" not in sql
    for alias in (
        "preferred_name",
        "date_of_birth",
        "identity_number",
        "passport_number",
        "home_language_id",
        "employment_equity_id",
        "qualification_type_ids",
        "other_language_ids",
    ):
        assert alias in sql
    assert "DATE_FORMAT(candidate.DOB, '%Y-%m-%d')" in sql
    assert "DATE_FORMAT(candidate.visa_start, '%Y-%m-%d')" in sql
    assert "DATE_FORMAT(candidate.visa_end, '%Y-%m-%d')" in sql


def test_legacy_candidate_profile_option_query_uses_authoritative_lookups():
    from bookings.management.commands.sync_legacy_mysql import Command

    sql = Command._candidate_profile_options_sql()

    assert "tbl_job_cj_countries" in sql
    assert "tbl_visa_types" in sql
    assert "tbl_candidates_detail_types_items" in sql
    assert "tbl_candidates_detail_types_sub_items" in sql
    assert "'employment_equity' AS category" in sql
    assert "'qualification_type' AS category" in sql
    assert "'suburb' AS category" in sql


def test_legacy_date_normalization_rejects_malformed_historical_values():
    from bookings.management.commands.sync_legacy_mysql import Command

    assert Command._legacy_date(date(1990, 1, 1)) == date(1990, 1, 1)
    assert Command._legacy_date("2000-02-29") == date(2000, 2, 29)
    assert Command._legacy_date("19") is None
    assert Command._legacy_date("0000-00-00") is None


def test_legacy_client_query_requires_recent_approved_desk_activity():
    from bookings.management.commands.sync_legacy_mysql import Command

    sql = Command._clients_sql()

    assert "SELECT DISTINCT timesheet.client_no" in sql
    assert "recent_timesheet.client_no = client.no" in sql
    assert "timesheet.date_from >= DATE_SUB(CURRENT_DATE, INTERVAL 12 MONTH)" in sql
    assert "timesheet.date_from <= CURRENT_DATE" in sql
    assert "timesheet.desk IN (1, 2, 3, 5, 9)" in sql


def test_legacy_department_query_selects_only_the_five_active_locum_desks():
    from bookings.management.commands.sync_legacy_mysql import Command

    sql = Command._departments_sql()

    assert "desk.no IN (1, 2, 3, 5, 9)" in sql
    assert "desk.desk_name AS name" in sql


@pytest.mark.django_db
def test_legacy_sync_activates_only_supplied_departments_and_retains_stale_history():
    from bookings.management.commands.sync_legacy_mysql import Command

    department_model = apps.get_model("bookings", "Department")
    stale = department_model.objects.create(
        legacy_mysql_id=6,
        name="Permanent",
        is_active=True,
    )
    dataset = {
        "departments": [
            {"legacy_id": 1, "name": "Doctors"},
            {"legacy_id": 2, "name": "Allied"},
            {"legacy_id": 3, "name": "Nursing"},
            {"legacy_id": 5, "name": "Assisted Care"},
            {"legacy_id": 9, "name": "Radiology"},
        ],
        "roles": [],
        "clients": [],
        "client_rates": [],
        "candidates": [],
        "candidate_roles": [],
        "experiences": [],
    }

    imported = Command().sync_dataset(dataset)

    assert imported["departments"] == 5
    assert set(
        department_model.objects.filter(is_active=True).values_list(
            "legacy_mysql_id", flat=True
        )
    ) == {1, 2, 3, 5, 9}
    stale.refresh_from_db()
    assert stale.is_active is False
    assert department_model.objects.filter(pk=stale.pk).exists()


@pytest.mark.django_db
def test_legacy_sync_preserves_locally_managed_profile_for_qualifying_candidate():
    from bookings.management.commands.sync_legacy_mysql import Command

    local_role = Profession.objects.create(name="Locally managed role")
    candidate = Candidate.objects.create(
        legacy_mysql_id=7001,
        first_name="Locally",
        last_name="Managed",
        email="managed@example.test",
        phone="+271****0000",
        preferred_name="Locally preferred",
        employment_equity="Other/Unspecified",
        home_area="Managed area",
        home_region="Managed region",
        postal_code="2000",
        is_active=True,
        compliance_status=Candidate.ComplianceStatus.CLEARED,
        profile_locally_managed=True,
    )
    candidate.professions.add(local_role)
    dataset = {
        "departments": [],
        "roles": [{"legacy_id": 3001, "name": "Source role"}],
        "clients": [],
        "client_rates": [],
        "candidates": [{
            "legacy_id": 7001,
            "first_name": "Source",
            "last_name": "Overwrite",
            "home_area": "Source area",
            "home_region": "Source region",
            "preferred_name": "Source preferred",
            "employment_equity_id": 11,
            "compliance_code": 0,
        }],
        "candidate_roles": [{"candidate_id": 7001, "role_id": 3001}],
        "experiences": [],
    }

    Command().sync_dataset(dataset)

    candidate.refresh_from_db()
    assert candidate.first_name == "Locally"
    assert candidate.last_name == "Managed"
    assert candidate.email == "managed@example.test"
    assert candidate.phone == "+271****0000"
    assert candidate.preferred_name == "Locally preferred"
    assert candidate.employment_equity == "Other/Unspecified"
    assert candidate.home_area == "Managed area"
    assert candidate.home_region == "Managed region"
    assert candidate.postal_code == "2000"
    assert candidate.is_active is True
    assert candidate.compliance_status == Candidate.ComplianceStatus.PENDING
    assert list(candidate.professions.values_list("name", flat=True)) == [
        "Locally managed role"
    ]


@pytest.mark.django_db
def test_legacy_sync_imports_profile_options_and_expanded_candidate_fields():
    from bookings.management.commands.sync_legacy_mysql import Command

    dataset = {
        "departments": [],
        "roles": [],
        "clients": [],
        "client_rates": [],
        "candidate_profile_options": [
            {"category": "language", "legacy_id": 99, "label": "English", "parent_id": None},
            {"category": "employment_equity", "legacy_id": 14, "label": "Other/Unspecified", "parent_id": None},
            {"category": "province", "legacy_id": 208, "label": "Western Cape", "parent_id": None},
            {"category": "suburb", "legacy_id": 801, "label": "Example Suburb", "parent_id": 208},
        ],
        "candidates": [{
            "legacy_id": 8001,
            "first_name": "Expanded",
            "last_name": "Profile",
            "preferred_name": "Preferred",
            "date_of_birth": date(1990, 1, 1),
            "identity_number": "",
            "is_sa_id": 0,
            "passport_number": "",
            "visa_type_id": 0,
            "visa_start": None,
            "visa_end": None,
            "visa_selected": 0,
            "country_origin_id": 0,
            "nationality_id": 0,
            "home_language_id": 99,
            "is_locum": 1,
            "is_permanent": 0,
            "email": "expanded@example.test",
            "phone": "+271****0000",
            "home_phone": "",
            "other_contact": "",
            "physical_address": "",
            "postal_code": "2000",
            "note": "",
            "division_id": 0,
            "consultant_id": 0,
            "sex_id": 7,
            "employment_equity_id": 14,
            "is_disabled": 0,
            "fingerprint_status_id": 0,
            "criminal_check_id": 0,
            "drivers_license_id": 0,
            "owns_car": 0,
            "qualification_id": 0,
            "qualification_type_ids": "",
            "education_level_id": 0,
            "source_id": 0,
            "marital_status_id": 0,
            "other_language_ids": "99;",
            "home_area": "Example Suburb",
            "home_region": "Kwazulu Natal",
            "compliance_code": 0,
        }],
        "candidate_roles": [],
        "experiences": [],
    }

    imported = Command().sync_dataset(dataset)

    candidate = Candidate.objects.get(legacy_mysql_id=8001)
    assert imported["candidate_profile_options"] == 4
    assert candidate.preferred_name == "Preferred"
    assert candidate.date_of_birth == date(1990, 1, 1)
    assert candidate.home_language == "English"
    assert candidate.employment_equity == "Other/Unspecified"
    assert candidate.sex == Candidate.Sex.FEMALE
    assert candidate.sex_source == Candidate.SexSource.LEGACY
    assert candidate.other_languages == ["English"]
    assert candidate.home_region == "KwaZulu-Natal"
    assert CandidateProfileOption.objects.get(
        category=CandidateProfileOption.Category.SUBURB,
        legacy_mysql_id=801,
    ).parent_legacy_mysql_id == 208


@pytest.mark.django_db
def test_legacy_sync_imports_active_client_role_links_and_normal_rates():
    from bookings.management.commands.sync_legacy_mysql import Command

    dataset = {
        "roles": [{"legacy_id": 1201, "name": "Theatre Nurse"}],
        "clients": [{
            "legacy_id": 901,
            "name": "Fast Facility",
            "region": "Gauteng",
            "city": "Johannesburg",
        }],
        "client_rates": [{
            "legacy_id": 4401,
            "client_id": 901,
            "role_id": 1201,
            "pay_rate": Decimal("245.50"),
            "bill_rate": Decimal("455.75"),
        }],
        "candidates": [],
        "candidate_roles": [],
        "experiences": [],
    }

    Command().sync_dataset(dataset)

    rate_model = apps.get_model("bookings", "ClientProfessionRate")
    rate = rate_model.objects.select_related("client", "profession").get()
    assert rate.legacy_mysql_id == 4401
    assert rate.client.legacy_mysql_id == 901
    assert rate.profession.legacy_mysql_id == 1201
    assert rate.pay_rate == Decimal("245.50")
    assert rate.bill_rate == Decimal("455.75")


@pytest.mark.django_db
def test_legacy_sync_preserves_a_locally_managed_client_rate():
    from bookings.management.commands.sync_legacy_mysql import Command

    dataset = {
        "roles": [{"legacy_id": 1201, "name": "Theatre Nurse"}],
        "clients": [{
            "legacy_id": 901,
            "name": "Fast Facility",
            "region": "Gauteng",
            "city": "Johannesburg",
        }],
        "client_rates": [{
            "legacy_id": 4401,
            "client_id": 901,
            "role_id": 1201,
            "pay_rate": Decimal("245.50"),
            "bill_rate": Decimal("455.75"),
        }],
        "candidates": [],
        "candidate_roles": [],
        "experiences": [],
    }
    command = Command()
    command.sync_dataset(dataset)
    rate = ClientProfessionRate.objects.get()
    rate.pay_rate = Decimal("300.00")
    rate.bill_rate = Decimal("520.00")
    rate.locally_managed = True
    rate.save()

    dataset["client_rates"][0]["pay_rate"] = Decimal("250.00")
    dataset["client_rates"][0]["bill_rate"] = Decimal("460.00")
    command.sync_dataset(dataset)

    preserved = ClientProfessionRate.objects.get()
    assert preserved.pk == rate.pk
    assert preserved.legacy_mysql_id == 4401
    assert preserved.pay_rate == Decimal("300.00")
    assert preserved.bill_rate == Decimal("520.00")
    assert preserved.locally_managed is True


@pytest.mark.django_db
def test_legacy_sync_rejects_negative_rates_without_persisting_partial_data():
    from bookings.management.commands.sync_legacy_mysql import Command

    dataset = {
        "roles": [{"legacy_id": 1201, "name": "Theatre Nurse"}],
        "clients": [{
            "legacy_id": 901,
            "name": "Invalid Rate Facility",
            "region": "Gauteng",
            "city": "Johannesburg",
        }],
        "client_rates": [{
            "legacy_id": 4401,
            "client_id": 901,
            "role_id": 1201,
            "pay_rate": Decimal("-1.00"),
            "bill_rate": Decimal("455.75"),
        }],
        "candidates": [],
        "candidate_roles": [],
        "experiences": [],
    }

    with pytest.raises(CommandError, match="cannot contain negative"):
        Command().sync_dataset(dataset)

    rate_model = apps.get_model("bookings", "ClientProfessionRate")
    assert rate_model.objects.count() == 0
    assert Client.objects.filter(name="Invalid Rate Facility").count() == 0


@pytest.mark.parametrize(
    "profile",
    [
        [],
        {
            "host": "legacy.invalid",
            "port": "not-a-port",
            "user": "reader",
            "password": "not-used",
        },
    ],
)
def test_legacy_sync_rejects_malformed_connection_profiles(tmp_path, profile):
    from bookings.management.commands.sync_legacy_mysql import Command

    config_path = tmp_path / "legacy-profile.json"
    config_path.write_text(json.dumps(profile))

    with pytest.raises(CommandError, match="Unable to read the protected MySQL profile"):
        Command().read_dataset(config_path)


@pytest.mark.django_db
def test_legacy_sync_preserves_same_name_clients_with_distinct_legacy_ids():
    from bookings.management.commands.sync_legacy_mysql import Command

    existing = Client.objects.create(
        name="Shared Facility Name",
        legacy_mysql_id=101,
    )

    Command().sync_dataset({
        "roles": [],
        "clients": [{
            "legacy_id": 202,
            "name": "Shared Facility Name",
            "region": "Gauteng",
            "city": "Johannesburg",
        }],
        "candidates": [],
        "candidate_roles": [],
        "experiences": [],
    })

    existing.refresh_from_db()
    assert existing.legacy_mysql_id == 101
    assert set(
        Client.objects.filter(name="Shared Facility Name").values_list(
            "legacy_mysql_id", flat=True
        )
    ) == {101, 202}


@pytest.mark.django_db
def test_legacy_sync_can_link_an_unmapped_local_client_by_name():
    from bookings.management.commands.sync_legacy_mysql import Command

    existing = Client.objects.create(name="Unmapped Facility")

    Command().sync_dataset({
        "roles": [],
        "clients": [{
            "legacy_id": 303,
            "name": "Unmapped Facility",
            "region": "Western Cape",
            "city": "Cape Town",
        }],
        "candidates": [],
        "candidate_roles": [],
        "experiences": [],
    })

    existing.refresh_from_db()
    assert existing.legacy_mysql_id == 303


@pytest.mark.django_db
def test_legacy_sync_deactivates_stale_clients_without_deleting_history():
    from bookings.management.commands.sync_legacy_mysql import Command

    stale = Client.objects.create(name="Old Facility", legacy_mysql_id=101)

    Command().sync_dataset({
        "roles": [],
        "clients": [{
            "legacy_id": 202,
            "name": "Recently Used Facility",
            "region": "Western Cape",
            "city": "Cape Town",
        }],
        "client_rates": [],
        "candidates": [],
        "candidate_roles": [],
        "experiences": [],
    })

    stale.refresh_from_db()
    recent = Client.objects.get(legacy_mysql_id=202)
    assert getattr(stale, "is_active", None) is False
    assert getattr(recent, "is_active", None) is True


@pytest.mark.django_db
def test_sync_legacy_mysql_imports_roles_candidates_and_aggregated_history(monkeypatch):
    from bookings.management.commands.sync_legacy_mysql import Command

    dataset = {
        "roles": [
            {"legacy_id": 1201, "name": "Theatre Nurse"},
            {"legacy_id": 1202, "name": "Theatre Nurse"},
        ],
        "clients": [
            {
                "legacy_id": 901,
                "name": "Rosebank Surgical Centre",
                "region": "Gauteng",
                "city": "Johannesburg",
            }
        ],
        "candidates": [
            {
                "legacy_id": 501,
                "first_name": "Lerato",
                "last_name": "Maseko",
                "email": "legacy@example.test",
                "phone": "+27000000000",
                "postal_code": "2193",
                "home_area": "Parktown",
                "home_region": "Gauteng",
                "compliance_code": 216,
            }
        ],
        "candidate_roles": [
            {"candidate_id": 501, "role_id": 1201},
            {"candidate_id": 501, "role_id": 1202},
        ],
        "experiences": [
            {
                "candidate_id": 501,
                "client_id": 901,
                "role_id": 1201,
                "completed_shift_count": 8,
                "total_hours": Decimal("84.00"),
                "last_worked_on": date(2026, 6, 14),
            },
            {
                "candidate_id": 501,
                "client_id": 901,
                "role_id": 1202,
                "completed_shift_count": 2,
                "total_hours": Decimal("16.00"),
                "last_worked_on": date(2026, 5, 10),
            },
        ],
    }
    monkeypatch.setattr(Command, "read_dataset", lambda self, config_path: dataset)

    call_command("sync_legacy_mysql", config="/protected/local/config.json")

    candidate = Candidate.objects.get(legacy_mysql_id=501)
    client = Client.objects.get(legacy_mysql_id=901)
    profession = Profession.objects.get(legacy_mysql_id=1201)
    assert candidate.compliance_status == Candidate.ComplianceStatus.CLEARED
    assert list(candidate.professions.all()) == [profession]
    experience = FacilityExperience.objects.get(
        candidate=candidate,
        client=client,
        profession=profession,
    )
    assert experience.completed_shift_count == 10
    assert experience.total_hours == Decimal("100.00")
    assert experience.last_worked_on == date(2026, 6, 14)

    monkeypatch.setattr(
        Command,
        "read_dataset",
        lambda self, path: {
            "roles": [],
            "clients": [],
            "candidates": [],
            "candidate_roles": [],
            "experiences": [],
        },
    )
    call_command("sync_legacy_mysql", config="/ignored")

    candidate.refresh_from_db()
    assert candidate.is_active is False
    assert candidate.email == ""
    assert candidate.phone == ""
    assert candidate.postal_code == ""
    assert not FacilityExperience.objects.filter(candidate=candidate).exists()