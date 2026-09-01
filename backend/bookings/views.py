from collections.abc import Mapping
from datetime import timedelta

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Count, Exists, Max, OuterRef, Prefetch, Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from bookings.candidate_locations import candidate_location_options
from bookings.department_scope import (
    scope_queryset_to_user_departments,
    user_can_access_departments,
    user_department_ids,
)
from bookings.models import (
    Booking,
    BookingRule,
    Candidate,
    CandidateChangeAudit,
    CandidateProfileOption,
    ClientProfessionRate,
    FacilityExperience,
    LegacyUserProfile,
    Profession,
    Shift,
    Site,
    SiteProfessionRate,
    SmsMessage,
    Vacancy,
)
from bookings.permissions import (
    CanManageBookings,
    user_can_view_candidate_pay_rates,
    user_can_view_client_charge_rates,
)
from bookings.serializers import (
    BookingSerializer,
    BookingSmsInputSerializer,
    CandidateBookShiftsInputSerializer,
    CandidateDirectorySerializer,
    CandidateProfileSerializer,
    CandidateSummarySerializer,
    FacilityBookNowInputSerializer,
    RankedFacilityCandidateQuerySerializer,
    RankedFacilityCandidateSerializer,
    ShiftSerializer,
    VacancySerializer,
    _configured_rates,
)
from bookings.sa_id import SouthAfricanIdError, decode_south_african_id
from bookings.sms import (
    mask_phone_number,
    normalize_phone_number,
    queue_booking_confirmation_sms,
    render_booking_confirmation_sms,
)


def _booking_rest_interval():
    return timedelta(minutes=BookingRule.current().minimum_rest_minutes)


def _rank_candidates_for_facility(candidates, site, profession_id):
    candidate_ids = [candidate.id for candidate in candidates]
    legacy_experience = {
        row.candidate_id: row
        for row in FacilityExperience.objects.filter(
            candidate_id__in=candidate_ids,
            client=site.client,
            profession_id=profession_id,
        )
    }
    current_experience = {
        row["candidate_id"]: row
        for row in Booking.objects.filter(
            candidate_id__in=candidate_ids,
            status=Booking.Status.CONFIRMED,
            shift__site__client=site.client,
            shift__profession_id=profession_id,
            shift__status=Shift.Status.COMPLETED,
            shift__ends_at__lte=timezone.now(),
        ).values("candidate_id").annotate(
            count=Count("id"),
            last_worked_at=Max("shift__ends_at"),
        )
    }
    client_city = site.client.city.strip().casefold()
    client_region = site.client.region.strip().casefold()
    for candidate in candidates:
        imported = legacy_experience.get(candidate.id)
        current = current_experience.get(candidate.id)
        candidate.facility_shift_count = (
            (imported.completed_shift_count if imported else 0)
            + (current["count"] if current else 0)
        )
        candidate.last_worked_on = imported.last_worked_on if imported else None
        if current and (
            candidate.last_worked_on is None
            or timezone.localdate(current["last_worked_at"]) > candidate.last_worked_on
        ):
            candidate.last_worked_on = timezone.localdate(current["last_worked_at"])

        home_area = candidate.home_area.strip().casefold()
        home_region = candidate.home_region.strip().casefold()
        if home_area and client_city and home_area == client_city:
            candidate.proximity_rank = 0
            candidate.proximity_label = "Same town as facility"
        elif home_region and client_region and home_region == client_region:
            candidate.proximity_rank = 1
            candidate.proximity_label = "Same province as facility"
        else:
            candidate.proximity_rank = 2
            candidate.proximity_label = ""

    candidates.sort(key=lambda candidate: (
        -candidate.facility_shift_count,
        candidate.proximity_rank,
        candidate.full_name.casefold(),
        candidate.id,
    ))


def _require_department_access(user, *department_managers):
    if not all(
        user_can_access_departments(user, manager)
        for manager in department_managers
    ):
        raise PermissionDenied("This record belongs to another department.")


def _can_edit_candidates(user):
    if user.is_superuser:
        return True
    try:
        return bool(user.legacy_profile.edit_cand)
    except LegacyUserProfile.DoesNotExist:
        return user.has_perm("bookings.manage_bookings")


