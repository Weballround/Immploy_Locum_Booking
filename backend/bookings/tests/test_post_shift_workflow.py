from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from bookings.models import (
    Booking,
    Candidate,
    Client,
    FinanceExportBatch,
    FinanceSettings,
    Invoice,
    Profession,
    Shift,
    Site,
    Timesheet,
    TimesheetDocument,
    TimesheetEvent,
    TimesheetLine,
)
from bookings.post_shift import (
    approve_timesheet,
    capture_timesheet,
    confirm_export_upload,
    decline_timesheet,
    generate_invoice,
    generate_pastel_export,
    generate_payroll_export,
    replace_and_resubmit_timesheet,
    stage_timesheet_for_payroll,
    upload_client_confirmation,
    void_timesheet,
)


@pytest.fixture
def completed_booking(db):
    profession = Profession.objects.create(name="Post-shift Nurse")
    client = Client.objects.create(name="Post-shift Hospital")
    site = Site.objects.create(client=client, name="Ward 1")
    candidate = Candidate.objects.create(
        first_name="Post",
        last_name="Shift",
        compliance_status=Candidate.ComplianceStatus.CLEARED,
    )
    candidate.professions.add(profession)
    ends_at = timezone.now() - timedelta(hours=1)
    shift = Shift.objects.create(
        site=site,
        profession=profession,
        starts_at=ends_at - timedelta(hours=8),
        ends_at=ends_at,
        pay_rate=Decimal("205.50"),
        bill_rate=Decimal("390.75"),
    )
    booking = Booking.objects.create(
        shift=shift,
        candidate=candidate,
        status=Booking.Status.CONFIRMED,
    )
    actor = get_user_model().objects.create_user(
        username="capturer",
        password="unused",
        is_staff=True,
    )
    return booking, actor


@pytest.mark.django_db
def test_capture_timesheet_snapshots_work_and_document(completed_booking, settings, tmp_path):
    settings.PRIVATE_MEDIA_ROOT = tmp_path
    booking, actor = completed_booking
    source = SimpleUploadedFile(
        "signed-timesheet.pdf",
        b"%PDF-1.4 signed timesheet",
        content_type="application/pdf",
    )

    timesheet = capture_timesheet(
        booking_id=booking.id,
        actor=actor,
        number="TS-2026-001",
        actual_start=booking.shift.starts_at,
        actual_end=booking.shift.ends_at,
        break_minutes=30,
        source_document=source,
    )

    assert timesheet.status == "submitted"
    assert timesheet.booking == booking
    assert timesheet.lines.get().pay_rate == Decimal("205.50")
    assert timesheet.lines.get().bill_rate == Decimal("390.75")
    assert timesheet.lines.get().worked_hours == Decimal("7.50")
    document = timesheet.documents.get()
    assert document.original_name == "signed-timesheet.pdf"
    assert document.sha256
    assert document.file.name != "signed-timesheet.pdf"
    booking.shift.refresh_from_db()
    assert booking.shift.status == Shift.Status.COMPLETED


def test_timesheet_rate_categories_cover_active_legacy_vocabulary():
    assert set(TimesheetLine.RateCategory.values) == {
        "normal",
        "saturday",
        "sunday",
        "overtime",
        "standby",
        "night",
        "public_holiday",
        "standby_holiday",
        "standby_sunday",
        "standby_week",
    }


@pytest.mark.django_db
def test_capture_rejects_document_content_that_does_not_match_extension(
    completed_booking, settings, tmp_path
):
    settings.PRIVATE_MEDIA_ROOT = tmp_path
    booking, actor = completed_booking

    with pytest.raises(ValidationError, match="valid PDF"):
        capture_timesheet(
            booking_id=booking.id,
            actor=actor,
            number="TS-FAKE-PDF",
            actual_start=booking.shift.starts_at,
            actual_end=booking.shift.ends_at,
            break_minutes=0,
            source_document=SimpleUploadedFile(
                "fake.pdf", b"this is not a pdf", content_type="application/pdf"
            ),
        )

    assert not Timesheet.objects.filter(number="TS-FAKE-PDF").exists()


