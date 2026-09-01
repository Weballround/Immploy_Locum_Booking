from datetime import timedelta

import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client as DjangoClient, RequestFactory
from django.utils import timezone

from bookings.models import (
    Booking,
    Candidate,
    Client,
    Department,
    FinanceExportBatch,
    FinanceSettings,
    Invoice,
    InvoiceLine,
    LegacyUserProfile,
    Profession,
    Shift,
    Site,
    Timesheet,
    TimesheetDocument,
    TimesheetEvent,
    TimesheetLine,
)


@pytest.fixture
def post_shift_admin_setup(db):
    user = get_user_model().objects.create_superuser(
        username="post-shift-admin",
        password="local-test-password",
    )
    browser = DjangoClient()
    browser.force_login(user)
    profession = Profession.objects.create(name="Admin Timesheet Nurse")
    client = Client.objects.create(
        name="Admin Hospital",
        accounting_code="ADMIN-ACC",
        billing_address="1 Admin Client Street",
    )
    FinanceSettings.objects.create(
        invoice_issuer_legal_name="IMMploy Admin Test (Pty) Ltd",
        invoice_issuer_vat_number="ADMIN-VAT-1",
        invoice_issuer_address="1 Admin IMMploy Street",
    )
    site = Site.objects.create(client=client, name="Admin Ward")
    candidate = Candidate.objects.create(
        first_name="Admin",
        last_name="Candidate",
        payroll_code="ADMIN01",
        compliance_status=Candidate.ComplianceStatus.CLEARED,
    )
    candidate.professions.add(profession)
    ends_at = timezone.now() - timedelta(hours=1)
    shift = Shift.objects.create(
        site=site,
        profession=profession,
        starts_at=ends_at - timedelta(hours=8),
        ends_at=ends_at,
        pay_rate="200.00",
        bill_rate="380.00",
    )
    booking = Booking.objects.create(
        shift=shift,
        candidate=candidate,
        status=Booking.Status.CONFIRMED,
    )
    return browser, booking


@pytest.mark.django_db
def test_admin_can_capture_completed_booking_timesheet(
    post_shift_admin_setup, settings, tmp_path
):
    settings.PRIVATE_MEDIA_ROOT = tmp_path
    browser, booking = post_shift_admin_setup

    listing = browser.get("/admin/bookings/timesheet/")
    assert listing.status_code == 200
    assert b"Capture timesheet" in listing.content

    response = browser.post(
        "/admin/bookings/timesheet/capture/",
        {
            "booking": booking.id,
            "number": "ADMIN-TS-001",
            "actual_start": booking.shift.starts_at.isoformat(),
            "actual_end": booking.shift.ends_at.isoformat(),
            "break_minutes": 30,
            "source_document": SimpleUploadedFile(
                "admin-signed.pdf",
                b"%PDF-1.4 admin signed",
                content_type="application/pdf",
            ),
        },
    )

    assert response.status_code == 302
    timesheet = Timesheet.objects.get(number="ADMIN-TS-001")
    assert timesheet.status == Timesheet.Status.SUBMITTED
    assert timesheet.documents.get().original_name == "admin-signed.pdf"


@pytest.mark.django_db
def test_candidate_payroll_code_is_editable_in_admin(post_shift_admin_setup):
    browser, booking = post_shift_admin_setup

    response = browser.get(
        f"/admin/bookings/candidate/{booking.candidate_id}/change/"
    )

    assert response.status_code == 200
    assert b"Payroll code" in response.content


