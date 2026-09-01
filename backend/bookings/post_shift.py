from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
import hashlib
from pathlib import Path

from django.core.files.base import ContentFile
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from bookings.models import (
    Booking,
    FinanceExportBatch,
    FinanceSettings,
    Invoice,
    InvoiceLine,
    Shift,
    Timesheet,
    TimesheetDocument,
    TimesheetEvent,
    TimesheetLine,
)
from bookings.invoice_pdf import build_invoice_pdf


ALLOWED_TIMESHEET_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}
MAX_TIMESHEET_FILE_SIZE = 10 * 1024 * 1024


def _validate_document(uploaded):
    extension = Path(uploaded.name).suffix.lower()
    if extension not in ALLOWED_TIMESHEET_EXTENSIONS:
        raise ValidationError("Timesheet document must be PDF, JPG, JPEG or PNG.")
    if uploaded.size > MAX_TIMESHEET_FILE_SIZE:
        raise ValidationError("Timesheet document may not exceed 10 MB.")
    position = uploaded.tell()
    signature = uploaded.read(8)
    uploaded.seek(position)
    is_valid = {
        ".pdf": signature.startswith(b"%PDF-"),
        ".jpg": signature.startswith(b"\xff\xd8\xff"),
        ".jpeg": signature.startswith(b"\xff\xd8\xff"),
        ".png": signature.startswith(b"\x89PNG\r\n\x1a\n"),
    }[extension]
    if not is_valid:
        label = "PDF" if extension == ".pdf" else extension.removeprefix(".").upper()
        raise ValidationError(f"The uploaded file is not a valid {label} document.")


def _create_timesheet_document(
    *, timesheet, uploaded_file, actor, kind=TimesheetDocument.Kind.SOURCE
):
    original_file_name = uploaded_file.name
    document = TimesheetDocument(
        timesheet=timesheet,
        kind=kind,
        file=uploaded_file,
        original_name=Path(uploaded_file.name).name,
        content_type=getattr(uploaded_file, "content_type", "")
        or "application/octet-stream",
        size=uploaded_file.size,
        sha256=TimesheetDocument.digest(uploaded_file),
        uploaded_by=actor,
    )
    try:
        document.save()
    except Exception:
        if document.file.name and document.file.name != original_file_name:
            document.file.delete(save=False)
        raise
    return document


@transaction.atomic
def capture_timesheet(
    *,
    booking_id,
    actor,
    number,
    actual_start,
    actual_end,
    break_minutes,
    source_document,
):
    _validate_document(source_document)
    booking = (
        Booking.objects.select_for_update()
        .select_related("shift", "candidate")
        .get(pk=booking_id)
    )
    shift = Shift.objects.select_for_update().get(pk=booking.shift_id)
    if booking.status != Booking.Status.CONFIRMED:
        raise ValidationError("Only a confirmed booking can have a timesheet.")
    if shift.ends_at > timezone.now():
        raise ValidationError("A timesheet cannot be captured before the shift ends.")
    if Timesheet.objects.filter(booking=booking).exists():
        raise ValidationError("This booking already has a timesheet.")

    timesheet = Timesheet.objects.create(
        booking=booking,
        number=number.strip(),
        status=Timesheet.Status.SUBMITTED,
        captured_by=actor,
        submitted_at=timezone.now(),
    )
    line = TimesheetLine(
        timesheet=timesheet,
        actual_start=actual_start,
        actual_end=actual_end,
        break_minutes=break_minutes,
        pay_rate=shift.pay_rate,
        bill_rate=shift.bill_rate,
    )
    line.full_clean()
    line.save()
    document = _create_timesheet_document(
        timesheet=timesheet,
        uploaded_file=source_document,
        actor=actor,
    )
    try:
        shift.status = Shift.Status.COMPLETED
        shift.save(update_fields=["status"])
    except Exception:
        document.file.delete(save=False)
        raise
    return timesheet