@pytest.mark.django_db
def test_capture_timesheet_rejects_duplicate_booking(completed_booking, settings, tmp_path):
    settings.PRIVATE_MEDIA_ROOT = tmp_path
    booking, actor = completed_booking
    values = {
        "booking_id": booking.id,
        "actor": actor,
        "number": "TS-2026-002",
        "actual_start": booking.shift.starts_at,
        "actual_end": booking.shift.ends_at,
        "break_minutes": 0,
    }
    capture_timesheet(
        **values,
        source_document=SimpleUploadedFile("first.pdf", b"%PDF-1.4 first"),
    )

    with pytest.raises(ValidationError, match="already has a timesheet"):
        capture_timesheet(
            **values,
            source_document=SimpleUploadedFile("second.pdf", b"%PDF-1.4 second"),
        )


@pytest.mark.django_db
def test_capture_removes_private_file_when_database_finalisation_fails(
    completed_booking, settings, tmp_path
):
    settings.PRIVATE_MEDIA_ROOT = tmp_path
    booking, actor = completed_booking

    with patch.object(Shift, "save", side_effect=RuntimeError("late failure")):
        with pytest.raises(RuntimeError, match="late failure"):
            capture_timesheet(
                booking_id=booking.id,
                actor=actor,
                number="TS-ROLLBACK-FILE",
                actual_start=booking.shift.starts_at,
                actual_end=booking.shift.ends_at,
                break_minutes=0,
                source_document=SimpleUploadedFile(
                    "rollback.pdf", b"%PDF-1.4 rollback"
                ),
            )

    assert list(tmp_path.rglob("*.*")) == []
    assert not Timesheet.objects.filter(number="TS-ROLLBACK-FILE").exists()


@pytest.mark.django_db
def test_capture_removes_private_file_when_document_insert_fails(
    completed_booking, settings, tmp_path
):
    settings.PRIVATE_MEDIA_ROOT = tmp_path
    booking, actor = completed_booking

    def save_file_then_fail(document, *args, **kwargs):
        document.file.save(document.original_name, document.file.file, save=False)
        raise RuntimeError("document insert failure")

    with patch.object(TimesheetDocument, "save", new=save_file_then_fail):
        with pytest.raises(RuntimeError, match="document insert failure"):
            capture_timesheet(
                booking_id=booking.id,
                actor=actor,
                number="TS-DOCUMENT-INSERT-FAILURE",
                actual_start=booking.shift.starts_at,
                actual_end=booking.shift.ends_at,
                break_minutes=0,
                source_document=SimpleUploadedFile(
                    "insert-failure.pdf", b"%PDF-1.4 insert failure"
                ),
            )

    assert list(tmp_path.rglob("*.*")) == []


@pytest.mark.django_db
def test_approval_is_segregated_and_audited(completed_booking, settings, tmp_path):
    settings.PRIVATE_MEDIA_ROOT = tmp_path
    booking, capturer = completed_booking
    timesheet = capture_timesheet(
        booking_id=booking.id,
        actor=capturer,
        number="TS-2026-003",
        actual_start=booking.shift.starts_at,
        actual_end=booking.shift.ends_at,
        break_minutes=0,
        source_document=SimpleUploadedFile("signed.pdf", b"%PDF-1.4 signed"),
    )

    with pytest.raises(ValidationError, match="own timesheet"):
        approve_timesheet(timesheet_id=timesheet.id, actor=capturer)

    approver = get_user_model().objects.create_user(
        username="approver",
        password="unused",
        is_staff=True,
    )
    approve_timesheet(timesheet_id=timesheet.id, actor=approver)

    timesheet.refresh_from_db()
    assert timesheet.status == "approved"
    assert timesheet.approved_by == approver
    assert timesheet.approved_at is not None
    event = timesheet.events.get()
    assert event.action == "approved"
    assert event.actor == approver
    assert event.from_status == "submitted"
    assert event.to_status == "approved"


@pytest.mark.django_db
def test_approval_revalidates_stored_worked_time_lines(
    completed_booking, settings, tmp_path
):
    settings.PRIVATE_MEDIA_ROOT = tmp_path
    booking, capturer = completed_booking
    timesheet = capture_timesheet(
        booking_id=booking.id,
        actor=capturer,
        number="TS-INVALID-LINE",
        actual_start=booking.shift.starts_at,
        actual_end=booking.shift.ends_at,
        break_minutes=0,
        source_document=SimpleUploadedFile("invalid-line.pdf", b"%PDF-1.4 invalid"),
    )
    timesheet.lines.update(break_minutes=8 * 60)
    approver = get_user_model().objects.create_user(
        username="invalid-line-approver",
        is_staff=True,
    )

    with pytest.raises(ValidationError, match="invalid worked-time line"):
        approve_timesheet(timesheet_id=timesheet.id, actor=approver)

    timesheet.refresh_from_db()
    assert timesheet.status == Timesheet.Status.SUBMITTED