def _candidate_profile_options():
    options = list(CandidateProfileOption.objects.filter(is_active=True))
    by_category = {}
    for option in options:
        payload = {
            "id": option.legacy_mysql_id,
            "label": option.label,
        }
        if option.parent_legacy_mysql_id is not None:
            payload["parent_id"] = option.parent_legacy_mysql_id
        by_category.setdefault(option.category, []).append(payload)
    return {
        "countries": by_category.get(CandidateProfileOption.Category.COUNTRY, []),
        "visa_types": by_category.get(CandidateProfileOption.Category.VISA_TYPE, []),
        "languages": by_category.get(CandidateProfileOption.Category.LANGUAGE, []),
        "divisions": by_category.get(CandidateProfileOption.Category.DIVISION, []),
        "consultants": by_category.get(CandidateProfileOption.Category.CONSULTANT, []),
        "employment_equity": by_category.get(
            CandidateProfileOption.Category.EMPLOYMENT_EQUITY, []
        ),
        "education_levels": by_category.get(
            CandidateProfileOption.Category.EDUCATION_LEVEL, []
        ),
        "qualifications": by_category.get(
            CandidateProfileOption.Category.QUALIFICATION, []
        ),
        "qualification_types": by_category.get(
            CandidateProfileOption.Category.QUALIFICATION_TYPE, []
        ),
        "sources": by_category.get(CandidateProfileOption.Category.SOURCE, []),
        "marital_statuses": by_category.get(
            CandidateProfileOption.Category.MARITAL_STATUS, []
        ),
        "drivers_licenses": by_category.get(
            CandidateProfileOption.Category.DRIVERS_LICENSE, []
        ),
        "fingerprint_statuses": by_category.get(
            CandidateProfileOption.Category.FINGERPRINT_STATUS, []
        ),
        "criminal_checks": by_category.get(
            CandidateProfileOption.Category.CRIMINAL_CHECK, []
        ),
        "sexes": [
            {"id": value, "label": label}
            for value, label in Candidate.Sex.choices
        ],
    }


