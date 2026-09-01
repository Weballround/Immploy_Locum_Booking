from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Barrier

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, close_old_connections
from django.utils import timezone

from bookings.models import (
    Booking,
    BookingRule,
    Candidate,
    Client,
    Profession,
    Shift,
    Site,
)


@pytest.mark.django_db
def test_confirming_booking_marks_shift_booked():
    profession = Profession.objects.create(name="Registered Nurse")
    client = Client.objects.create(name="Web Allround Medical")
    site = Site.objects.create(client=client, name="Main Hospital")
    candidate = Candidate.objects.create(
        first_name="Sihle",
        last_name="Makeleni",
        compliance_status=Candidate.ComplianceStatus.CLEARED,
    )
    candidate.professions.add(profession)
    start = timezone.make_aware(datetime(2026, 8, 3, 8, 0))
    shift = Shift.objects.create(
        site=site,
        profession=profession,
        starts_at=start,
        ends_at=start + timedelta(hours=8),
        pay_rate="180.00",
        bill_rate="350.00",
    )

    Booking.objects.create(
        shift=shift,
        candidate=candidate,
        status=Booking.Status.CONFIRMED,
    )

    shift.refresh_from_db()
    assert shift.status == Shift.Status.BOOKED


@pytest.mark.django_db
def test_candidate_cannot_be_confirmed_for_overlapping_shifts():
    profession = Profession.objects.create(name="Locum Pharmacist")
    client = Client.objects.create(name="Central Pharmacy")
    site = Site.objects.create(client=client, name="Rosebank")
    candidate = Candidate.objects.create(
        first_name="Naledi",
        last_name="Mokoena",
        compliance_status=Candidate.ComplianceStatus.CLEARED,
    )
    candidate.professions.add(profession)
    start = timezone.make_aware(datetime(2026, 8, 4, 8, 0))
    first_shift = Shift.objects.create(
        site=site,
        profession=profession,
        starts_at=start,
        ends_at=start + timedelta(hours=8),
        pay_rate="200.00",
        bill_rate="380.00",
    )
    overlapping_shift = Shift.objects.create(
        site=site,
        profession=profession,
        starts_at=start + timedelta(hours=4),
        ends_at=start + timedelta(hours=12),
        pay_rate="200.00",
        bill_rate="380.00",
    )
    Booking.objects.create(
        shift=first_shift,
        candidate=candidate,
        status=Booking.Status.CONFIRMED,
    )

    with pytest.raises(ValidationError, match="already booked"):
        Booking.objects.create(
            shift=overlapping_shift,
            candidate=candidate,
            status=Booking.Status.CONFIRMED,
        )


@pytest.mark.django_db
def test_candidate_cannot_be_double_booked_at_different_locations():
    profession = Profession.objects.create(name="Cross-location Doctor")
    first_client = Client.objects.create(name="North Hospital")
    second_client = Client.objects.create(name="South Hospital")
    first_site = Site.objects.create(client=first_client, name="Emergency Unit")
    second_site = Site.objects.create(client=second_client, name="Theatre")
    candidate = Candidate.objects.create(
        first_name="Global",
        last_name="Locum",
        compliance_status=Candidate.ComplianceStatus.CLEARED,
    )
    candidate.professions.add(profession)
    start = timezone.make_aware(datetime(2026, 8, 4, 8, 0))
    first_shift = Shift.objects.create(
        site=first_site,
        profession=profession,
        starts_at=start,
        ends_at=start + timedelta(hours=8),
        pay_rate="200.00",
        bill_rate="380.00",
    )
    second_shift = Shift.objects.create(
        site=second_site,
        profession=profession,
        starts_at=start + timedelta(hours=2),
        ends_at=start + timedelta(hours=10),
        pay_rate="220.00",
        bill_rate="410.00",
    )
    Booking.objects.create(
        shift=first_shift,
        candidate=candidate,
        status=Booking.Status.CONFIRMED,
    )

    with pytest.raises(ValidationError, match="another confirmed booking"):
        Booking.objects.create(
            shift=second_shift,
            candidate=candidate,
            status=Booking.Status.CONFIRMED,
        )