@pytest.mark.django_db
def test_declined_timesheet_replacement_preserves_document_history(
    completed_booking, settings, tmp_path
):
    settings.PRIVATE_MEDIA_ROOT = tmp_path
    booking, capturer = completed_booking
    timesheet = capture_timesheet(
        booking_id=booking.id,
        actor=capturer,
        number="TS-2026-004",
        actual_start=booking.shift.starts_at,
        actual_end=booking.shift.ends_at,
        break_minutes=15,
        source_document=SimpleUploadedFile("unclear.pdf", b"%PDF-1.4 unclear"),
    )
    approver = get_user_model().objects.create_user(
        username="decliner",
        password="unused",
        is_staff=True,
    )

    with pytest.raises(ValidationError, match="reason"):
        decline_timesheet(timesheet_id=timesheet.id, actor=approver, reason="  ")

    decline_timesheet(
        timesheet_id=timesheet.id,
        actor=approver,
        reason="Client signature is not readable.",
    )
    replace_and_resubmit_timesheet(
        timesheet_id=timesheet.id,
        actor=capturer,
        source_document=SimpleUploadedFile(
            "signed-clear.pdf", b"%PDF-1.4 corrected"
        ),
    )

    timesheet.refresh_from_db()
    assert timesheet.status == "submitted"
    assert timesheet.decline_reason == ""
    assert timesheet.documents.count() == 2
    assert timesheet.documents.filter(is_current=True).get().original_name == "signed-clear.pdf"
    assert timesheet.documents.filter(is_current=False).get().original_name == "unclear.pdf"
    assert list(timesheet.events.values_list("action", flat=True)) == [
        "declined",
        "resubmitted",
    ]


@pytest.mark.django_db
def test_replacement_removes_new_file_when_resubmission_rolls_back(
    completed_booking, settings, tmp_path
):
    settings.PRIVATE_MEDIA_ROOT = tmp_path
    booking, capturer = completed_booking
    timesheet = capture_timesheet(
        booking_id=booking.id,
        actor=capturer,
        number="TS-REPLACEMENT-ROLLBACK",
        actual_start=booking.shift.starts_at,
        actual_end=booking.shift.ends_at,
        break_minutes=0,
        source_document=SimpleUploadedFile("original.pdf", b"%PDF-1.4 original"),
    )
    approver = get_user_model().objects.create_user(username="rollback-decliner")
    decline_timesheet(
        timesheet_id=timesheet.id,
        actor=approver,
        reason="Needs replacement.",
    )
    original_name = timesheet.documents.get(is_current=True).file.name

    with patch.object(
        TimesheetEvent.objects,
        "create",
        side_effect=RuntimeError("resubmission failure"),
    ):
        with pytest.raises(RuntimeError, match="resubmission failure"):
            replace_and_resubmit_timesheet(
                timesheet_id=timesheet.id,
                actor=capturer,
                source_document=SimpleUploadedFile(
                    "replacement.pdf", b"%PDF-1.4 replacement"
                ),
            )

    timesheet.refresh_from_db()
    assert timesheet.status == Timesheet.Status.DECLINED
    assert timesheet.documents.get(is_current=True).file.name == original_name
    assert len(list(tmp_path.rglob("*.pdf"))) == 1


@pytest.mark.django_db
def test_declined_timesheet_can_be_voided_with_audit_reason(
    completed_booking, settings, tmp_path
):
    settings.PRIVATE_MEDIA_ROOT = tmp_path
    booking, capturer = completed_booking
    timesheet = capture_timesheet(
        booking_id=booking.id,
        actor=capturer,
        number="TS-DUPLICATE",
        actual_start=booking.shift.starts_at,
        actual_end=booking.shift.ends_at,
        break_minutes=0,
        source_document=SimpleUploadedFile("duplicate.pdf", b"%PDF-1.4 duplicate"),
    )
    approver = get_user_model().objects.create_user(
        username="duplicate-approver",
        is_staff=True,
    )
    decline_timesheet(
        timesheet_id=timesheet.id,
        actor=approver,
        reason="Duplicate of another signed timesheet.",
    )

    void_timesheet(
        timesheet_id=timesheet.id,
        actor=approver,
        reason="Confirmed duplicate; retain for audit only.",
    )

    timesheet.refresh_from_db()
    assert timesheet.status == Timesheet.Status.VOID
    event = timesheet.events.get(action="voided")
    assert event.from_status == Timesheet.Status.DECLINED
    assert event.to_status == Timesheet.Status.VOID
    assert event.reason == "Confirmed duplicate; retain for audit only."