@pytest.mark.django_db
def test_admin_actions_complete_finance_chain(
    post_shift_admin_setup, settings, tmp_path
):
    settings.PRIVATE_MEDIA_ROOT = tmp_path
    browser, booking = post_shift_admin_setup
    browser.post(
        "/admin/bookings/timesheet/capture/",
        {
            "booking": booking.id,
            "number": "ADMIN-TS-002",
            "actual_start": booking.shift.starts_at.isoformat(),
            "actual_end": booking.shift.ends_at.isoformat(),
            "break_minutes": 0,
            "source_document": SimpleUploadedFile(
                "finance.pdf", b"%PDF-1.4 finance", content_type="application/pdf"
            ),
        },
    )
    timesheet = Timesheet.objects.get(number="ADMIN-TS-002")

    for action in (
        "approve_selected_timesheets",
        "stage_selected_timesheets_for_payroll",
        "generate_payroll_for_selected_timesheets",
        "generate_invoices_for_selected_timesheets",
    ):
        response = browser.post(
            "/admin/bookings/timesheet/",
            {"action": action, "_selected_action": [timesheet.id]},
        )
        assert response.status_code == 302

    timesheet.refresh_from_db()
    assert timesheet.status == Timesheet.Status.APPROVED
    assert timesheet.payroll_exported_at is not None
    invoice = Invoice.objects.get()
    assert invoice.document
    invoice_detail = browser.get(
        f"/admin/bookings/invoice/{invoice.id}/change/"
    )
    assert invoice_detail.status_code == 200
    assert b"Download invoice PDF" in invoice_detail.content

    response = browser.post(
        "/admin/bookings/invoice/",
        {
            "action": "generate_pastel_for_selected_invoices",
            "_selected_action": [invoice.id],
        },
    )
    assert response.status_code == 302
    pastel_batch = FinanceExportBatch.objects.get(kind="pastel_sales")

    download = browser.get(
        f"/admin/bookings/financeexportbatch/{pastel_batch.id}/download/"
    )
    assert download.status_code == 200
    assert download.content.decode() == pastel_batch.content

    response = browser.post(
        "/admin/bookings/financeexportbatch/",
        {
            "action": "confirm_external_upload",
            "_selected_action": [pastel_batch.id],
        },
    )
    assert response.status_code == 302
    pastel_batch.refresh_from_db()
    assert pastel_batch.status == FinanceExportBatch.Status.UPLOAD_CONFIRMED

    source_document = timesheet.documents.get(
        kind="source",
        is_current=True,
    )
    unauthorized = get_user_model().objects.create_user(
        username="finance-download-denied",
        is_staff=True,
    )
    browser.force_login(unauthorized)
    assert browser.get(
        f"/admin/bookings/timesheet/{timesheet.id}/documents/"
        f"{source_document.id}/download/"
    ).status_code == 403
    assert browser.get(
        f"/admin/bookings/invoice/{invoice.id}/document/"
    ).status_code == 403


@pytest.mark.django_db
def test_admin_decline_replacement_and_private_download(
    post_shift_admin_setup, settings, tmp_path
):
    settings.PRIVATE_MEDIA_ROOT = tmp_path
    browser, booking = post_shift_admin_setup
    browser.post(
        "/admin/bookings/timesheet/capture/",
        {
            "booking": booking.id,
            "number": "ADMIN-TS-003",
            "actual_start": booking.shift.starts_at.isoformat(),
            "actual_end": booking.shift.ends_at.isoformat(),
            "break_minutes": 0,
            "source_document": SimpleUploadedFile(
                "original.pdf", b"%PDF-1.4 original", content_type="application/pdf"
            ),
        },
    )
    timesheet = Timesheet.objects.get(number="ADMIN-TS-003")
    detail = browser.get(f"/admin/bookings/timesheet/{timesheet.id}/change/")
    assert b"Decline timesheet" in detail.content
    assert b"Upload Client confirmation" in detail.content

    response = browser.post(
        f"/admin/bookings/timesheet/{timesheet.id}/decline/",
        {"reason": "Client signature missing."},
    )
    assert response.status_code == 302
    detail = browser.get(f"/admin/bookings/timesheet/{timesheet.id}/change/")
    assert b"Replace signed document" in detail.content
    response = browser.post(
        f"/admin/bookings/timesheet/{timesheet.id}/replace/",
        {
            "document": SimpleUploadedFile(
                "replacement.pdf",
                b"%PDF-1.4 replacement",
                content_type="application/pdf",
            )
        },
    )
    assert response.status_code == 302
    timesheet.refresh_from_db()
    assert timesheet.status == Timesheet.Status.SUBMITTED
    current = timesheet.documents.get(is_current=True)
    download = browser.get(
        f"/admin/bookings/timesheet/{timesheet.id}/documents/{current.id}/download/"
    )
    assert download.status_code == 200
    assert b"%PDF-1.4 replacement" == b"".join(download.streaming_content)