@pytest.mark.django_db
def test_admin_defined_minimum_rest_applies_between_different_locations():
    BookingRule.objects.update_or_create(
        pk=1,
        defaults={"minimum_rest_minutes": 60},
    )
    profession = Profession.objects.create(name="Rest-rule Nurse")
    first_client = Client.objects.create(name="Day Hospital")
    second_client = Client.objects.create(name="Night Hospital")
    first_site = Site.objects.create(client=first_client, name="Day Ward")
    second_site = Site.objects.create(client=second_client, name="Night Ward")
    candidate = Candidate.objects.create(
        first_name="Rested",
        last_name="Candidate",
        compliance_status=Candidate.ComplianceStatus.CLEARED,
    )
    candidate.professions.add(profession)
    start = timezone.make_aware(datetime(2026, 8, 5, 8, 0))
    first_shift = Shift.objects.create(
        site=first_site,
        profession=profession,
        starts_at=start,
        ends_at=start + timedelta(hours=8),
        pay_rate="200.00",
        bill_rate="380.00",
    )
    too_soon = Shift.objects.create(
        site=second_site,
        profession=profession,
        starts_at=start + timedelta(hours=8, minutes=30),
        ends_at=start + timedelta(hours=16),
        pay_rate="220.00",
        bill_rate="410.00",
    )
    Booking.objects.create(
        shift=first_shift,
        candidate=candidate,
        status=Booking.Status.CONFIRMED,
    )

    with pytest.raises(ValidationError, match="minimum rest period"):
        Booking.objects.create(
            shift=too_soon,
            candidate=candidate,
            status=Booking.Status.CONFIRMED,
        )


@pytest.mark.django_db
def test_candidate_must_be_compliance_cleared_to_confirm_booking():
    profession = Profession.objects.create(name="Radiographer")
    client = Client.objects.create(name="North Clinic")
    site = Site.objects.create(client=client, name="Radiology")
    candidate = Candidate.objects.create(
        first_name="Anele",
        last_name="Dlamini",
        compliance_status=Candidate.ComplianceStatus.PENDING,
    )
    candidate.professions.add(profession)
    start = timezone.make_aware(datetime(2026, 8, 5, 7, 0))
    shift = Shift.objects.create(
        site=site,
        profession=profession,
        starts_at=start,
        ends_at=start + timedelta(hours=8),
        pay_rate="190.00",
        bill_rate="360.00",
    )

    with pytest.raises(ValidationError, match="compliance-cleared"):
        Booking.objects.create(
            shift=shift,
            candidate=candidate,
            status=Booking.Status.CONFIRMED,
        )


@pytest.mark.django_db
def test_confirmation_uses_authoritative_candidate_compliance():
    profession = Profession.objects.create(name="Authoritative Nurse")
    client = Client.objects.create(name="Authoritative Clinic")
    site = Site.objects.create(client=client, name="Ward Authoritative")
    candidate = Candidate.objects.create(
        first_name="Authoritative", last_name="Candidate",
        compliance_status=Candidate.ComplianceStatus.CLEARED,
    )
    candidate.professions.add(profession)
    start = timezone.make_aware(datetime(2026, 8, 4, 8, 0))
    shift = Shift.objects.create(
        site=site, profession=profession, starts_at=start,
        ends_at=start + timedelta(hours=8), pay_rate="175.00", bill_rate="340.00",
    )
    booking = Booking(
        shift=shift, candidate=candidate, status=Booking.Status.CONFIRMED,
    )
    Candidate.objects.filter(pk=candidate.pk).update(
        compliance_status=Candidate.ComplianceStatus.EXPIRED,
    )

    with pytest.raises(ValidationError, match="compliance-cleared"):
        booking.save()


@pytest.mark.django_db
def test_partial_status_save_validates_authoritative_candidate():
    nurse = Profession.objects.create(name="Partial Save Nurse")
    pharmacist = Profession.objects.create(name="Partial Save Pharmacist")
    client = Client.objects.create(name="Partial Save Clinic")
    site = Site.objects.create(client=client, name="Ward Partial")
    cleared = Candidate.objects.create(
        first_name="Cleared", last_name="Nurse",
        compliance_status=Candidate.ComplianceStatus.CLEARED,
    )
    cleared.professions.add(nurse)
    ineligible = Candidate.objects.create(
        first_name="Expired", last_name="Pharmacist",
        compliance_status=Candidate.ComplianceStatus.EXPIRED,
    )
    ineligible.professions.add(pharmacist)
    start = timezone.make_aware(datetime(2026, 8, 4, 18, 0))
    shift = Shift.objects.create(
        site=site, profession=nurse, starts_at=start,
        ends_at=start + timedelta(hours=8), pay_rate="175.00", bill_rate="340.00",
    )
    booking = Booking.objects.create(
        shift=shift, candidate=cleared, status=Booking.Status.OFFERED,
    )
    stale_booking = Booking.objects.get(pk=booking.pk)
    authoritative_booking = Booking.objects.get(pk=booking.pk)
    authoritative_booking.candidate = ineligible
    authoritative_booking.save()
    stale_booking.status = Booking.Status.CONFIRMED

    with pytest.raises(ValidationError, match="compliance-cleared"):
        stale_booking.save(update_fields=["status"])

    booking.refresh_from_db()
    assert booking.status == Booking.Status.OFFERED
    assert booking.candidate == ineligible


