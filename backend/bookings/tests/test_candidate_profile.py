from datetime import date

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from rest_framework.test import APIClient

from bookings.models import (
    Candidate,
    CandidateChangeAudit,
    CandidateProfileOption,
    LegacyUserProfile,
    Profession,
)


@pytest.fixture
def candidate_editor(db):
    user = get_user_model().objects.create_user(
        username="profile-editor",
        is_staff=True,
    )
    user.user_permissions.add(Permission.objects.get(codename="manage_bookings"))
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _synthetic_id(date_part, sequence, citizenship="0", marker="8"):
    first_twelve = f"{date_part}{sequence}{citizenship}{marker}"
    provisional = f"{first_twelve}0"
    digits = [int(value) for value in provisional]
    parity = len(digits) % 2
    total = 0
    for index, value in enumerate(digits):
        if index % 2 == parity:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return f"{first_twelve}{(10 - total % 10) % 10}"


def _option(category, legacy_id, label, parent_id=None):
    return CandidateProfileOption.objects.create(
        category=category,
        legacy_mysql_id=legacy_id,
        label=label,
        parent_legacy_mysql_id=parent_id,
    )


@pytest.mark.django_db
def test_candidate_profile_options_are_server_backed_and_dependent(candidate_editor):
    _option(CandidateProfileOption.Category.EMPLOYMENT_EQUITY, 14, "Other/Unspecified")
    _option(CandidateProfileOption.Category.PROVINCE, 208, "Western Cape")
    _option(CandidateProfileOption.Category.SUBURB, 9001, "Example Suburb", 208)
    _option(CandidateProfileOption.Category.LANGUAGE, 100, "English")
    _option(CandidateProfileOption.Category.QUALIFICATION_TYPE, 501, "Ward Nurse", 81)

    response = candidate_editor.get("/api/candidates/creation-options/")

    assert response.status_code == 200
    profile = response.json()["profile"]
    assert profile["employment_equity"] == [
        {"id": 14, "label": "Other/Unspecified"}
    ]
    assert profile["languages"] == [{"id": 100, "label": "English"}]
    assert profile["qualification_types"] == [
        {"id": 501, "label": "Ward Nurse", "parent_id": 81}
    ]


@pytest.mark.django_db
def test_booking_only_legacy_user_cannot_read_candidate_profile_options():
    user = get_user_model().objects.create_user(username="booking-only", is_staff=True)
    LegacyUserProfile.objects.create(
        user=user,
        legacy_mysql_id=99001,
        link_conf=True,
        edit_cand=False,
    )
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.get("/api/candidates/creation-options/")

    assert response.status_code == 403
    assert client.get("/api/candidates/1/profile/").status_code == 403
    assert client.post(
        "/api/candidates/decode-sa-id/",
        {"identity_number": "not-provided"},
        format="json",
    ).status_code == 403


@pytest.mark.django_db
def test_valid_sa_id_derives_dob_and_sex_but_not_employment_equity(candidate_editor):
    profession = Profession.objects.create(name="Profile Role")
    candidate = Candidate.objects.create(first_name="Profile", last_name="Subject")
    candidate.professions.add(profession)
    _option(CandidateProfileOption.Category.EMPLOYMENT_EQUITY, 14, "Other/Unspecified")
    identity_number = _synthetic_id("000101", "4000")

    decoded = candidate_editor.post(
        "/api/candidates/decode-sa-id/",
        {"identity_number": identity_number},
        format="json",
    )

    assert decoded.status_code == 200
    assert decoded.json() == {
        "date_of_birth": "2000-01-01",
        "sex": "female",
        "sex_source": "sa_id",
        "citizenship_status": "citizen",
    }

    response = candidate_editor.patch(
        f"/api/candidates/{candidate.id}/profile/",
        {
            "identity_number": identity_number,
            "is_sa_id": True,
            "date_of_birth": "1999-12-31",
            "sex": "male",
            "employment_equity": "Other/Unspecified",
        },
        format="json",
    )

    assert response.status_code == 200
    assert response.json()["date_of_birth"] == "2000-01-01"
    assert response.json()["sex"] == "female"
    assert response.json()["sex_source"] == "sa_id"
    assert response.json()["employment_equity"] == "Other/Unspecified"
    candidate.refresh_from_db()
    assert candidate.date_of_birth == date(2000, 1, 1)
    assert candidate.sex == Candidate.Sex.FEMALE
    audit = CandidateChangeAudit.objects.get(candidate=candidate)
    assert "identity_number" in audit.changed_fields
    assert "identity_number" not in audit.before
    assert "identity_number" not in audit.after


@pytest.mark.django_db
def test_candidate_profile_rejects_unknown_dropdown_and_invalid_sa_id(candidate_editor):
    profession = Profession.objects.create(name="Validation Role")
    candidate = Candidate.objects.create(first_name="Validation", last_name="Subject")
    candidate.professions.add(profession)

    unknown_option = candidate_editor.patch(
        f"/api/candidates/{candidate.id}/profile/",
        {"employment_equity": "Invented option"},
        format="json",
    )
    invalid_id = candidate_editor.patch(
        f"/api/candidates/{candidate.id}/profile/",
        {"identity_number": "not-valid", "is_sa_id": True},
        format="json",
    )

    assert unknown_option.status_code == 400
    assert set(unknown_option.json()) == {"employment_equity"}
    assert invalid_id.status_code == 400
    assert set(invalid_id.json()) == {"identity_number"}
    assert "not-valid" not in str(invalid_id.json())


