from types import SimpleNamespace

import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import RequestFactory

from bookings.admin import CandidateAdmin
from bookings.models import Candidate, CandidateChangeAudit, LegacyUserProfile


@pytest.mark.django_db
def test_legacy_admin_without_compliance_authority_sees_compliance_read_only():
    user = get_user_model().objects.create_user(username="admin-without-compliance", is_staff=True)
    LegacyUserProfile.objects.create(
        user=user,
        legacy_mysql_id=99101,
        edit_cand=True,
        set_compliance=False,
    )
    request = RequestFactory().get("/admin/bookings/candidate/")
    request.user = user
    model_admin = CandidateAdmin(Candidate, admin.site)

    assert "compliance_status" in model_admin.get_readonly_fields(request)


@pytest.mark.django_db
def test_authorized_admin_compliance_change_creates_redacted_candidate_audit():
    user = get_user_model().objects.create_superuser(
        username="compliance-superuser",
        email="admin@example.test",
        password="unused-test-password",
    )
    candidate = Candidate.objects.create(first_name="Audit", last_name="Candidate")
    candidate.compliance_status = Candidate.ComplianceStatus.CLEARED
    request = RequestFactory().post("/admin/bookings/candidate/")
    request.user = user
    model_admin = CandidateAdmin(Candidate, admin.site)
    form = SimpleNamespace(changed_data=["compliance_status"])

    model_admin.save_model(request, candidate, form, change=True)

    audit = CandidateChangeAudit.objects.get(candidate=candidate)
    assert audit.changed_by == user
    assert audit.changed_fields == ["compliance_status"]
    assert audit.before == {}
    assert audit.after == {}
