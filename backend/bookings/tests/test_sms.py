from datetime import datetime
from decimal import Decimal
import json
from io import StringIO

import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings
from django.test import RequestFactory
from django.utils import timezone
from rest_framework.test import APIClient

from bookings.models import (
    Booking,
    Candidate,
    Client,
    Department,
    LegacyUserProfile,
    Profession,
    Shift,
    Site,
    SmsMessage,
)
from bookings.sms import (
    MyMobileApiClient,
    process_sms_outbox,
    queue_booking_confirmation_sms,
)


@pytest.mark.django_db
def test_confirmed_booking_sms_is_snapshotted_in_the_outbox():
    actor = get_user_model().objects.create_superuser(
        username="sms-scheduler",
        password="local-test-password",
    )
    client = Client.objects.create(name="SMS Hospital")
    site = Site.objects.create(client=client, name="SMS Ward")
    profession = Profession.objects.create(name="SMS Nurse")
    candidate = Candidate.objects.create(
        first_name="Nomsa",
        last_name="Dlamini",
        phone="082 123 4567",
        compliance_status=Candidate.ComplianceStatus.CLEARED,
    )
    candidate.professions.add(profession)
    shift = Shift.objects.create(
        site=site,
        profession=profession,
        starts_at=timezone.make_aware(datetime(2026, 9, 12, 20, 0)),
        ends_at=timezone.make_aware(datetime(2026, 9, 13, 3, 0)),
        pay_rate=Decimal("225.00"),
        bill_rate=Decimal("425.00"),
    )
    booking = Booking.objects.create(
        shift=shift,
        candidate=candidate,
        status=Booking.Status.CONFIRMED,
    )

    message = queue_booking_confirmation_sms(booking_id=booking.id, actor=actor)

    assert message.status == SmsMessage.Status.QUEUED
    assert message.booking == booking
    assert message.candidate == candidate
    assert message.destination == "+27821234567"
    assert message.customer_id == f"booking-confirmation:{booking.id}"
    assert message.requested_by == actor
    assert "Nomsa Dlamini" in message.body
    assert "SMS Hospital" in message.body
    assert "SMS Ward" in message.body
    assert "12 September 2026 20:00 to 13 September 2026 03:00" in message.body
    assert message.provider_event_id == ""


