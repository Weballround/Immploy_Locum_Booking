from datetime import datetime, timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from bookings.models import (
    Candidate,
    Client,
    ClientProfessionRate,
    LegacyUserProfile,
    Profession,
    Site,
)
from bookings.serializers import (
    CandidateNewShiftInputSerializer,
    FacilityBookNowInputSerializer,
    ShiftSerializer,
    VacancyShiftInputSerializer,
)


@pytest.mark.django_db
def test_booking_creation_serializers_reject_times_outside_quarter_hours():
    actor = get_user_model().objects.create_user(username="nursing-quarter-hour-booker")
    LegacyUserProfile.objects.create(
        user=actor,
        legacy_mysql_id=8800,
        assigned_desk=3,
        link_conf=True,
    )
    request = type("Request", (), {"user": actor})()
    context = {"request": request}
    client = Client.objects.create(name="Quarter-hour Client")
    site = Site.objects.create(client=client, name="Quarter-hour Facility")
    profession = Profession.objects.create(name="Quarter-hour Role")
    candidate = Candidate.objects.create(first_name="Quarter", last_name="Hour")
    starts_at = timezone.make_aware(datetime(2026, 9, 10, 7, 7))
    ends_at = starts_at + timedelta(hours=7)
    shared_times = {
        "starts_at": starts_at.isoformat(),
        "ends_at": ends_at.isoformat(),
    }
    serializers = [
        VacancyShiftInputSerializer(
            data={**shared_times, "pay_rate": "225.00"},
            context=context,
        ),
        CandidateNewShiftInputSerializer(data=shared_times, context=context),
        FacilityBookNowInputSerializer(
            data={
                **shared_times,
                "site": site.id,
                "profession": profession.id,
                "candidate": candidate.id,
            },
            context=context,
        ),
        ShiftSerializer(
            data={
                **shared_times,
                "site": site.id,
                "profession": profession.id,
                "pay_rate": "225.00",
            },
            context=context,
        ),
    ]

    for serializer in serializers:
        assert not serializer.is_valid()
        assert "15-minute" in str(serializer.errors)


@pytest.mark.django_db
def test_permanent_desk_accepts_whole_minute_booking_times():
    actor = get_user_model().objects.create_user(username="per-minute-booker", is_staff=True)
    LegacyUserProfile.objects.create(
        user=actor,
        legacy_mysql_id=8801,
        assigned_desk=6,
        link_conf=True,
    )
    request = type("Request", (), {"user": actor})()
    context = {"request": request}
    client = Client.objects.create(name="Per-minute Client")
    site = Site.objects.create(client=client, name="Per-minute Facility")
    profession = Profession.objects.create(name="Per-minute Role")
    ClientProfessionRate.objects.create(
        client=client,
        profession=profession,
        pay_rate="225.00",
        bill_rate="425.00",
    )
    candidate = Candidate.objects.create(first_name="Per", last_name="Minute")
    starts_at = timezone.make_aware(datetime(2026, 9, 10, 7, 7))
    ends_at = starts_at + timedelta(hours=7)
    shared_times = {
        "starts_at": starts_at.isoformat(),
        "ends_at": ends_at.isoformat(),
    }
    serializers = [
        VacancyShiftInputSerializer(
            data={**shared_times, "pay_rate": "225.00"},
            context=context,
        ),
        CandidateNewShiftInputSerializer(data=shared_times, context=context),
        FacilityBookNowInputSerializer(
            data={
                **shared_times,
                "site": site.id,
                "profession": profession.id,
                "candidate": candidate.id,
            },
            context=context,
        ),
        ShiftSerializer(
            data={
                **shared_times,
                "site": site.id,
                "profession": profession.id,
                "pay_rate": "225.00",
            },
            context=context,
        ),
    ]

    for serializer in serializers:
        assert serializer.is_valid(), serializer.errors