@transaction.atomic
def approve_timesheet(*, timesheet_id, actor):
    timesheet = Timesheet.objects.select_for_update().get(pk=timesheet_id)
    if timesheet.status != Timesheet.Status.SUBMITTED:
        raise ValidationError("Only a submitted timesheet can be approved.")
    if timesheet.captured_by_id == actor.id and not actor.is_superuser:
        raise ValidationError("A user cannot approve their own timesheet capture.")
    lines = list(
        TimesheetLine.objects.select_for_update()
        .filter(timesheet=timesheet)
        .order_by("pk")
    )
    if not lines:
        raise ValidationError("A timesheet must contain worked-time lines before approval.")
    for line in lines:
        try:
            line.full_clean()
        except ValidationError as exc:
            raise ValidationError(
                f"Timesheet {timesheet.number} has an invalid worked-time line "
                f"({line.pk}): {'; '.join(exc.messages)}"
            ) from exc
    if not timesheet.documents.filter(
        kind=TimesheetDocument.Kind.SOURCE,
        is_current=True,
    ).exists():
        raise ValidationError("A current signed timesheet document is required.")

    previous_status = timesheet.status
    timesheet.status = Timesheet.Status.APPROVED
    timesheet.approved_by = actor
    timesheet.approved_at = timezone.now()
    timesheet.declined_by = None
    timesheet.declined_at = None
    timesheet.decline_reason = ""
    timesheet.save(update_fields=[
        "status",
        "approved_by",
        "approved_at",
        "declined_by",
        "declined_at",
        "decline_reason",
    ])
    TimesheetEvent.objects.create(
        timesheet=timesheet,
        action="approved",
        from_status=previous_status,
        to_status=timesheet.status,
        actor=actor,
    )
    return timesheet


@transaction.atomic
def decline_timesheet(*, timesheet_id, actor, reason):
    reason = reason.strip()
    if not reason:
        raise ValidationError("A decline reason is required.")
    timesheet = Timesheet.objects.select_for_update().get(pk=timesheet_id)
    if timesheet.status != Timesheet.Status.SUBMITTED:
        raise ValidationError("Only a submitted timesheet can be declined.")
    previous_status = timesheet.status
    timesheet.status = Timesheet.Status.DECLINED
    timesheet.declined_by = actor
    timesheet.declined_at = timezone.now()
    timesheet.decline_reason = reason
    timesheet.save(update_fields=[
        "status",
        "declined_by",
        "declined_at",
        "decline_reason",
    ])
    TimesheetEvent.objects.create(
        timesheet=timesheet,
        action="declined",
        from_status=previous_status,
        to_status=timesheet.status,
        actor=actor,
        reason=reason,
    )
    return timesheet


@transaction.atomic
def void_timesheet(*, timesheet_id, actor, reason):
    reason = reason.strip()
    if not reason:
        raise ValidationError("A void reason is required.")
    timesheet = Timesheet.objects.select_for_update().get(pk=timesheet_id)
    if timesheet.status != Timesheet.Status.DECLINED:
        raise ValidationError("Only a declined timesheet can be voided.")
    previous_status = timesheet.status
    timesheet.status = Timesheet.Status.VOID
    timesheet.save(update_fields=["status"])
    TimesheetEvent.objects.create(
        timesheet=timesheet,
        action="voided",
        from_status=previous_status,
        to_status=timesheet.status,
        actor=actor,
        reason=reason,
    )
    return timesheet


@transaction.atomic
def replace_and_resubmit_timesheet(*, timesheet_id, actor, source_document):
    _validate_document(source_document)
    timesheet = Timesheet.objects.select_for_update().get(pk=timesheet_id)
    if timesheet.status != Timesheet.Status.DECLINED:
        raise ValidationError("Only a declined timesheet can be resubmitted.")
    TimesheetDocument.objects.filter(
        timesheet=timesheet,
        kind=TimesheetDocument.Kind.SOURCE,
        is_current=True,
    ).update(is_current=False)
    document = _create_timesheet_document(
        timesheet=timesheet,
        uploaded_file=source_document,
        actor=actor,
    )
    try:
        previous_status = timesheet.status
        timesheet.status = Timesheet.Status.SUBMITTED
        timesheet.submitted_at = timezone.now()
        timesheet.decline_reason = ""
        timesheet.save(update_fields=["status", "submitted_at", "decline_reason"])
        TimesheetEvent.objects.create(
            timesheet=timesheet,
            action="resubmitted",
            from_status=previous_status,
            to_status=timesheet.status,
            actor=actor,
        )
    except Exception:
        document.file.delete(save=False)
        raise
    return timesheet