@pytest.mark.django_db
def test_client_confirmation_removes_file_when_event_write_rolls_back(
    completed_booking, settings, tmp_path
):
    settings.PRIVATE_MEDIA_ROOT = tmp_path
    booking, capturer = completed_booking
    timesheet = capture_timesheet(
        booking_id=booking.id,
        actor=capturer,
        number="TS-CONFIRMATION-ROLLBACK",
        actual_start=booking.shift.starts_at,
        actual_end=booking.shift.ends_at,
        break_minutes=0,
        source_document=SimpleUploadedFile("source.pdf", b"%PDF-1.4 source"),
    )

    with patch.object(
        TimesheetEvent.objects,
        "create",
        side_effect=RuntimeError("confirmation event failure"),
    ):
        with pytest.raises(RuntimeError, match="confirmation event failure"):
            upload_client_confirmation(
                timesheet_id=timesheet.id,
                actor=capturer,
                document=SimpleUploadedFile(
                    "confirmation.pdf", b"%PDF-1.4 confirmation"
                ),
            )

    assert not timesheet.documents.filter(
        kind="client_confirmation"
    ).exists()
    assert len(list(tmp_path.rglob("*.pdf"))) == 1


@pytest.mark.django_db
def test_payroll_export_is_exact_hashed_and_not_repeatable(
    completed_booking, settings, tmp_path
):
    settings.PRIVATE_MEDIA_ROOT = tmp_path
    booking, capturer = completed_booking
    booking.candidate.payroll_code = "POST01"
    booking.candidate.save(update_fields=["payroll_code"])
    timesheet = capture_timesheet(
        booking_id=booking.id,
        actor=capturer,
        number="TS-2026-005",
        actual_start=booking.shift.starts_at,
        actual_end=booking.shift.ends_at,
        break_minutes=30,
        source_document=SimpleUploadedFile("payroll.pdf", b"%PDF-1.4 payroll"),
    )
    approver = get_user_model().objects.create_user(
        username="payroll-approver",
        password="unused",
        is_staff=True,
    )
    approve_timesheet(timesheet_id=timesheet.id, actor=approver)

    with pytest.raises(ValidationError, match="staged for payroll"):
        generate_payroll_export(
            timesheet_ids=[timesheet.id],
            actor=approver,
            process_code="2026-W35-NOT-STAGED",
        )
    stage_timesheet_for_payroll(timesheet_id=timesheet.id, actor=approver)
    batch = generate_payroll_export(
        timesheet_ids=[timesheet.id],
        actor=approver,
        process_code="2026-W35",
    )

    assert batch.kind == "payroll"
    assert batch.content == "POST01,4100,,,0,1,1541.25,N\r\n"
    assert len(batch.sha256) == 64
    assert list(batch.timesheets.all()) == [timesheet]
    timesheet.refresh_from_db()
    assert timesheet.payroll_exported_at is not None
    with pytest.raises(ValidationError, match="already exported"):
        generate_payroll_export(
            timesheet_ids=[timesheet.id],
            actor=approver,
            process_code="2026-W35-REPEAT",
        )


