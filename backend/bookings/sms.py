import base64
import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from bookings.models import Booking, SmsMessage


E164_PATTERN = re.compile(r"^\+[1-9]\d{7,14}$")
PHONE_INPUT_PATTERN = re.compile(r"^[\d\s()+-]+$")
MAX_SMS_BODY_LENGTH = 459


class SmsProviderError(Exception):
    pass


class MyMobileApiClient:
    def __init__(self, *, opener=None, timeout=15):
        self.opener = opener or urlopen
        self.timeout = timeout

    def validate_configuration(self):
        base_url = settings.SMS_MYMOBILEAPI_BASE_URL.rstrip("/")
        if urlsplit(base_url).scheme != "https":
            raise SmsProviderError("SMS provider base URL must use HTTPS.")
        client_id = settings.SMS_MYMOBILEAPI_CLIENT_ID
        secret = settings.SMS_MYMOBILEAPI_SECRET
        if not client_id or not secret:
            raise SmsProviderError("SMS provider credentials are not configured.")
        return base_url, client_id, secret

    def send(self, message):
        base_url, client_id, secret = self.validate_configuration()
        encoded_credentials = base64.b64encode(
            f"{client_id}:{secret}".encode("utf-8")
        ).decode("ascii")
        payload = json.dumps({
            "messages": [{
                "content": message.body,
                "destination": message.destination,
                "customerId": message.customer_id,
            }]
        }).encode("utf-8")
        request = Request(
            f"{base_url}/v3/BulkMessages",
            data=payload,
            method="POST",
            headers={
                "Authorization": f"Basic {encoded_credentials}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with self.opener(request, timeout=self.timeout) as response:
                if response.status != 200:
                    raise SmsProviderError(
                        f"SMS provider rejected the request with HTTP {response.status}."
                    )
                result = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise SmsProviderError(
                f"SMS provider rejected the request with HTTP {exc.code}."
            ) from exc
        except (URLError, TimeoutError) as exc:
            raise SmsProviderError("SMS provider could not be reached.") from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SmsProviderError("SMS provider returned an invalid response.") from exc

        event_id = result.get("eventId") if isinstance(result, dict) else None
        if event_id is None:
            raise SmsProviderError("SMS provider response did not include an event ID.")
        return str(event_id)


def normalize_phone_number(value):
    raw = (value or "").strip()
    if not raw or not PHONE_INPUT_PATTERN.fullmatch(raw):
        raise ValidationError("Candidate mobile number is missing or invalid.")
    compact = re.sub(r"[\s()-]", "", raw)
    if compact.startswith("00"):
        compact = f"+{compact[2:]}"
    elif compact.startswith("0") and len(compact) == 10:
        compact = f"+27{compact[1:]}"
    elif compact.startswith("27") and len(compact) == 11:
        compact = f"+{compact}"
    if not E164_PATTERN.fullmatch(compact):
        raise ValidationError("Candidate mobile number must be a valid E.164 number.")
    return compact


def mask_phone_number(value):
    return f"{value[:4]}{'*' * max(1, len(value) - 8)}{value[-4:]}"


def render_booking_confirmation_sms(booking):
    starts_at = timezone.localtime(booking.shift.starts_at)
    ends_at = timezone.localtime(booking.shift.ends_at)
    return (
        f"Hello {booking.candidate.full_name}, your IMMploy booking at "
        f"{booking.shift.site.client.name} - {booking.shift.site.name} is confirmed for "
        f"{starts_at:%d %B %Y %H:%M} to {ends_at:%d %B %Y %H:%M}."
    )


def _claim_next_sms_message():
    with transaction.atomic():
        message = (
            SmsMessage.objects.select_for_update()
            .filter(status=SmsMessage.Status.QUEUED)
            .order_by("requested_at", "id")
            .first()
        )
        if message is None:
            return None
        message.status = SmsMessage.Status.PROCESSING
        message.processing_started_at = timezone.now()
        message.attempt_count += 1
        message.last_error = ""
        message.save(update_fields=[
            "status",
            "processing_started_at",
            "attempt_count",
            "last_error",
        ])
        return message


def process_sms_outbox(*, client=None, limit=100):
    if limit < 1 or limit > 1000:
        raise ValueError("SMS outbox limit must be between 1 and 1000.")
    provider = client or MyMobileApiClient()
    validate_configuration = getattr(provider, "validate_configuration", None)
    if validate_configuration is not None:
        validate_configuration()
    result = {"accepted": 0, "failed": 0}
    for _ in range(limit):
        message = _claim_next_sms_message()
        if message is None:
            break
        try:
            event_id = provider.send(message)
        except SmsProviderError as exc:
            error_message = str(exc)
        except Exception:
            error_message = "Unexpected SMS provider error."
        else:
            with transaction.atomic():
                locked = SmsMessage.objects.select_for_update().get(pk=message.pk)
                if locked.status == SmsMessage.Status.PROCESSING:
                    locked.status = SmsMessage.Status.ACCEPTED
                    locked.provider_event_id = event_id
                    locked.accepted_at = timezone.now()
                    locked.last_error = ""
                    locked.save(update_fields=[
                        "status",
                        "provider_event_id",
                        "accepted_at",
                        "last_error",
                    ])
            result["accepted"] += 1
            continue

        with transaction.atomic():
            locked = SmsMessage.objects.select_for_update().get(pk=message.pk)
            if locked.status == SmsMessage.Status.PROCESSING:
                locked.status = SmsMessage.Status.FAILED
                locked.last_error = error_message
                locked.save(update_fields=["status", "last_error"])
        result["failed"] += 1
    return result


@transaction.atomic
def queue_booking_confirmation_sms(*, booking_id, actor, body=None):
    if not actor or not actor.is_authenticated or not actor.has_perm(
        "bookings.send_booking_sms"
    ):
        raise PermissionDenied("You do not have permission to send booking SMS messages.")

    booking = (
        Booking.objects.select_for_update()
        .select_related("candidate", "shift__site__client")
        .get(pk=booking_id)
    )
    if booking.status != Booking.Status.CONFIRMED:
        raise ValidationError("Only confirmed bookings can receive a confirmation SMS.")
    if SmsMessage.objects.filter(booking=booking).exists():
        raise ValidationError("A confirmation SMS has already been queued for this booking.")

    destination = normalize_phone_number(booking.candidate.phone)
    rendered_body = (body if body is not None else render_booking_confirmation_sms(booking)).strip()
    if not rendered_body:
        raise ValidationError("SMS message text is required.")
    if len(rendered_body) > MAX_SMS_BODY_LENGTH:
        raise ValidationError(
            f"SMS message text cannot exceed {MAX_SMS_BODY_LENGTH} characters."
        )

    return SmsMessage.objects.create(
        booking=booking,
        candidate=booking.candidate,
        destination=destination,
        body=rendered_body,
        customer_id=f"booking-confirmation:{booking.pk}",
        requested_by=actor,
    )