@transaction.atomic
def upload_client_confirmation(*, timesheet_id, actor, document):
    _validate_document(document)
    timesheet = Timesheet.objects.select_for_update().get(pk=timesheet_id)
    if timesheet.status not in {
        Timesheet.Status.SUBMITTED,
        Timesheet.Status.APPROVED,
    }:
        raise ValidationError(
            "Client confirmation can only be linked to a submitted or approved timesheet."
        )
    TimesheetDocument.objects.filter(
        timesheet=timesheet,
        kind=TimesheetDocument.Kind.CLIENT_CONFIRMATION,
        is_current=True,
    ).update(is_current=False)
    confirmation = _create_timesheet_document(
        timesheet=timesheet,
        kind=TimesheetDocument.Kind.CLIENT_CONFIRMATION,
        uploaded_file=document,
        actor=actor,
    )
    try:
        TimesheetEvent.objects.create(
            timesheet=timesheet,
            action="client_confirmation_uploaded",
            from_status=timesheet.status,
            to_status=timesheet.status,
            actor=actor,
        )
    except Exception:
        confirmation.file.delete(save=False)
        raise
    return timesheet


@transaction.atomic
def stage_timesheet_for_payroll(*, timesheet_id, actor):
    timesheet = (
        Timesheet.objects.select_for_update()
        .select_related("booking__candidate")
        .get(pk=timesheet_id)
    )
    if timesheet.status != Timesheet.Status.APPROVED:
        raise ValidationError("Only an approved timesheet can be staged for payroll.")
    if timesheet.payroll_ready_at:
        raise ValidationError("This timesheet is already staged for payroll.")
    if timesheet.payroll_exported_at:
        raise ValidationError("This timesheet has already been exported to payroll.")
    if not (timesheet.booking.candidate.payroll_code or "").strip():
        raise ValidationError("The Candidate payroll code is required.")
    timesheet.payroll_ready_by = actor
    timesheet.payroll_ready_at = timezone.now()
    timesheet.save(update_fields=["payroll_ready_by", "payroll_ready_at"])
    TimesheetEvent.objects.create(
        timesheet=timesheet,
        action="payroll_staged",
        from_status=timesheet.status,
        to_status=timesheet.status,
        actor=actor,
    )
    return timesheet


@transaction.atomic
def generate_payroll_export(*, timesheet_ids, actor, process_code):
    ids = sorted(set(timesheet_ids))
    if not ids:
        raise ValidationError("Select at least one timesheet for payroll export.")
    if len(ids) != len(timesheet_ids):
        raise ValidationError("A timesheet may only appear once in a payroll batch.")
    timesheets = list(
        Timesheet.objects.select_for_update()
        .filter(pk__in=ids)
        .select_related("booking__candidate")
        .prefetch_related("lines")
        .order_by("pk")
    )
    if len(timesheets) != len(ids):
        raise ValidationError("One or more selected timesheets do not exist.")

    totals = defaultdict(lambda: Decimal("0.00"))
    for timesheet in timesheets:
        if timesheet.status != Timesheet.Status.APPROVED:
            raise ValidationError(
                f"Timesheet {timesheet.number} must be approved before payroll export."
            )
        if timesheet.payroll_ready_at is None:
            raise ValidationError(
                f"Timesheet {timesheet.number} must be staged for payroll first."
            )
        if timesheet.payroll_exported_at is not None:
            raise ValidationError(
                f"Timesheet {timesheet.number} is already exported to payroll."
            )
        payroll_code = (timesheet.booking.candidate.payroll_code or "").strip()
        if not payroll_code:
            raise ValidationError(
                f"Candidate on timesheet {timesheet.number} has no payroll code."
            )
        for line in timesheet.lines.all():
            totals[payroll_code] += line.worked_hours * line.pay_rate

    content = "".join(
        f"{payroll_code},4100,,,0,1,"
        f"{amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.2f},N\r\n"
        for payroll_code, amount in sorted(totals.items())
    )
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    batch = FinanceExportBatch.objects.create(
        kind=FinanceExportBatch.Kind.PAYROLL,
        process_code=process_code.strip(),
        file_name=f"IMMploy-payroll-{process_code.strip()}.txt",
        content=content,
        sha256=digest,
        generated_by=actor,
    )
    batch.timesheets.set(timesheets)
    Timesheet.objects.filter(pk__in=ids).update(payroll_exported_at=timezone.now())
    return batch