class CandidateViewSet(viewsets.ModelViewSet):
    serializer_class = CandidateDirectorySerializer
    permission_classes = [CanManageBookings]
    http_method_names = ["get", "post", "patch", "head", "options"]

    @transaction.atomic
    def partial_update(self, request, *args, **kwargs):
        return super().partial_update(request, *args, **kwargs)

    def perform_create(self, serializer):
        candidate = serializer.save()
        department_ids = user_department_ids(self.request.user)
        if department_ids is not None:
            candidate.departments.set(department_ids)

    def perform_update(self, serializer):
        candidate = serializer.instance
        profile_fields = [
            "first_name",
            "last_name",
            "preferred_name",
            "date_of_birth",
            "identity_number",
            "is_sa_id",
            "passport_number",
            "visa_type",
            "visa_start",
            "visa_end",
            "visa_selected",
            "country_of_origin",
            "nationality",
            "home_language",
            "is_locum",
            "is_permanent",
            "email",
            "phone",
            "home_phone",
            "other_contact",
            "physical_address",
            "home_area",
            "home_region",
            "postal_code",
            "note",
            "division",
            "assigned_consultant",
            "sex",
            "sex_source",
            "citizenship_status",
            "employment_equity",
            "is_disabled",
            "fingerprint_status",
            "criminal_check",
            "drivers_license",
            "owns_car",
            "qualification",
            "qualification_types",
            "education_level",
            "source",
            "marital_status",
            "other_languages",
            "is_active",
        ]
        before = {field: getattr(candidate, field) for field in profile_fields}
        before["profession_ids"] = sorted(
            candidate.professions.values_list("id", flat=True)
        )
        candidate = serializer.save(profile_locally_managed=True)
        after = {field: getattr(candidate, field) for field in profile_fields}
        after["profession_ids"] = sorted(
            candidate.professions.values_list("id", flat=True)
        )
        changed_fields = sorted(
            field for field in before if before[field] != after[field]
        )
        if changed_fields:
            audited_values = {"home_area", "home_region", "is_active", "profession_ids"}
            CandidateChangeAudit.objects.create(
                candidate=candidate,
                changed_by=self.request.user,
                changed_fields=changed_fields,
                before={field: before[field] for field in audited_values if field in changed_fields},
                after={field: after[field] for field in audited_values if field in changed_fields},
            )

    def get_queryset(self):
        queryset = Candidate.objects.filter(is_active=True).prefetch_related(
            "professions"
        )
        queryset = scope_queryset_to_user_departments(
            queryset,
            self.request.user,
        )
        profession = self.request.query_params.get("profession")
        if profession is not None:
            try:
                profession_id = int(profession)
            except (TypeError, ValueError) as exc:
                raise ValidationError({"profession": "Select a valid role."}) from exc
            queryset = queryset.filter(professions__id=profession_id)
        search = self.request.query_params.get("search", "").strip()
        for term in search.split():
            queryset = queryset.filter(
                Q(first_name__icontains=term)
                | Q(last_name__icontains=term)
            )
        return queryset.order_by("first_name", "last_name")

    def list(self, request, *args, **kwargs):
        raw_site = request.query_params.get("site")
        if raw_site is None:
            return super().list(request, *args, **kwargs)
        query_serializer = RankedFacilityCandidateQuerySerializer(
            data=request.query_params
        )
        query_serializer.is_valid(raise_exception=True)
        query = query_serializer.validated_data
        site = query["site"]
        profession_id = query["profession"].id

        queryset = self.get_queryset().filter(
            compliance_status=Candidate.ComplianceStatus.CLEARED,
            professions__id=profession_id,
        ).distinct()
        if query.get("starts_at"):
            rest_interval = _booking_rest_interval()
            confirmed_overlap = Booking.objects.filter(
                candidate_id=OuterRef("pk"),
                status=Booking.Status.CONFIRMED,
                shift__starts_at__lt=query["ends_at"] + rest_interval,
                shift__ends_at__gt=query["starts_at"] - rest_interval,
            )
            queryset = queryset.filter(~Exists(confirmed_overlap))
        candidates = list(queryset)
        _rank_candidates_for_facility(candidates, site, profession_id)
        return Response(RankedFacilityCandidateSerializer(
            candidates,
            many=True,
            context=self.get_serializer_context(),
        ).data)

    @action(detail=False, methods=["get"], url_path="creation-options")
    def creation_options(self, request):
        if not _can_edit_candidates(request.user):
            raise PermissionDenied("You do not have permission to manage Candidates.")
        professions = Profession.objects.order_by("name")
        return Response({
            "professions": [
                {
                    "id": profession.id,
                    "name": profession.name,
                    "legacy_mysql_id": profession.legacy_mysql_id,
                }
                for profession in professions
            ],
            "locations": candidate_location_options(
                user_department_ids(request.user)
            ),
            "profile": _candidate_profile_options(),
        })

    @action(detail=True, methods=["get", "patch"], url_path="profile")
    def profile(self, request, pk=None):
        if not _can_edit_candidates(request.user):
            raise PermissionDenied("Your access rules do not allow Candidate editing.")
        candidate = self.get_object()
        if request.method == "GET":
            return Response(CandidateProfileSerializer(
                candidate,
                context=self.get_serializer_context(),
            ).data)
        serializer = CandidateProfileSerializer(
            candidate,
            data=request.data,
            partial=True,
            context=self.get_serializer_context(),
        )
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            self.perform_update(serializer)
        return Response(serializer.data)

    @action(detail=False, methods=["post"], url_path="decode-sa-id")
    def decode_sa_id(self, request):
        if not _can_edit_candidates(request.user):
            raise PermissionDenied("Your access rules do not allow Candidate editing.")
        if not isinstance(request.data, Mapping):
            raise ValidationError({"identity_number": "Enter a valid ID number."})
        try:
            decoded = decode_south_african_id(request.data.get("identity_number", ""))
        except SouthAfricanIdError as exc:
            raise ValidationError({"identity_number": str(exc)}) from exc
        return Response({
            "date_of_birth": decoded["date_of_birth"].isoformat(),
            "sex": decoded["sex"],
            "sex_source": Candidate.SexSource.SA_ID,
            "citizenship_status": decoded["citizenship_status"],
        })

    @action(detail=True, methods=["get"], url_path="compatible-shifts")
    def compatible_shifts(self, request, pk=None):
        candidate = self.get_object()
        if candidate.compliance_status != Candidate.ComplianceStatus.CLEARED:
            return Response([])

        rest_interval = _booking_rest_interval()
        confirmed_overlap = Booking.objects.filter(
            candidate=candidate,
            status=Booking.Status.CONFIRMED,
            shift__starts_at__lt=OuterRef("ends_at") + rest_interval,
            shift__ends_at__gt=OuterRef("starts_at") - rest_interval,
        )
        shifts = Shift.objects.filter(
            status=Shift.Status.OPEN,
            profession__in=candidate.professions.all(),
        ).filter(~Exists(confirmed_overlap)).select_related(
            "site__client", "profession"
        ).order_by("starts_at", "id")
        return Response(ShiftSerializer(
            shifts,
            many=True,
            context=self.get_serializer_context(),
        ).data)