@pytest.mark.django_db
def test_invoice_pdf_and_pastel_export_are_generated_from_snapshots(
    completed_booking, settings, tmp_path
):
    settings.PRIVATE_MEDIA_ROOT = tmp_path
    booking, capturer = completed_booking
    booking.candidate.payroll_code = "POST02"
    booking.candidate.save(update_fields=["payroll_code"])
    client = booking.shift.site.client
    client.accounting_code = "ACC-POST"
    client.billing_address = "1 Client Street\nJohannesburg"
    client.vat_number = "CLIENT-VAT-1"
    client.requires_timesheet_confirmation = True
    client.save(update_fields=[
        "accounting_code",
        "billing_address",
        "vat_number",
        "requires_timesheet_confirmation",
    ])
    timesheet = capture_timesheet(
        booking_id=booking.id,
        actor=capturer,
        number="TS-2026-006",
        actual_start=booking.shift.starts_at,
        actual_end=booking.shift.ends_at,
        break_minutes=30,
        source_document=SimpleUploadedFile("invoice.pdf", b"%PDF-1.4 invoice"),
    )
    finance_user = get_user_model().objects.create_user(
        username="finance-user",
        password="unused",
        is_staff=True,
    )
    approve_timesheet(timesheet_id=timesheet.id, actor=finance_user)
    stage_timesheet_for_payroll(timesheet_id=timesheet.id, actor=finance_user)
    generate_payroll_export(
        timesheet_ids=[timesheet.id],
        actor=finance_user,
        process_code="2026-W35-INVOICE",
    )

    with pytest.raises(ValidationError, match="invoice issuer legal name"):
        generate_invoice(
            timesheet_ids=[timesheet.id],
            actor=finance_user,
            invoice_date=date(2026, 8, 26),
        )
    FinanceSettings.objects.create(
        invoice_issuer_legal_name="IMMploy Test (Pty) Ltd",
        invoice_issuer_vat_number="VAT-TEST-1",
        invoice_issuer_address="1 IMMploy Street\nJohannesburg",
    )
    with pytest.raises(ValidationError, match="requires Client confirmation"):
        generate_invoice(
            timesheet_ids=[timesheet.id],
            actor=finance_user,
            invoice_date=date(2026, 8, 26),
        )
    upload_client_confirmation(
        timesheet_id=timesheet.id,
        actor=finance_user,
        document=SimpleUploadedFile(
            "client-confirmation.pdf",
            b"%PDF-1.4 client confirmation",
        ),
    )

    with patch.object(
        Timesheet.objects,
        "filter",
        side_effect=RuntimeError("invoice finalisation failure"),
    ):
        with pytest.raises(RuntimeError, match="invoice finalisation failure"):
            generate_invoice(
                timesheet_ids=[timesheet.id],
                actor=finance_user,
                invoice_date=date(2026, 8, 26),
            )
    assert not Invoice.objects.exists()
    assert not list((tmp_path / "invoices").rglob("*.pdf"))

    invoice = generate_invoice(
        timesheet_ids=[timesheet.id],
        actor=finance_user,
        invoice_date=date(2026, 8, 26),
    )

    assert invoice.number.startswith("IMT")
    assert invoice.subtotal == Decimal("2930.63")
    assert invoice.vat_amount == Decimal("439.59")
    assert invoice.total == Decimal("3370.22")
    assert invoice.issuer_legal_name == "IMMploy Test (Pty) Ltd"
    assert invoice.issuer_vat_number == "VAT-TEST-1"
    assert invoice.client_billing_address == "1 Client Street\nJohannesburg"
    assert invoice.client_vat_number == "CLIENT-VAT-1"
    assert invoice.lines.get().bill_rate == Decimal("390.75")
    with invoice.document.open("rb") as invoice_file:
        invoice_content = invoice_file.read()
    assert invoice_content.startswith(b"%PDF-1.")
    assert b"IMMploy Test" in invoice_content
    assert b"VAT-TEST-1" in invoice_content
    assert b"Post-shift Nurse" in invoice_content
    assert b"Day shift" in invoice_content

    batch = generate_pastel_export(invoice_ids=[invoice.id], actor=finance_user)

    assert batch.kind == "pastel_sales"
    assert batch.content.startswith('6,"26/08/2026","D","ACC-POST"')
    assert invoice.number in batch.content
    assert "3370.22" in batch.content
    invoice.refresh_from_db()
    assert invoice.pastel_exported_at is not None
    with pytest.raises(ValidationError, match="already exported"):
        generate_pastel_export(invoice_ids=[invoice.id], actor=finance_user)


@pytest.mark.django_db
def test_external_upload_confirmation_is_single_transition():
    actor = get_user_model().objects.create_user(
        username="external-upload-confirmer",
        is_staff=True,
    )
    batch = FinanceExportBatch.objects.create(
        kind=FinanceExportBatch.Kind.PAYROLL,
        process_code="CONFIRM-ONCE",
        file_name="confirm-once.txt",
        content="payroll",
        sha256="c" * 64,
        generated_by=actor,
    )

    confirmed = confirm_export_upload(batch_ids=[batch.id], actor=actor)

    assert confirmed == 1
    batch.refresh_from_db()
    assert batch.status == FinanceExportBatch.Status.UPLOAD_CONFIRMED
    assert batch.upload_confirmed_by == actor
    assert batch.upload_confirmed_at is not None
    with pytest.raises(ValidationError, match="already confirmed"):
        confirm_export_upload(batch_ids=[batch.id], actor=actor)