@transaction.atomic
def generate_invoice(*, timesheet_ids, actor, invoice_date):
    ids = sorted(set(timesheet_ids))
    if not ids:
        raise ValidationError("Select at least one timesheet to invoice.")
    if len(ids) != len(timesheet_ids):
        raise ValidationError("A timesheet may only appear once on an invoice.")
    timesheets = list(
        Timesheet.objects.select_for_update()
        .filter(pk__in=ids)
        .select_related(
            "booking__candidate",
            "booking__shift__profession",
            "booking__shift__site__client",
        )
        .prefetch_related("lines", "documents")
        .order_by("pk")
    )
    if len(timesheets) != len(ids):
        raise ValidationError("One or more selected timesheets do not exist.")
    clients = {timesheet.booking.shift.site.client_id for timesheet in timesheets}
    if len(clients) != 1:
        raise ValidationError("An invoice may contain timesheets for one Client only.")
    client = timesheets[0].booking.shift.site.client
    accounting_code = (client.accounting_code or "").strip()
    if not accounting_code:
        raise ValidationError(f"Client {client.name} has no Pastel account code.")
    client_billing_address = (client.billing_address or "").strip()
    if not client_billing_address:
        raise ValidationError(f"Client {client.name} has no billing address.")

    finance_settings = FinanceSettings.current()
    issuer_legal_name = finance_settings.invoice_issuer_legal_name.strip()
    issuer_address = finance_settings.invoice_issuer_address.strip()
    issuer_vat_number = finance_settings.invoice_issuer_vat_number.strip()
    if not issuer_legal_name:
        raise ValidationError("Configure the invoice issuer legal name before invoicing.")
    if not issuer_address:
        raise ValidationError("Configure the invoice issuer address before invoicing.")
    if finance_settings.vat_percent and not issuer_vat_number:
        raise ValidationError("Configure the invoice issuer VAT number before invoicing.")

    prepared_lines = []
    subtotal = Decimal("0.00")
    for timesheet in timesheets:
        if timesheet.status != Timesheet.Status.APPROVED:
            raise ValidationError(
                f"Timesheet {timesheet.number} must be approved before invoicing."
            )
        if timesheet.payroll_exported_at is None:
            raise ValidationError(
                f"Timesheet {timesheet.number} must be exported to payroll before invoicing."
            )
        if timesheet.invoiced_at is not None:
            raise ValidationError(f"Timesheet {timesheet.number} is already invoiced.")
        if client.requires_timesheet_confirmation and not timesheet.documents.filter(
            kind=TimesheetDocument.Kind.CLIENT_CONFIRMATION,
            is_current=True,
        ).exists():
            raise ValidationError(
                f"Timesheet {timesheet.number} requires Client confirmation before invoicing."
            )
        candidate_name = timesheet.booking.candidate.full_name
        profession_name = timesheet.booking.shift.profession.name
        for line in timesheet.lines.all():
            amount = (line.worked_hours * line.bill_rate).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )
            subtotal += amount
            prepared_lines.append(
                (timesheet, line, candidate_name, profession_name, amount)
            )

    vat_percent = finance_settings.vat_percent
    vat_amount = (subtotal * vat_percent / Decimal("100")).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )
    total = subtotal + vat_amount
    invoice = Invoice.objects.create(
        client=client,
        invoice_date=invoice_date,
        client_name=client.name,
        accounting_code=accounting_code,
        client_billing_address=client_billing_address,
        client_vat_number=client.vat_number.strip(),
        issuer_legal_name=issuer_legal_name,
        issuer_vat_number=issuer_vat_number,
        issuer_address=issuer_address,
        subtotal=subtotal,
        vat_percent=vat_percent,
        vat_amount=vat_amount,
        total=total,
        generated_by=actor,
    )
    invoice.number = f"IMT{invoice.pk}"
    invoice.save(update_fields=["number"])
    for timesheet, line, candidate_name, profession_name, amount in prepared_lines:
        rate_label = (
            "Day"
            if line.rate_category == TimesheetLine.RateCategory.NORMAL
            else line.get_rate_category_display()
        )
        InvoiceLine.objects.create(
            invoice=invoice,
            timesheet=timesheet,
            timesheet_number=timesheet.number,
            candidate_name=candidate_name,
            description=(
                f"{profession_name} | {candidate_name}, {rate_label} shift, "
                f"{line.actual_start:%d %b %Y}"
            ),
            worked_hours=line.worked_hours,
            bill_rate=line.bill_rate,
            amount=amount,
        )
    pdf_lines = [
        "IMMploy Tax Invoice",
        invoice.issuer_legal_name,
        *invoice.issuer_address.splitlines(),
        f"VAT number: {invoice.issuer_vat_number}",
        "",
        f"Invoice: {invoice.number}",
        f"Date: {invoice.invoice_date:%d %B %Y}",
        f"Client: {invoice.client_name}",
        f"Account: {invoice.accounting_code}",
        *invoice.client_billing_address.splitlines(),
        *(
            [f"Client VAT number: {invoice.client_vat_number}"]
            if invoice.client_vat_number
            else []
        ),
        "",
    ]
    pdf_lines.extend(
        f"{item.timesheet_number} | {item.description} | "
        f"{item.worked_hours:.2f} h x R {item.bill_rate:.2f} = R {item.amount:.2f}"
        for item in invoice.lines.all()
    )
    pdf_lines.extend([
        "",
        f"Subtotal: R {invoice.subtotal:.2f}",
        f"VAT ({invoice.vat_percent:.2f}%): R {invoice.vat_amount:.2f}",
        f"Total: R {invoice.total:.2f}",
    ])
    try:
        invoice.document.save(
            f"{invoice.number}.pdf",
            ContentFile(build_invoice_pdf(pdf_lines)),
            save=True,
        )
        Timesheet.objects.filter(pk__in=ids).update(invoiced_at=timezone.now())
    except Exception:
        if invoice.document.name:
            invoice.document.delete(save=False)
        raise
    return invoice


