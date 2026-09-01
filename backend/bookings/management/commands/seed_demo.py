from datetime import time, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone

from bookings.models import Booking, Candidate, Client, Profession, Shift, Site


class Command(BaseCommand):
    help = "Create a small, idempotent demo schedule for local development."

    def handle(self, *args, **options):
        nurse, _ = Profession.objects.get_or_create(name="Registered Nurse")
        pharmacist, _ = Profession.objects.get_or_create(name="Locum Pharmacist")

        hospital, _ = Client.objects.get_or_create(name="Rosebank Day Hospital")
        pharmacy, _ = Client.objects.get_or_create(name="Central Pharmacy Group")
        ward, _ = Site.objects.get_or_create(client=hospital, name="Ward A")
        dispensary, _ = Site.objects.get_or_create(client=pharmacy, name="Sandton Dispensary")

        candidate_specs = [
            ("Lerato", "Maseko", nurse),
            ("Sihle", "Makeleni", nurse),
            ("Naledi", "Mokoena", pharmacist),
        ]
        candidates = []
        for first_name, last_name, profession in candidate_specs:
            candidate, _ = Candidate.objects.get_or_create(
                first_name=first_name,
                last_name=last_name,
                defaults={"compliance_status": Candidate.ComplianceStatus.CLEARED},
            )
            candidate.compliance_status = Candidate.ComplianceStatus.CLEARED
            candidate.save(update_fields=["compliance_status"])
            candidate.professions.add(profession)
            candidates.append(candidate)

        today = timezone.localdate()
        schedule = [
            (ward, nurse, 1, time(7, 30), 12, Decimal("210.00"), Decimal("400.00")),
            (dispensary, pharmacist, 2, time(8, 0), 9, Decimal("230.00"), Decimal("440.00")),
            (ward, nurse, 3, time(19, 0), 12, Decimal("245.00"), Decimal("450.00")),
        ]
        shifts = []
        for site, profession, day_offset, start_time, hours, pay, bill in schedule:
            start = timezone.make_aware(
                timezone.datetime.combine(today + timedelta(days=day_offset), start_time)
            )
            shift, _ = Shift.objects.get_or_create(
                site=site,
                profession=profession,
                starts_at=start,
                defaults={
                    "ends_at": start + timedelta(hours=hours),
                    "pay_rate": pay,
                    "bill_rate": bill,
                },
            )
            shifts.append(shift)

        booked_shift = shifts[2]
        booking, _ = Booking.objects.get_or_create(
            shift=booked_shift,
            candidate=candidates[1],
            defaults={"status": Booking.Status.CONFIRMED},
        )
        if booking.status != Booking.Status.CONFIRMED:
            booking.status = Booking.Status.CONFIRMED
            booking.save(update_fields=["status"])

        self.stdout.write(self.style.SUCCESS("Demo clients, candidates and shifts are ready."))