class ShiftViewSet(viewsets.ModelViewSet):
    queryset = Shift.objects.select_related("site__client", "profession").prefetch_related(
        Prefetch(
            "bookings",
            queryset=Booking.objects.filter(
                status=Booking.Status.CONFIRMED
            ).select_related("candidate"),
            to_attr="confirmed_bookings",
        )
    )
    serializer_class = ShiftSerializer
    permission_classes = [CanManageBookings]
    http_method_names = ["get", "post", "head", "options"]

    def perform_create(self, serializer):
        _require_department_access(
            self.request.user,
            serializer.validated_data["site"].client.departments,
        )
        serializer.save()

    def get_queryset(self):
        queryset = scope_queryset_to_user_departments(
            super().get_queryset(),
            self.request.user,
            lookup="site__client__departments",
        ).order_by("starts_at")
        site_id = self.request.query_params.get("site")
        if site_id:
            try:
                queryset = queryset.filter(site_id=int(site_id))
            except (TypeError, ValueError) as exc:
                raise ValidationError({"site": "Enter a valid Facility ID."}) from exc

        for parameter, lookup in (
            ("starts_before", "starts_at__lt"),
            ("ends_after", "ends_at__gt"),
        ):
            raw_value = self.request.query_params.get(parameter)
            if not raw_value:
                continue
            value = parse_datetime(raw_value)
            if value is None:
                raise ValidationError({parameter: "Enter a valid ISO 8601 date and time."})
            queryset = queryset.filter(**{lookup: value})
        return queryset

    @action(detail=False, methods=["get"], url_path="creation-options")
    def creation_options(self, request):
        sites = Site.objects.filter(client__is_active=True).select_related(
            "client"
        )
        sites = scope_queryset_to_user_departments(
            sites,
            request.user,
            lookup="client__departments",
        ).order_by("client__name", "name")
        professions = Profession.objects.order_by("name")
        return Response({
            "sites": [
                {"id": site.id, "name": site.name, "client_name": site.client.name}
                for site in sites
            ],
            "professions": [
                {"id": profession.id, "name": profession.name}
                for profession in professions
            ],
        })

    @action(detail=True, methods=["get"])
    def candidates(self, request, pk=None):
        shift = self.get_object()
        rest_interval = _booking_rest_interval()
        confirmed_overlap = Booking.objects.filter(
            candidate_id=OuterRef("pk"),
            status=Booking.Status.CONFIRMED,
            shift__starts_at__lt=shift.ends_at + rest_interval,
            shift__ends_at__gt=shift.starts_at - rest_interval,
        )
        candidate_queryset = Candidate.objects.filter(
            is_active=True,
            professions=shift.profession,
            compliance_status=Candidate.ComplianceStatus.CLEARED,
        ).filter(~Exists(confirmed_overlap))
        candidates = list(scope_queryset_to_user_departments(
            candidate_queryset,
            request.user,
        ))

        candidate_ids = [candidate.id for candidate in candidates]
        legacy_experience = {
            row.candidate_id: row
            for row in FacilityExperience.objects.filter(
                candidate_id__in=candidate_ids,
                client=shift.site.client,
                profession=shift.profession,
            )
        }
        history_cutoff = min(shift.starts_at, timezone.now())
        current_experience = {
            row["candidate_id"]: row
            for row in Booking.objects.filter(
                candidate_id__in=candidate_ids,
                status=Booking.Status.CONFIRMED,
                shift__site__client=shift.site.client,
                shift__profession=shift.profession,
                shift__status=Shift.Status.COMPLETED,
                shift__ends_at__lte=history_cutoff,
            ).values("candidate_id").annotate(
                count=Count("id"),
                last_worked_at=Max("shift__ends_at"),
            )
        }

        client_region = shift.site.client.region.strip().casefold()
        client_city = shift.site.client.city.strip().casefold()
        for candidate in candidates:
            imported = legacy_experience.get(candidate.id)
            current = current_experience.get(candidate.id)
            candidate.facility_shift_count = (
                (imported.completed_shift_count if imported else 0)
                + (current["count"] if current else 0)
            )
            candidate.last_worked_on = imported.last_worked_on if imported else None
            if current and (
                candidate.last_worked_on is None
                or timezone.localdate(current["last_worked_at"]) > candidate.last_worked_on
            ):
                candidate.last_worked_on = timezone.localdate(current["last_worked_at"])

            home_area = candidate.home_area.strip().casefold()
            home_region = candidate.home_region.strip().casefold()
            if home_area and client_city and home_area == client_city:
                candidate.proximity_rank = 0
                candidate.proximity_label = "Same area as facility"
            elif home_region and client_region and home_region == client_region:
                candidate.proximity_rank = 1
                candidate.proximity_label = "Same region as facility"
            else:
                candidate.proximity_rank = 2
                candidate.proximity_label = ""

        candidates.sort(key=lambda candidate: (
            -candidate.facility_shift_count,
            candidate.proximity_rank,
            candidate.full_name.casefold(),
            candidate.id,
        ))
        serializer = CandidateSummarySerializer(
            candidates,
            many=True,
            context={"shift": shift},
        )
        return Response(serializer.data)