@pytest.mark.django_db
def test_candidate_must_have_the_shift_profession_to_confirm_booking():
    nurse = Profession.objects.create(name="Professional Nurse")
    pharmacist = Profession.objects.create(name="Pharmacist")
    client = Client.objects.create(name="East Clinic")
    site = Site.objects.create(client=client, name="Ward C")
    candidate = Candidate.objects.create(
        first_name="Boitumelo",
        last_name="Khumalo",
        compliance_status=Candidate.ComplianceStatus.CLEARED,
    )
    candidate.professions.add(pharmacist)
    start = timezone.make_aware(datetime(2026, 8, 9, 8, 0))
    shift = Shift.objects.create(
        site=site,
        profession=nurse,
        starts_at=start,
        ends_at=start + timedelta(hours=8),
        pay_rate="210.00",
        bill_rate="400.00",
    )

    with pytest.raises(ValidationError, match="required profession"):
        Booking.objects.create(
            shift=shift,
            candidate=candidate,
            status=Booking.Status.CONFIRMED,
        )


@pytest.mark.django_db
def test_shift_cannot_be_confirmed_for_two_candidates():
    profession = Profession.objects.create(name="Enrolled Nurse")
    client = Client.objects.create(name="South Clinic")
    site = Site.objects.create(client=client, name="Ward D")
    first = Candidate.objects.create(
        first_name="Nandi", last_name="Molefe",
        compliance_status=Candidate.ComplianceStatus.CLEARED,
    )
    second = Candidate.objects.create(
        first_name="Ayanda", last_name="Ndlovu",
        compliance_status=Candidate.ComplianceStatus.CLEARED,
    )
    first.professions.add(profession)
    second.professions.add(profession)
    start = timezone.make_aware(datetime(2026, 8, 11, 8, 0))
    shift = Shift.objects.create(
        site=site, profession=profession, starts_at=start,
        ends_at=start + timedelta(hours=8), pay_rate="190.00", bill_rate="360.00",
    )
    Booking.objects.create(
        shift=shift, candidate=first, status=Booking.Status.CONFIRMED,
    )

    with pytest.raises(ValidationError, match="already has a confirmed booking"):
        Booking.objects.create(
            shift=shift, candidate=second, status=Booking.Status.CONFIRMED,
        )


@pytest.mark.django_db(transaction=True)
def test_concurrent_confirmation_allows_only_one_candidate():
    profession = Profession.objects.create(name="Concurrent Nurse")
    client = Client.objects.create(name="Concurrent Clinic")
    site = Site.objects.create(client=client, name="Ward Lock")
    candidates = [
        Candidate.objects.create(
            first_name=f"Candidate {index}", last_name="Concurrent",
            compliance_status=Candidate.ComplianceStatus.CLEARED,
        )
        for index in range(2)
    ]
    for candidate in candidates:
        candidate.professions.add(profession)
    start = timezone.make_aware(datetime(2026, 8, 11, 20, 0))
    shift = Shift.objects.create(
        site=site, profession=profession, starts_at=start,
        ends_at=start + timedelta(hours=8), pay_rate="190.00", bill_rate="360.00",
    )
    barrier = Barrier(2)

    def confirm(candidate_id):
        close_old_connections()
        barrier.wait()
        try:
            Booking.objects.create(
                shift_id=shift.id,
                candidate_id=candidate_id,
                status=Booking.Status.CONFIRMED,
            )
            return "confirmed"
        except (ValidationError, IntegrityError):
            return "blocked"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(confirm, [candidate.id for candidate in candidates]))

    assert sorted(outcomes) == ["blocked", "confirmed"]
    assert Booking.objects.filter(
        shift=shift, status=Booking.Status.CONFIRMED,
    ).count() == 1