@pytest.mark.django_db
def test_compliance_fields_require_compliance_authority(candidate_editor):
    profession = Profession.objects.create(name="Compliance Boundary Role")
    candidate = Candidate.objects.create(first_name="Compliance", last_name="Boundary")
    candidate.professions.add(profession)
    _option(CandidateProfileOption.Category.FINGERPRINT_STATUS, 218, "Has Fingerprint")
    _option(CandidateProfileOption.Category.CRIMINAL_CHECK, 220, "Has Criminal Check")

    response = candidate_editor.patch(
        f"/api/candidates/{candidate.id}/profile/",
        {
            "fingerprint_status": "Has Fingerprint",
            "criminal_check": "Has Criminal Check",
        },
        format="json",
    )

    assert response.status_code == 400
    assert set(response.json()) == {"fingerprint_status", "criminal_check"}


@pytest.mark.django_db
def test_unchanged_historical_identity_does_not_block_unrelated_profile_edit(candidate_editor):
    profession = Profession.objects.create(name="Historical identity role")
    candidate = Candidate.objects.create(
        first_name="Historical",
        last_name="Identity",
        identity_number="legacy-unvalidated-value",
        is_sa_id=True,
        date_of_birth=date(1990, 1, 1),
        sex=Candidate.Sex.FEMALE,
        sex_source=Candidate.SexSource.LEGACY,
        is_active=True,
    )
    candidate.professions.add(profession)

    response = candidate_editor.patch(
        f"/api/candidates/{candidate.id}/profile/",
        {
            "identity_number": candidate.identity_number,
            "is_sa_id": True,
            "date_of_birth": "1990-01-01",
            "sex": Candidate.Sex.FEMALE,
            "email": "updated@example.test",
            "profession_ids": [profession.id],
        },
        format="json",
    )

    assert response.status_code == 200
    candidate.refresh_from_db()
    assert candidate.email == "updated@example.test"


@pytest.mark.django_db
def test_full_profile_preserves_sex_source_until_sex_or_sa_id_flag_changes(candidate_editor):
    profession = Profession.objects.create(name="Sex Source Role")
    candidate = Candidate.objects.create(
        first_name="Source",
        last_name="Preserved",
        sex=Candidate.Sex.FEMALE,
        sex_source=Candidate.SexSource.LEGACY,
    )
    candidate.professions.add(profession)

    unchanged = candidate_editor.patch(
        f"/api/candidates/{candidate.id}/profile/",
        {"email": "source@example.test", "sex": "female"},
        format="json",
    )
    assert unchanged.status_code == 200
    candidate.refresh_from_db()
    assert candidate.sex_source == Candidate.SexSource.LEGACY

    candidate.is_sa_id = True
    candidate.identity_number = "legacy-unvalidated"
    candidate.sex_source = Candidate.SexSource.SA_ID
    candidate.citizenship_status = Candidate.CitizenshipStatus.CITIZEN
    candidate.save(
        update_fields=[
            "is_sa_id",
            "identity_number",
            "sex_source",
            "citizenship_status",
        ]
    )

    removed = candidate_editor.patch(
        f"/api/candidates/{candidate.id}/profile/",
        {"is_sa_id": False, "sex": "female"},
        format="json",
    )
    assert removed.status_code == 200
    candidate.refresh_from_db()
    assert candidate.sex_source == Candidate.SexSource.MANUAL
    assert candidate.citizenship_status == ""


@pytest.mark.django_db
def test_qualification_types_must_match_selected_candidate_roles(candidate_editor):
    nursing = Profession.objects.create(name="Ward Nurse", legacy_mysql_id=501)
    Profession.objects.create(name="Pharmacy Role", legacy_mysql_id=502)
    candidate = Candidate.objects.create(first_name="Linked", last_name="Qualification")
    candidate.professions.add(nursing)
    _option(CandidateProfileOption.Category.QUALIFICATION_TYPE, 501, "Ward Nurse", 81)
    _option(CandidateProfileOption.Category.QUALIFICATION_TYPE, 502, "Pharmacy Role", 84)

    rejected = candidate_editor.patch(
        f"/api/candidates/{candidate.id}/profile/",
        {"profession_ids": [nursing.id], "qualification_types": ["Pharmacy Role"]},
        format="json",
    )
    accepted = candidate_editor.patch(
        f"/api/candidates/{candidate.id}/profile/",
        {"profession_ids": [nursing.id], "qualification_types": ["Ward Nurse"]},
        format="json",
    )

    assert rejected.status_code == 400
    assert set(rejected.json()) == {"qualification_types"}
    assert accepted.status_code == 200
    assert accepted.json()["qualification_types"] == ["Ward Nurse"]


@pytest.mark.django_db
def test_bulk_candidate_directory_excludes_expanded_sensitive_profile_fields(candidate_editor):
    profession = Profession.objects.create(name="Directory Privacy Role")
    candidate = Candidate.objects.create(
        first_name="Directory",
        last_name="Privacy",
        identity_number="not-a-real-identity",
        passport_number="not-a-real-passport",
        home_phone="private-home-contact",
        other_contact="private-other-contact",
        physical_address="private-address",
        note="private-note",
        employment_equity="private-demographic-value",
    )
    candidate.professions.add(profession)

    response = candidate_editor.get("/api/candidates/")

    assert response.status_code == 200
    payload = next(row for row in response.json() if row["id"] == candidate.id)
    assert {
        "identity_number",
        "passport_number",
        "home_phone",
        "other_contact",
        "physical_address",
        "note",
        "employment_equity",
        "date_of_birth",
        "sex",
        "citizenship_status",
    }.isdisjoint(payload)