class VacancyViewSet(viewsets.ModelViewSet):
    queryset = Vacancy.objects.select_related(
        "site__client", "profession", "created_by"
    ).prefetch_related(
        Prefetch(
            "shifts",
            queryset=Shift.objects.select_related(
                "site__client", "profession"
            ).prefetch_related(
                Prefetch(
                    "bookings",
                    queryset=Booking.objects.filter(
                        status=Booking.Status.CONFIRMED
                    ).select_related("candidate"),
                    to_attr="confirmed_bookings",
                )
            ),
        )
    )
    serializer_class = VacancySerializer
    permission_classes = [CanManageBookings]
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        return scope_queryset_to_user_departments(
            super().get_queryset(),
            self.request.user,
            lookup="site__client__departments",
        )

    def perform_create(self, serializer):
        _require_department_access(
            self.request.user,
            serializer.validated_data["site"].client.departments,
        )
        serializer.save(created_by=self.request.user)

    @action(detail=False, methods=["post"], url_path="book-now")
    def book_now(self, request):
        input_serializer = FacilityBookNowInputSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        book_now = input_serializer.validated_data
        _require_department_access(
            request.user,
            book_now["site"].client.departments,
            book_now["candidate"].departments,
        )
        with transaction.atomic():
            rates = _configured_rates(book_now["site"], book_now["profession"])
            vacancy_serializer = self.get_serializer(
                data={
                    "reference": book_now.get("reference", ""),
                    "site": book_now["site"].id,
                    "profession": book_now["profession"].id,
                    "notes": book_now.get("notes", ""),
                    "shift_items": [{
                        "starts_at": book_now["starts_at"],
                        "ends_at": book_now["ends_at"],
                        "pay_rate": rates["pay_rate"],
                    }],
                },
                context={
                    **self.get_serializer_context(),
                    "configured_bill_rate": rates["bill_rate"],
                    "persist_rate_default": False,
                },
            )
            vacancy_serializer.is_valid(raise_exception=True)
            vacancy = vacancy_serializer.save(created_by=request.user)
            shifts = list(vacancy.shifts.all())
            booking_serializer = BookingSerializer(data={
                "shift": shifts[0].id,
                "candidate": book_now["candidate"].id,
                "status": Booking.Status.CONFIRMED,
            })
            booking_serializer.is_valid(raise_exception=True)
            booking = booking_serializer.save()
            vacancy = self.get_queryset().get(pk=vacancy.pk)
        return Response({
            "vacancy": self.get_serializer(vacancy).data,
            "booking": BookingSerializer(booking).data,
        }, status=201)

    @action(detail=False, methods=["post"], url_path="book-candidate-shifts")
    def book_candidate_shifts(self, request):
        input_serializer = CandidateBookShiftsInputSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        booking_request = input_serializer.validated_data
        _require_department_access(
            request.user,
            booking_request["site"].client.departments,
            booking_request["candidate"].departments,
        )
        with transaction.atomic():
            rates = _configured_rates(
                booking_request["site"], booking_request["profession"]
            )
            vacancy_serializer = self.get_serializer(
                data={
                    "reference": booking_request.get("reference", ""),
                    "site": booking_request["site"].id,
                    "profession": booking_request["profession"].id,
                    "notes": booking_request.get("notes", ""),
                    "shift_items": [
                        {
                            **shift_item,
                            "pay_rate": rates["pay_rate"],
                        }
                        for shift_item in booking_request["shift_items"]
                    ],
                },
                context={
                    **self.get_serializer_context(),
                    "configured_bill_rate": rates["bill_rate"],
                    "persist_rate_default": False,
                },
            )
            vacancy_serializer.is_valid(raise_exception=True)
            vacancy = vacancy_serializer.save(created_by=request.user)
            shifts = list(vacancy.shifts.order_by("starts_at", "id"))
            bookings_serializer = BookingSerializer(
                data=[
                    {
                        "shift": shift.id,
                        "candidate": booking_request["candidate"].id,
                        "status": Booking.Status.CONFIRMED,
                    }
                    for shift in shifts
                ],
                many=True,
            )
            bookings_serializer.is_valid(raise_exception=True)
            bookings = bookings_serializer.save()
            vacancy = self.get_queryset().get(pk=vacancy.pk)
        return Response({
            "vacancy": self.get_serializer(vacancy).data,
            "bookings": BookingSerializer(bookings, many=True).data,
        }, status=201)

    @action(detail=False, methods=["get"], url_path="creation-options")
    def creation_options(self, request):
        sites = Site.objects.filter(client__is_active=True).select_related(
            "client"
        )
        sites = scope_queryset_to_user_departments(
            sites,
            request.user,
            lookup="client__departments",
        ).order_by("client__name", "name")
        professions = Profession.objects.order_by("name")
        return Response({
            "sites": [
                {"id": site.id, "name": site.name, "client_name": site.client.name}
                for site in sites
            ],
            "professions": [
                {"id": profession.id, "name": profession.name}
                for profession in professions
            ],
        })

    @action(detail=False, methods=["get"], url_path="rate-default")
    def rate_default(self, request):
        try:
            site_id = int(request.query_params["site"])
            profession_id = int(request.query_params["profession"])
        except (KeyError, TypeError, ValueError):
            return Response(
                {"detail": "Select a valid facility and role."},
                status=400,
            )

        site = scope_queryset_to_user_departments(
            Site.objects.filter(pk=site_id, client__is_active=True),
            request.user,
            lookup="client__departments",
        ).first()
        if site is None:
            return Response({"detail": "Select a valid facility."}, status=404)

        rate = SiteProfessionRate.objects.filter(
            site_id=site_id,
            profession_id=profession_id,
        ).values("pay_rate", "bill_rate").first()
        if rate is None:
            rate = Shift.objects.filter(
                site_id=site_id,
                profession_id=profession_id,
            ).order_by("-starts_at").values("pay_rate", "bill_rate").first()
        payload = {}
        if user_can_view_candidate_pay_rates(request.user):
            payload["pay_rate"] = None if rate is None else f"{rate['pay_rate']:.2f}"
        if user_can_view_client_charge_rates(request.user):
            payload["bill_rate"] = None if rate is None else f"{rate['bill_rate']:.2f}"
        return Response(payload)

    @action(detail=False, methods=["get"], url_path="site-role-options")
    def site_role_options(self, request):
        try:
            site_id = int(request.query_params["site"])
        except (KeyError, TypeError, ValueError):
            return Response({"detail": "Select a valid facility."}, status=400)

        sites = scope_queryset_to_user_departments(
            Site.objects.filter(pk=site_id, client__is_active=True),
            request.user,
            lookup="client__departments",
        )
        client_id = sites.values_list(
            "client_id", flat=True
        ).first()
        if client_id is None:
            return Response({"detail": "Select a valid facility."}, status=404)

        site_rates = {
            rate["profession_id"]: rate
            for rate in SiteProfessionRate.objects.filter(site_id=site_id).values(
                "profession_id", "pay_rate", "bill_rate"
            )
        }
        linked_rates = ClientProfessionRate.objects.filter(
            client_id=client_id
        ).select_related("profession").order_by("profession__name")
        professions = []
        for linked_rate in linked_rates:
            rate = site_rates.get(linked_rate.profession_id)
            pay_rate = rate["pay_rate"] if rate else linked_rate.pay_rate
            bill_rate = rate["bill_rate"] if rate else linked_rate.bill_rate
            professions.append({
                "id": linked_rate.profession_id,
                "name": linked_rate.profession.name,
                **(
                    {"pay_rate": f"{pay_rate:.2f}"}
                    if user_can_view_candidate_pay_rates(request.user)
                    else {}
                ),
                **(
                    {"bill_rate": f"{bill_rate:.2f}"}
                    if user_can_view_client_charge_rates(request.user)
                    else {}
                ),
            })
        return Response({"professions": professions})