@pytest.mark.django_db
def test_admin_can_void_declined_duplicate(post_shift_admin_setup, settings, tmp_path):
    settings.PRIVATE_MEDIA_ROOT = tmp_path
    browser, booking = post_shift_admin_setup
    browser.post(
        "/admin/bookings/timesheet/capture/",
        {
            "booking": booking.id,
            "number": "ADMIN-TS-DUPLICATE",
            "actual_start": booking.shift.starts_at.isoformat(),
            "actual_end": booking.shift.ends_at.isoformat(),
            "break_minutes": 0,
            "source_document": SimpleUploadedFile(
                "duplicate.pdf", b"%PDF-1.4 duplicate", content_type="application/pdf"
            ),
        },
    )
    timesheet = Timesheet.objects.get(number="ADMIN-TS-DUPLICATE")
    browser.post(
        f"/admin/bookings/timesheet/{timesheet.id}/decline/",
        {"reason": "Suspected duplicate."},
    )

    detail = browser.get(f"/admin/bookings/timesheet/{timesheet.id}/change/")
    assert b"Void duplicate/unusable timesheet" in detail.content
    response = browser.post(
        f"/admin/bookings/timesheet/{timesheet.id}/void/",
        {"reason": "Confirmed duplicate; retain for audit only."},
    )

    assert response.status_code == 302
    timesheet.refresh_from_db()
    assert timesheet.status == Timesheet.Status.VOID


@pytest.mark.django_db
def test_admin_hides_actions_without_the_corresponding_legacy_rule():
    user = get_user_model().objects.create_user(username="capture-only", is_staff=True)
    LegacyUserProfile.objects.create(
        user=user,
        legacy_mysql_id=1201,
        cap_ts=True,
        approve_ts=False,
        export_ts=False,
        export_inv=False,
    )
    request = RequestFactory().get("/admin/bookings/timesheet/")
    request.user = user

    actions = admin.site._registry[Timesheet].get_actions(request)

    assert "approve_selected_timesheets" not in actions
    assert "stage_selected_timesheets_for_payroll" not in actions
    assert "generate_payroll_for_selected_timesheets" not in actions
    assert "generate_invoices_for_selected_timesheets" not in actions


@pytest.mark.django_db
def test_payroll_only_admin_cannot_list_pastel_batches():
    user = get_user_model().objects.create_user(username="payroll-only", is_staff=True)
    user.user_permissions.add(Permission.objects.get(codename="export_payroll"))
    FinanceExportBatch.objects.create(
        kind=FinanceExportBatch.Kind.PAYROLL,
        process_code="PAY-ONLY",
        file_name="payroll.txt",
        content="payroll",
        sha256="a" * 64,
        generated_by=user,
    )
    FinanceExportBatch.objects.create(
        kind=FinanceExportBatch.Kind.PASTEL_SALES,
        process_code="PASTEL-HIDDEN",
        file_name="pastel.csv",
        content="pastel",
        sha256="b" * 64,
        generated_by=user,
    )
    request = RequestFactory().get("/admin/bookings/financeexportbatch/")
    request.user = user

    queryset = admin.site._registry[FinanceExportBatch].get_queryset(request)

    assert list(queryset.values_list("kind", flat=True)) == [
        FinanceExportBatch.Kind.PAYROLL
    ]