def _pastel_period(invoice_date):
    return ((invoice_date.month - 3) % 12) + 1


def _quoted(value):
    return f'"{str(value).replace(chr(34), chr(34) * 2)}"'


@transaction.atomic
def generate_pastel_export(*, invoice_ids, actor):
    ids = sorted(set(invoice_ids))
    if not ids:
        raise ValidationError("Select at least one invoice for Pastel export.")
    if len(ids) != len(invoice_ids):
        raise ValidationError("An invoice may only appear once in a Pastel batch.")
    invoices = list(
        Invoice.objects.select_for_update().filter(pk__in=ids).order_by("pk")
    )
    if len(invoices) != len(ids):
        raise ValidationError("One or more selected invoices do not exist.")
    contra_account = FinanceSettings.current().sales_contra_account.strip()
    if not contra_account:
        raise ValidationError("Configure the Pastel sales contra account before export.")
    rows = []
    for invoice in invoices:
        if not invoice.document:
            raise ValidationError(f"Invoice {invoice.number} has no generated PDF.")
        if invoice.pastel_exported_at is not None:
            raise ValidationError(f"Invoice {invoice.number} is already exported to Pastel.")
        rows.append(",".join([
            str(_pastel_period(invoice.invoice_date)),
            _quoted(invoice.invoice_date.strftime("%d/%m/%Y")),
            _quoted("D"),
            _quoted(invoice.accounting_code),
            _quoted(invoice.number),
            _quoted("TS Invoice"),
            f"{invoice.total:.2f}",
            "15",
            f"{invoice.vat_amount:.2f}",
            _quoted(" "),
            _quoted("    "),
            _quoted(contra_account),
            "1", "1", "0", "0", "0",
            f"{invoice.total:.2f}",
        ]))
    content = "\r\n".join(rows) + "\r\n"
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    batch = FinanceExportBatch.objects.create(
        kind=FinanceExportBatch.Kind.PASTEL_SALES,
        process_code=f"PASTEL-{'-'.join(str(value) for value in ids)}",
        file_name=f"IMMploy-Pastel-sales-{'-'.join(str(value) for value in ids)}.csv",
        content=content,
        sha256=digest,
        generated_by=actor,
    )
    batch.invoices.set(invoices)
    Invoice.objects.filter(pk__in=ids).update(pastel_exported_at=timezone.now())
    return batch


@transaction.atomic
def confirm_export_upload(*, batch_ids, actor):
    ids = sorted(set(batch_ids))
    if not ids:
        raise ValidationError("Select at least one export batch to confirm.")
    if len(ids) != len(batch_ids):
        raise ValidationError("An export batch may only appear once in a confirmation.")
    batches = list(
        FinanceExportBatch.objects.select_for_update()
        .filter(pk__in=ids)
        .order_by("pk")
    )
    if len(batches) != len(ids):
        raise ValidationError("One or more selected export batches do not exist.")
    for batch in batches:
        if batch.status != FinanceExportBatch.Status.GENERATED:
            raise ValidationError(
                f"Export batch {batch.process_code} is already confirmed or void."
            )

    confirmed_at = timezone.now()
    FinanceExportBatch.objects.filter(pk__in=ids).update(
        status=FinanceExportBatch.Status.UPLOAD_CONFIRMED,
        upload_confirmed_by=actor,
        upload_confirmed_at=confirmed_at,
    )
    return len(batches)