@pytest.mark.django_db
def test_cancelled_shift_cannot_be_confirmed():
    profession = Profession.objects.create(name="Ward Nurse")
    client = Client.objects.create(name="North Clinic")
    site = Site.objects.create(client=client, name="Ward E")
    candidate = Candidate.objects.create(
        first_name="Neo", last_name="Mokoena",
        compliance_status=Candidate.ComplianceStatus.CLEARED,
    )
    candidate.professions.add(profession)
    start = timezone.make_aware(datetime(2026, 8, 12, 8, 0))
    shift = Shift.objects.create(
        site=site, profession=profession, starts_at=start,
        ends_at=start + timedelta(hours=8), pay_rate="190.00", bill_rate="360.00",
        status=Shift.Status.CANCELLED,
    )

    with pytest.raises(ValidationError, match="open"):
        Booking.objects.create(
            shift=shift, candidate=candidate, status=Booking.Status.CONFIRMED,
        )


@pytest.mark.django_db
@pytest.mark.parametrize("operation", ["cancel", "delete"])
def test_removing_confirmation_reopens_shift(operation):
    profession = Profession.objects.create(name=f"Agency Nurse {operation}")
    client = Client.objects.create(name=f"Recovery Clinic {operation}")
    site = Site.objects.create(client=client, name="Ward F")
    candidate = Candidate.objects.create(
        first_name="Refilwe", last_name="Dlamini",
        compliance_status=Candidate.ComplianceStatus.CLEARED,
    )
    candidate.professions.add(profession)
    start = timezone.make_aware(datetime(2026, 8, 13, 8, 0))
    shift = Shift.objects.create(
        site=site, profession=profession, starts_at=start,
        ends_at=start + timedelta(hours=8), pay_rate="195.00", bill_rate="370.00",
    )
    booking = Booking.objects.create(
        shift=shift, candidate=candidate, status=Booking.Status.CONFIRMED,
    )

    if operation == "cancel":
        booking.status = Booking.Status.CANCELLED
        booking.save()
    else:
        booking.delete()

    shift.refresh_from_db()
    assert shift.status == Shift.Status.OPEN


@pytest.mark.django_db
def test_moving_confirmation_updates_both_shift_statuses():
    profession = Profession.objects.create(name="Transfer Nurse")
    client = Client.objects.create(name="Transfer Clinic")
    site = Site.objects.create(client=client, name="Ward Transfer")
    candidate = Candidate.objects.create(
        first_name="Move", last_name="Candidate",
        compliance_status=Candidate.ComplianceStatus.CLEARED,
    )
    candidate.professions.add(profession)
    start = timezone.make_aware(datetime(2026, 8, 16, 8, 0))
    first_shift = Shift.objects.create(
        site=site, profession=profession, starts_at=start,
        ends_at=start + timedelta(hours=8), pay_rate="195.00", bill_rate="370.00",
    )
    second_shift = Shift.objects.create(
        site=site, profession=profession, starts_at=start + timedelta(days=1),
        ends_at=start + timedelta(days=1, hours=8),
        pay_rate="195.00", bill_rate="370.00",
    )
    booking = Booking.objects.create(
        shift=first_shift, candidate=candidate, status=Booking.Status.CONFIRMED,
    )

    booking.shift = second_shift
    booking.save()

    first_shift.refresh_from_db()
    second_shift.refresh_from_db()
    assert first_shift.status == Shift.Status.OPEN
    assert second_shift.status == Shift.Status.BOOKED


@pytest.mark.django_db
def test_deleting_stale_booking_instance_reopens_authoritative_shift():
    profession = Profession.objects.create(name="Stale Delete Nurse")
    client = Client.objects.create(name="Stale Delete Clinic")
    site = Site.objects.create(client=client, name="Ward Stale")
    candidate = Candidate.objects.create(
        first_name="Stale", last_name="Delete",
        compliance_status=Candidate.ComplianceStatus.CLEARED,
    )
    candidate.professions.add(profession)
    start = timezone.make_aware(datetime(2026, 8, 18, 8, 0))
    first_shift = Shift.objects.create(
        site=site, profession=profession, starts_at=start,
        ends_at=start + timedelta(hours=8), pay_rate="195.00", bill_rate="370.00",
    )
    second_shift = Shift.objects.create(
        site=site, profession=profession, starts_at=start + timedelta(days=1),
        ends_at=start + timedelta(days=1, hours=8),
        pay_rate="195.00", bill_rate="370.00",
    )
    booking = Booking.objects.create(
        shift=first_shift, candidate=candidate, status=Booking.Status.CONFIRMED,
    )
    stale_booking = Booking.objects.get(pk=booking.pk)
    booking.shift = second_shift
    booking.save()

    stale_booking.delete()

    first_shift.refresh_from_db()
    second_shift.refresh_from_db()
    assert first_shift.status == Shift.Status.OPEN
    assert second_shift.status == Shift.Status.OPEN