@pytest.mark.django_db
@override_settings(
    SMS_MYMOBILEAPI_BASE_URL="https://rest.mymobileapi.com",
    SMS_MYMOBILEAPI_CLIENT_ID="test-client-id",
    SMS_MYMOBILEAPI_SECRET="test-secret",
)
def test_mymobileapi_client_sends_the_snapshotted_message_over_https():
    actor = get_user_model().objects.create_superuser(username="sms-provider-user")
    client = Client.objects.create(name="Provider Hospital")
    site = Site.objects.create(client=client, name="Provider Ward")
    profession = Profession.objects.create(name="Provider Nurse")
    candidate = Candidate.objects.create(
        first_name="Lerato",
        last_name="Mokoena",
        phone="+27821234567",
    )
    shift = Shift.objects.create(
        site=site,
        profession=profession,
        starts_at=timezone.make_aware(datetime(2026, 10, 1, 8, 0)),
        ends_at=timezone.make_aware(datetime(2026, 10, 1, 15, 0)),
        pay_rate=Decimal("225.00"),
        bill_rate=Decimal("425.00"),
    )
    booking = Booking.objects.create(shift=shift, candidate=candidate)
    message = SmsMessage.objects.create(
        booking=booking,
        candidate=candidate,
        destination="+27821234567",
        body="Your IMMploy booking is confirmed.",
        customer_id=f"booking-confirmation:{booking.id}",
        requested_by=actor,
    )
    captured = {}

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps({"eventId": 2235442184, "messages": 1}).encode()

    def open_request(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return Response()

    event_id = MyMobileApiClient(opener=open_request).send(message)

    request = captured["request"]
    assert request.full_url == "https://rest.mymobileapi.com/v3/BulkMessages"
    assert request.method == "POST"
    assert request.get_header("Content-type") == "application/json"
    assert request.get_header("Authorization").startswith("Basic ")
    assert b"test-secret" not in request.data
    assert json.loads(request.data) == {
        "messages": [{
            "content": message.body,
            "destination": message.destination,
            "customerId": message.customer_id,
        }]
    }
    assert captured["timeout"] == 15
    assert event_id == "2235442184"


@pytest.mark.django_db
def test_sms_outbox_worker_records_provider_acceptance():
    actor = get_user_model().objects.create_superuser(username="sms-worker-user")
    client = Client.objects.create(name="Worker Hospital")
    site = Site.objects.create(client=client, name="Worker Ward")
    profession = Profession.objects.create(name="Worker Nurse")
    candidate = Candidate.objects.create(first_name="Worker", last_name="Candidate")
    shift = Shift.objects.create(
        site=site,
        profession=profession,
        starts_at=timezone.make_aware(datetime(2026, 10, 1, 8, 0)),
        ends_at=timezone.make_aware(datetime(2026, 10, 1, 15, 0)),
        pay_rate=Decimal("225.00"),
        bill_rate=Decimal("425.00"),
    )
    booking = Booking.objects.create(shift=shift, candidate=candidate)
    message = SmsMessage.objects.create(
        booking=booking,
        candidate=candidate,
        destination="+27821234567",
        body="Worker message",
        customer_id=f"booking-confirmation:{booking.id}",
        requested_by=actor,
    )

    class Provider:
        def send(self, queued_message):
            assert queued_message.pk == message.pk
            assert queued_message.status == SmsMessage.Status.PROCESSING
            return "998877"

    result = process_sms_outbox(client=Provider(), limit=10)

    message.refresh_from_db()
    assert result == {"accepted": 1, "failed": 0}
    assert message.status == SmsMessage.Status.ACCEPTED
    assert message.provider_event_id == "998877"
    assert message.attempt_count == 1
    assert message.processing_started_at is not None
    assert message.accepted_at is not None
    assert message.last_error == ""


@pytest.mark.django_db
def test_authorised_scheduler_previews_and_queues_a_booking_sms():
    actor = get_user_model().objects.create_user(
        username="sms-api-scheduler",
        is_staff=True,
    )
    actor.user_permissions.add(
        Permission.objects.get(codename="manage_bookings"),
        Permission.objects.get(codename="send_booking_sms"),
    )
    api_client = APIClient()
    api_client.force_authenticate(user=actor)
    client = Client.objects.create(name="API SMS Hospital")
    site = Site.objects.create(client=client, name="API SMS Ward")
    profession = Profession.objects.create(name="API SMS Nurse")
    candidate = Candidate.objects.create(
        first_name="Api",
        last_name="Candidate",
        phone="0831234567",
        compliance_status=Candidate.ComplianceStatus.CLEARED,
    )
    candidate.professions.add(profession)
    shift = Shift.objects.create(
        site=site,
        profession=profession,
        starts_at=timezone.make_aware(datetime(2026, 10, 2, 8, 0)),
        ends_at=timezone.make_aware(datetime(2026, 10, 2, 15, 0)),
        pay_rate=Decimal("225.00"),
        bill_rate=Decimal("425.00"),
    )
    booking = Booking.objects.create(
        shift=shift,
        candidate=candidate,
        status=Booking.Status.CONFIRMED,
    )
    endpoint = f"/api/bookings/{booking.id}/confirmation-sms/"

    preview = api_client.get(endpoint)
    queued = api_client.post(endpoint, {"body": "Edited booking confirmation."}, format="json")

    assert preview.status_code == 200
    assert preview.json()["status"] == "not_queued"
    assert preview.json()["destination"] == "+278****4567"
    assert "API SMS Hospital" in preview.json()["body"]
    assert queued.status_code == 201
    assert queued.json() == {
        "id": SmsMessage.objects.get().id,
        "status": "queued",
        "body": "Edited booking confirmation.",
        "destination": "+278****4567",
    }
    assert SmsMessage.objects.get().provider_event_id == ""


@pytest.mark.django_db
@override_settings(
    SMS_MYMOBILEAPI_CLIENT_ID="",
    SMS_MYMOBILEAPI_SECRET="",
)
def test_sms_outbox_command_leaves_messages_queued_without_provider_credentials():
    actor = get_user_model().objects.create_superuser(username="sms-command-user")
    client = Client.objects.create(name="Command Hospital")
    site = Site.objects.create(client=client, name="Command Ward")
    profession = Profession.objects.create(name="Command Nurse")
    candidate = Candidate.objects.create(first_name="Command", last_name="Candidate")
    shift = Shift.objects.create(
        site=site,
        profession=profession,
        starts_at=timezone.make_aware(datetime(2026, 10, 3, 8, 0)),
        ends_at=timezone.make_aware(datetime(2026, 10, 3, 15, 0)),
        pay_rate=Decimal("225.00"),
        bill_rate=Decimal("425.00"),
    )
    booking = Booking.objects.create(shift=shift, candidate=candidate)
    message = SmsMessage.objects.create(
        booking=booking,
        candidate=candidate,
        destination="+27821234567",
        body="Command message",
        customer_id=f"booking-confirmation:{booking.id}",
        requested_by=actor,
    )
    stdout = StringIO()

    with pytest.raises(CommandError, match="credentials are not configured"):
        call_command("send_sms_outbox", limit=10, stdout=stdout)

    message.refresh_from_db()
    assert message.status == SmsMessage.Status.QUEUED
    assert message.attempt_count == 0
    assert message.provider_event_id == ""
    assert message.last_error == ""
    assert stdout.getvalue() == ""


@pytest.mark.django_db
def test_sms_admin_is_an_immutable_audit_log():
    user = get_user_model().objects.create_superuser(username="sms-admin-user")
    request = RequestFactory().get("/admin/bookings/smsmessage/")
    request.user = user

    model_admin = admin.site._registry[SmsMessage]

    assert model_admin.has_view_permission(request)
    assert not model_admin.has_add_permission(request)
    assert not model_admin.has_change_permission(request)
    assert not model_admin.has_delete_permission(request)
    assert "body" not in model_admin.list_display
    assert "destination" not in model_admin.list_display


def create_sms_booking(*, prefix, phone="0821234567", status=Booking.Status.CONFIRMED):
    client = Client.objects.create(name=f"{prefix} Hospital")
    site = Site.objects.create(client=client, name=f"{prefix} Ward")
    profession = Profession.objects.create(name=f"{prefix} Nurse")
    candidate = Candidate.objects.create(
        first_name=prefix,
        last_name="Candidate",
        phone=phone,
        compliance_status=Candidate.ComplianceStatus.CLEARED,
    )
    candidate.professions.add(profession)
    shift = Shift.objects.create(
        site=site,
        profession=profession,
        starts_at=timezone.make_aware(datetime(2026, 11, 1, 8, 0)),
        ends_at=timezone.make_aware(datetime(2026, 11, 1, 15, 0)),
        pay_rate=Decimal("225.00"),
        bill_rate=Decimal("425.00"),
    )
    return Booking.objects.create(
        shift=shift,
        candidate=candidate,
        status=status,
    )


@pytest.mark.django_db
def test_booking_manager_without_sms_permission_is_denied():
    actor = get_user_model().objects.create_user(username="booking-only-user", is_staff=True)
    actor.user_permissions.add(Permission.objects.get(codename="manage_bookings"))
    booking = create_sms_booking(prefix="NoSmsPermission")
    api_client = APIClient()
    api_client.force_authenticate(user=actor)

    response = api_client.post(
        f"/api/bookings/{booking.id}/confirmation-sms/",
        {"body": "Not authorised."},
        format="json",
    )

    assert response.status_code == 403
    assert not SmsMessage.objects.exists()


@pytest.mark.django_db
def test_booking_sms_is_hidden_across_department_boundaries():
    allowed_department = Department.objects.create(
        name="Allowed SMS Desk",
        legacy_mysql_id=701,
    )
    other_department = Department.objects.create(
        name="Other SMS Desk",
        legacy_mysql_id=702,
    )
    actor = get_user_model().objects.create_user(username="desk-sms-user", is_staff=True)
    LegacyUserProfile.objects.create(
        user=actor,
        legacy_mysql_id=9701,
        assigned_desk=allowed_department.legacy_mysql_id,
        link_conf=True,
    )
    actor.user_permissions.add(Permission.objects.get(codename="send_booking_sms"))
    booking = create_sms_booking(prefix="OtherDesk")
    booking.shift.site.client.departments.add(other_department)
    booking.candidate.departments.add(other_department)
    api_client = APIClient()
    api_client.force_authenticate(user=actor)

    response = api_client.get(f"/api/bookings/{booking.id}/confirmation-sms/")

    assert response.status_code == 404
    assert not SmsMessage.objects.exists()


@pytest.mark.django_db
def test_invalid_candidate_phone_creates_no_sms_message():
    actor = get_user_model().objects.create_superuser(username="invalid-phone-sms-user")
    booking = create_sms_booking(prefix="InvalidPhone", phone="not-a-phone")

    with pytest.raises(DjangoValidationError, match="mobile number"):
        queue_booking_confirmation_sms(booking_id=booking.id, actor=actor)

    assert not SmsMessage.objects.exists()


@pytest.mark.django_db
def test_duplicate_booking_sms_request_creates_only_one_message():
    actor = get_user_model().objects.create_superuser(username="duplicate-sms-user")
    booking = create_sms_booking(prefix="DuplicateSms")

    queue_booking_confirmation_sms(booking_id=booking.id, actor=actor)
    with pytest.raises(DjangoValidationError, match="already been queued"):
        queue_booking_confirmation_sms(booking_id=booking.id, actor=actor)

    assert SmsMessage.objects.count() == 1