class BookingViewSet(viewsets.ModelViewSet):
    queryset = Booking.objects.select_related("shift", "candidate")
    serializer_class = BookingSerializer
    permission_classes = [CanManageBookings]

    def get_queryset(self):
        return scope_queryset_to_user_departments(
            super().get_queryset(),
            self.request.user,
            lookup="shift__site__client__departments",
        )

    def perform_create(self, serializer):
        _require_department_access(
            self.request.user,
            serializer.validated_data["shift"].site.client.departments,
            serializer.validated_data["candidate"].departments,
        )
        serializer.save()

    @action(detail=True, methods=["get", "post"], url_path="confirmation-sms")
    def confirmation_sms(self, request, pk=None):
        if not request.user.has_perm("bookings.send_booking_sms"):
            raise PermissionDenied(
                "You do not have permission to send booking SMS messages."
            )
        booking = self.get_object()
        existing = SmsMessage.objects.filter(booking=booking).first()
        if request.method == "GET":
            if existing is not None:
                return Response({
                    "id": existing.id,
                    "status": existing.status,
                    "body": existing.body,
                    "destination": mask_phone_number(existing.destination),
                })
            try:
                destination = normalize_phone_number(booking.candidate.phone)
            except DjangoValidationError as exc:
                raise ValidationError({"destination": exc.messages}) from exc
            return Response({
                "status": "not_queued",
                "body": render_booking_confirmation_sms(booking),
                "destination": mask_phone_number(destination),
            })

        serializer = BookingSmsInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            message = queue_booking_confirmation_sms(
                booking_id=booking.id,
                actor=request.user,
                body=serializer.validated_data["body"],
            )
        except DjangoValidationError as exc:
            raise ValidationError({"non_field_errors": exc.messages}) from exc
        return Response({
            "id": message.id,
            "status": message.status,
            "body": message.body,
            "destination": mask_phone_number(message.destination),
        }, status=201)

    @action(detail=False, methods=["post"])
    def bulk(self, request):
        if not isinstance(request.data, Mapping):
            raise ValidationError({"non_field_errors": "Expected a JSON object."})
        assignments = request.data.get("assignments")
        if not isinstance(assignments, list) or not assignments:
            raise ValidationError({"assignments": "Select at least one booking."})
        if len(assignments) > 100:
            raise ValidationError({"assignments": "Book at most 100 shifts at a time."})

        serializer = self.get_serializer(data=assignments, many=True)
        with transaction.atomic():
            serializer.is_valid(raise_exception=True)
            for assignment in serializer.validated_data:
                _require_department_access(
                    request.user,
                    assignment["shift"].site.client.departments,
                    assignment["candidate"].departments,
                )
            bookings = serializer.save()
        return Response(self.get_serializer(bookings, many=True).data, status=201)