@pytest.mark.django_db
def test_queryset_delete_reopens_confirmed_shift():
    profession = Profession.objects.create(name="Bulk Delete Nurse")
    client = Client.objects.create(name="Bulk Delete Clinic")
    site = Site.objects.create(client=client, name="Ward Bulk")
    candidate = Candidate.objects.create(
        first_name="Bulk", last_name="Delete",
        compliance_status=Candidate.ComplianceStatus.CLEARED,
    )
    candidate.professions.add(profession)
    start = timezone.make_aware(datetime(2026, 8, 18, 18, 0))
    shift = Shift.objects.create(
        site=site, profession=profession, starts_at=start,
        ends_at=start + timedelta(hours=8), pay_rate="195.00", bill_rate="370.00",
    )
    booking = Booking.objects.create(
        shift=shift, candidate=candidate, status=Booking.Status.CONFIRMED,
    )

    Booking.objects.filter(pk=booking.pk).delete()

    shift.refresh_from_db()
    assert shift.status == Shift.Status.OPEN


@pytest.mark.django_db
def test_stale_booking_save_cannot_resurrect_deleted_booking():
    profession = Profession.objects.create(name="Stale Save Nurse")
    client = Client.objects.create(name="Stale Save Clinic")
    site = Site.objects.create(client=client, name="Ward Stale Save")
    candidate = Candidate.objects.create(
        first_name="Stale", last_name="Save",
        compliance_status=Candidate.ComplianceStatus.CLEARED,
    )
    candidate.professions.add(profession)
    start = timezone.make_aware(datetime(2026, 8, 20, 8, 0))
    shift = Shift.objects.create(
        site=site, profession=profession, starts_at=start,
        ends_at=start + timedelta(hours=8), pay_rate="195.00", bill_rate="370.00",
    )
    booking = Booking.objects.create(
        shift=shift, candidate=candidate, status=Booking.Status.CONFIRMED,
    )
    stale_booking = Booking.objects.get(pk=booking.pk)
    Booking.objects.get(pk=booking.pk).delete()

    with pytest.raises(ValidationError, match="no longer exists"):
        stale_booking.save()

    assert not Booking.objects.filter(pk=booking.pk).exists()
    shift.refresh_from_db()
    assert shift.status == Shift.Status.OPEN


@pytest.mark.django_db
@pytest.mark.parametrize("manual_status", [Shift.Status.OPEN, Shift.Status.BOOKED])
def test_open_and_booked_statuses_are_derived_from_confirmations(manual_status):
    profession = Profession.objects.create(name=f"Derived Status {manual_status}")
    client = Client.objects.create(name=f"Derived Client {manual_status}")
    site = Site.objects.create(client=client, name="Ward Derived")
    start = timezone.make_aware(datetime(2026, 8, 19, 8, 0))
    shift = Shift.objects.create(
        site=site, profession=profession, starts_at=start,
        ends_at=start + timedelta(hours=8), pay_rate="195.00", bill_rate="370.00",
    )

    if manual_status == Shift.Status.OPEN:
        candidate = Candidate.objects.create(
            first_name="Derived", last_name="Candidate",
            compliance_status=Candidate.ComplianceStatus.CLEARED,
        )
        candidate.professions.add(profession)
        Booking.objects.create(
            shift=shift, candidate=candidate, status=Booking.Status.CONFIRMED,
        )
    shift.status = manual_status

    with pytest.raises(ValidationError, match="managed by confirmed bookings"):
        shift.save()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("end_delta", "pay_rate", "bill_rate", "message"),
    [
        (timedelta(0), "190.00", "360.00", "after"),
        (timedelta(hours=8), "-1.00", "360.00", "greater than or equal"),
        (timedelta(hours=8), "190.00", "-1.00", "greater than or equal"),
    ],
)
def test_shift_rejects_invalid_interval_and_rates(end_delta, pay_rate, bill_rate, message):
    profession = Profession.objects.create(name=f"Validation {pay_rate} {bill_rate}")
    client = Client.objects.create(name=f"Validation client {pay_rate} {bill_rate}")
    site = Site.objects.create(client=client, name="Ward G")
    start = timezone.make_aware(datetime(2026, 8, 14, 8, 0))

    with pytest.raises(ValidationError, match=message):
        Shift.objects.create(
            site=site, profession=profession, starts_at=start,
            ends_at=start + end_delta, pay_rate=pay_rate, bill_rate=bill_rate,
        )