@pytest.mark.django_db
def test_timesheet_child_admins_are_department_scoped(settings, tmp_path):
    settings.PRIVATE_MEDIA_ROOT = tmp_path
    profession = Profession.objects.create(name="Scoped post-shift role")
    department_a = Department.objects.create(
        name="Scoped Department A", legacy_mysql_id=7101
    )
    department_b = Department.objects.create(
        name="Scoped Department B", legacy_mysql_id=7102
    )
    actor = get_user_model().objects.create_user(username="scoped-capturer")

    timesheets = []
    for suffix, department in (("A", department_a), ("B", department_b)):
        client = Client.objects.create(name=f"Scoped Client {suffix}")
        client.departments.add(department)
        site = Site.objects.create(client=client, name=f"Scoped Site {suffix}")
        candidate = Candidate.objects.create(
            first_name="Scoped",
            last_name=f"Candidate {suffix}",
            compliance_status=Candidate.ComplianceStatus.CLEARED,
        )
        candidate.professions.add(profession)
        shift = Shift.objects.create(
            site=site,
            profession=profession,
            starts_at=timezone.now() - timedelta(hours=9),
            ends_at=timezone.now() - timedelta(hours=1),
            pay_rate="200.00",
            bill_rate="380.00",
        )
        booking = Booking.objects.create(
            shift=shift,
            candidate=candidate,
            status=Booking.Status.CONFIRMED,
        )
        timesheet = Timesheet.objects.create(
            booking=booking,
            number=f"SCOPED-{suffix}",
            status=Timesheet.Status.SUBMITTED,
            captured_by=actor,
        )
        TimesheetLine.objects.create(
            timesheet=timesheet,
            actual_start=shift.starts_at,
            actual_end=shift.ends_at,
            pay_rate="200.00",
            bill_rate="380.00",
        )
        TimesheetDocument.objects.create(
            timesheet=timesheet,
            file=SimpleUploadedFile(f"scoped-{suffix}.pdf", b"%PDF-1.4 scoped"),
            original_name=f"scoped-{suffix}.pdf",
            content_type="application/pdf",
            size=15,
            sha256=suffix.lower() * 64,
            uploaded_by=actor,
        )
        TimesheetEvent.objects.create(
            timesheet=timesheet,
            action="captured",
            from_status=Timesheet.Status.DRAFT,
            to_status=Timesheet.Status.SUBMITTED,
            actor=actor,
        )
        timesheets.append(timesheet)

    user = get_user_model().objects.create_user(
        username="department-a-post-shift-user", is_staff=True
    )
    LegacyUserProfile.objects.create(
        user=user,
        legacy_mysql_id=7103,
        assigned_desk=department_a.legacy_mysql_id,
        cap_ts=True,
    )
    for codename in (
        "view_timesheetline",
        "view_timesheetdocument",
        "view_timesheetevent",
    ):
        user.user_permissions.add(Permission.objects.get(codename=codename))
    request = RequestFactory().get("/admin/bookings/timesheetline/")
    request.user = user

    for model in (TimesheetLine, TimesheetDocument, TimesheetEvent):
        queryset = admin.site._registry[model].get_queryset(request)
        assert list(queryset.values_list("timesheet_id", flat=True)) == [
            timesheets[0].id
        ]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "model",
    [
        Timesheet,
        TimesheetLine,
        TimesheetDocument,
        TimesheetEvent,
        Invoice,
        InvoiceLine,
        FinanceExportBatch,
        FinanceSettings,
    ],
)
def test_post_shift_finance_admins_deny_delete_even_with_model_permission(model):
    user = get_user_model().objects.create_user(
        username=f"delete-{model._meta.model_name}",
        is_staff=True,
    )
    user.user_permissions.add(
        Permission.objects.get(codename=f"delete_{model._meta.model_name}")
    )
    request = RequestFactory().get("/admin/")
    request.user = user

    assert admin.site._registry[model].has_delete_permission(request) is False
