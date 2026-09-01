from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Prefetch
from rest_framework import serializers

from bookings.booking_times import booking_time_step_minutes_for_user
from bookings.candidate_locations import canonical_candidate_location
from bookings.models import (
    Booking,
    Candidate,
    CandidateProfileOption,
    ClientProfessionRate,
    LegacyUserProfile,
    Profession,
    Shift,
    Site,
    SiteProfessionRate,
    Vacancy,
)
from bookings.permissions import (
    user_can_override_approved_rates,
    user_can_view_candidate_pay_rates,
    user_can_view_client_charge_rates,
)
from bookings.sa_id import SouthAfricanIdError, decode_south_african_id


def _validation_detail(exc):
    return getattr(exc, "message_dict", None) or exc.messages


def _configured_rates(site, profession):
    rate = SiteProfessionRate.objects.filter(
        site=site,
        profession=profession,
    ).values("pay_rate", "bill_rate").first()
    if rate is None:
        rate = ClientProfessionRate.objects.filter(
            client_id=site.client_id,
            profession=profession,
        ).values("pay_rate", "bill_rate").first()
    if rate is None:
        raise serializers.ValidationError({
            "profession": "The selected role has no configured pay and client charge rate for this facility."
        })
    return rate


def _configured_bill_rate(site, profession):
    return _configured_rates(site, profession)["bill_rate"]


def _context_user(context):
    request = context.get("request")
    return getattr(request, "user", None)


def _validate_booking_times(attrs, context):
    request = context.get("request")
    step_minutes = booking_time_step_minutes_for_user(
        getattr(request, "user", None)
    )
    errors = {}
    for field in ("starts_at", "ends_at"):
        value = attrs.get(field)
        if value and (
            value.minute % step_minutes or value.second or value.microsecond
        ):
            errors[field] = f"Select a time on a {step_minutes}-minute interval."
    if errors:
        raise serializers.ValidationError(errors)
    return attrs


class CandidateSummarySerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
    role_name = serializers.SerializerMethodField()
    worked_at_facility = serializers.SerializerMethodField()
    facility_shift_count = serializers.IntegerField(read_only=True)
    last_worked_on = serializers.DateField(read_only=True)
    proximity_label = serializers.CharField(read_only=True)
    eligibility_reasons = serializers.SerializerMethodField()

    class Meta:
        model = Candidate
        fields = [
            "id",
            "full_name",
            "compliance_status",
            "role_name",
            "home_area",
            "home_region",
            "worked_at_facility",
            "facility_shift_count",
            "last_worked_on",
            "proximity_label",
            "eligibility_reasons",
        ]

    def get_role_name(self, obj):
        return self.context["shift"].profession.name

    def get_worked_at_facility(self, obj):
        return obj.facility_shift_count > 0

    def get_eligibility_reasons(self, obj):
        role_name = self.context["shift"].profession.name
        reasons = ["Compliance cleared", f"{role_name} role matched"]
        if obj.facility_shift_count:
            suffix = "shift" if obj.facility_shift_count == 1 else "shifts"
            reasons.append(
                f"{obj.facility_shift_count} completed {suffix} at this facility"
            )
        if obj.proximity_label:
            reasons.append(obj.proximity_label)
        return reasons


class CandidateDirectorySerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
    profession_ids = serializers.PrimaryKeyRelatedField(
        source="professions",
        queryset=Profession.objects.all(),
        many=True,
    )
    profession_names = serializers.SlugRelatedField(
        source="professions",
        many=True,
        read_only=True,
        slug_field="name",
    )
    class Meta:
        model = Candidate
        fields = [
            "id",
            "first_name",
            "last_name",
            "full_name",
            "email",
            "phone",
            "compliance_status",
            "home_area",
            "home_region",
            "postal_code",
            "is_active",
            "profession_names",
            "profession_ids",
        ]
        read_only_fields = ["id", "compliance_status"]

    def validate(self, attrs):
        protected_fields = {
            "compliance_status": (
                "Compliance is managed through the protected compliance workflow."
            ),
            "legacy_mysql_id": "The legacy integration identifier is immutable.",
            "profile_locally_managed": "Profile ownership is managed by the server.",
        }
        rejected = {
            field: message
            for field, message in protected_fields.items()
            if field in self.initial_data
        }
        if rejected:
            raise serializers.ValidationError(rejected)
        home_region = attrs.get(
            "home_region",
            self.instance.home_region if self.instance else "",
        ).strip()
        home_area = attrs.get(
            "home_area",
            self.instance.home_area if self.instance else "",
        ).strip()
        if home_area and not home_region:
            raise serializers.ValidationError({
                "home_region": "Select a Region before selecting an Area."
            })
        if home_region and home_area:
            canonical_location = canonical_candidate_location(home_region, home_area)
            if canonical_location is None:
                raise serializers.ValidationError({
                    "home_area": "Select an Area that belongs to the selected Region."
                })
            attrs["home_region"], attrs["home_area"] = canonical_location
        is_active = attrs.get(
            "is_active",
            self.instance.is_active if self.instance else True,
        )
        professions = attrs.get("professions")
        if is_active and professions is not None and not professions:
            raise serializers.ValidationError({
                "profession_ids": "An active Candidate must have at least one role."
            })
        if (
            is_active
            and professions is None
            and self.instance
            and not self.instance.professions.exists()
        ):
            raise serializers.ValidationError({
                "profession_ids": "An active Candidate must have at least one role."
            })
        return attrs


class CandidateProfileSerializer(CandidateDirectorySerializer):
    can_set_compliance = serializers.SerializerMethodField()
    qualification_types = serializers.ListField(
        child=serializers.CharField(max_length=160),
        required=False,
    )
    other_languages = serializers.ListField(
        child=serializers.CharField(max_length=160),
        required=False,
    )

    class Meta(CandidateDirectorySerializer.Meta):
        fields = CandidateDirectorySerializer.Meta.fields + [
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
            "home_phone",
            "other_contact",
            "physical_address",
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
            "can_set_compliance",
        ]
        read_only_fields = CandidateDirectorySerializer.Meta.read_only_fields + [
            "sex_source",
            "citizenship_status",
        ]

    def get_can_set_compliance(self, _candidate):
        return self._can_set_compliance(self.context.get("request"))

    @staticmethod
    def _can_set_compliance(request):
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        try:
            return bool(user.legacy_profile.set_compliance)
        except LegacyUserProfile.DoesNotExist:
            return user.has_perm("bookings.change_candidate")

    def _validate_option(self, attrs, field, category, errors):
        if field not in attrs:
            return
        value = attrs[field].strip()
        attrs[field] = value
        if not value:
            return
        current = getattr(self.instance, field, "") if self.instance else ""
        if value == current:
            return
        if not CandidateProfileOption.objects.filter(
            category=category,
            label=value,
            is_active=True,
        ).exists():
            errors[field] = "Select a configured option."

    def _validate_option_list(self, attrs, field, category, errors):
        if field not in attrs:
            return
        values = list(dict.fromkeys(value.strip() for value in attrs[field] if value.strip()))
        attrs[field] = values
        configured = set(CandidateProfileOption.objects.filter(
            category=category,
            label__in=values,
            is_active=True,
        ).values_list("label", flat=True))
        current = set(getattr(self.instance, field, []) if self.instance else [])
        if set(values) - configured - current:
            errors[field] = "Select only configured options."

    def validate(self, attrs):
        attrs = super().validate(attrs)
        errors = {}
        scalar_options = {
            "visa_type": CandidateProfileOption.Category.VISA_TYPE,
            "country_of_origin": CandidateProfileOption.Category.COUNTRY,
            "nationality": CandidateProfileOption.Category.COUNTRY,
            "home_language": CandidateProfileOption.Category.LANGUAGE,
            "division": CandidateProfileOption.Category.DIVISION,
            "assigned_consultant": CandidateProfileOption.Category.CONSULTANT,
            "employment_equity": CandidateProfileOption.Category.EMPLOYMENT_EQUITY,
            "fingerprint_status": CandidateProfileOption.Category.FINGERPRINT_STATUS,
            "criminal_check": CandidateProfileOption.Category.CRIMINAL_CHECK,
            "drivers_license": CandidateProfileOption.Category.DRIVERS_LICENSE,
            "qualification": CandidateProfileOption.Category.QUALIFICATION,
            "education_level": CandidateProfileOption.Category.EDUCATION_LEVEL,
            "source": CandidateProfileOption.Category.SOURCE,
            "marital_status": CandidateProfileOption.Category.MARITAL_STATUS,
        }
        for field, category in scalar_options.items():
            self._validate_option(attrs, field, category, errors)
        self._validate_option_list(
            attrs,
            "qualification_types",
            CandidateProfileOption.Category.QUALIFICATION_TYPE,
            errors,
        )
        self._validate_option_list(
            attrs,
            "other_languages",
            CandidateProfileOption.Category.LANGUAGE,
            errors,
        )

        if "qualification_types" in attrs:
            effective_professions = attrs.get("professions")
            if effective_professions is None:
                effective_professions = (
                    self.instance.professions.all() if self.instance else []
                )
            allowed_legacy_role_ids = {
                profession.legacy_mysql_id
                for profession in effective_professions
                if profession.legacy_mysql_id is not None
            }
            current_types = set(
                self.instance.qualification_types if self.instance else []
            )
            selected_types = set(attrs["qualification_types"])
            current_profession_ids = set(
                self.instance.professions.values_list("id", flat=True)
                if self.instance else []
            )
            effective_profession_ids = {
                profession.id for profession in effective_professions
            }
            role_selection_changed = (
                self.instance is None
                or effective_profession_ids != current_profession_ids
            )
            labels_to_check = (
                selected_types
                if role_selection_changed
                else selected_types - current_types
            )
            incompatible = CandidateProfileOption.objects.filter(
                category=CandidateProfileOption.Category.QUALIFICATION_TYPE,
                label__in=labels_to_check,
                is_active=True,
            ).exclude(legacy_mysql_id__in=allowed_legacy_role_ids)
            if incompatible.exists():
                errors["qualification_types"] = (
                    "Qualification types must match the selected Candidate roles."
                )

        request = self.context.get("request")
        if not self._can_set_compliance(request):
            for field in ("fingerprint_status", "criminal_check"):
                if field in self.initial_data:
                    current = getattr(self.instance, field, "") if self.instance else ""
                    if self.initial_data[field] != current:
                        errors[field] = "This field is managed through the compliance workflow."

        effective_is_sa_id = attrs.get(
            "is_sa_id",
            self.instance.is_sa_id if self.instance else False,
        )
        identity_fields = {"identity_number", "is_sa_id", "date_of_birth", "sex"}
        identity_changed = self.instance is None or any(
            field in attrs and attrs[field] != getattr(self.instance, field)
            for field in identity_fields
        )
        if effective_is_sa_id and identity_changed:
            identity_number = attrs.get(
                "identity_number",
                self.instance.identity_number if self.instance else "",
            )
            try:
                decoded = decode_south_african_id(identity_number)
            except SouthAfricanIdError as exc:
                errors["identity_number"] = str(exc)
            else:
                attrs["date_of_birth"] = decoded["date_of_birth"]
                attrs["sex"] = decoded["sex"]
                attrs["sex_source"] = Candidate.SexSource.SA_ID
                attrs["citizenship_status"] = decoded["citizenship_status"]
        elif not effective_is_sa_id:
            sa_id_removed = bool(
                self.instance
                and self.instance.is_sa_id
                and attrs.get("is_sa_id") is False
            )
            sex_changed = (
                "sex" in attrs
                and (self.instance is None or attrs["sex"] != self.instance.sex)
            )
            if sa_id_removed or sex_changed:
                attrs["sex_source"] = Candidate.SexSource.MANUAL
            if sa_id_removed:
                attrs["citizenship_status"] = ""

        visa_start = attrs.get(
            "visa_start",
            self.instance.visa_start if self.instance else None,
        )
        visa_end = attrs.get(
            "visa_end",
            self.instance.visa_end if self.instance else None,
        )
        if visa_start and visa_end and visa_end < visa_start:
            errors["visa_end"] = "Visa expiration must be on or after visa start."
        if errors:
            raise serializers.ValidationError(errors)
        return attrs


class RankedFacilityCandidateSerializer(CandidateDirectorySerializer):
    worked_at_facility = serializers.SerializerMethodField()
    facility_shift_count = serializers.IntegerField(read_only=True)
    last_worked_on = serializers.DateField(read_only=True, allow_null=True)
    proximity_label = serializers.CharField(read_only=True)

    class Meta(CandidateDirectorySerializer.Meta):
        fields = CandidateDirectorySerializer.Meta.fields + [
            "worked_at_facility",
            "facility_shift_count",
            "last_worked_on",
            "proximity_label",
        ]

    def get_worked_at_facility(self, obj):
        return getattr(obj, "facility_shift_count", 0) > 0


class RankedFacilityCandidateQuerySerializer(serializers.Serializer):
    site = serializers.PrimaryKeyRelatedField(
        queryset=Site.objects.filter(client__is_active=True).select_related("client")
    )
    profession = serializers.PrimaryKeyRelatedField(queryset=Profession.objects.all())
    search = serializers.CharField(required=False, allow_blank=True)
    starts_at = serializers.DateTimeField(required=False)
    ends_at = serializers.DateTimeField(required=False)

    def validate(self, attrs):
        starts_at = attrs.get("starts_at")
        ends_at = attrs.get("ends_at")
        if bool(starts_at) != bool(ends_at):
            raise serializers.ValidationError(
                "Provide both start and end to filter scheduling conflicts."
            )
        if starts_at and ends_at <= starts_at:
            raise serializers.ValidationError({
                "ends_at": "Shift end must be after its start."
            })
        return attrs


class ConfirmedBookingSummarySerializer(serializers.ModelSerializer):
    candidate_name = serializers.CharField(source="candidate.full_name", read_only=True)

    class Meta:
        model = Booking
        fields = ["id", "candidate_id", "candidate_name", "status"]


class ShiftSerializer(serializers.ModelSerializer):
    site = serializers.PrimaryKeyRelatedField(
        queryset=Site.objects.filter(client__is_active=True),
        write_only=True,
    )
    site_id = serializers.IntegerField(read_only=True)
    profession_id = serializers.IntegerField(read_only=True)
    profession = serializers.PrimaryKeyRelatedField(
        queryset=Profession.objects.all(),
        write_only=True,
    )
    client_name = serializers.CharField(source="site.client.name", read_only=True)
    site_name = serializers.CharField(source="site.name", read_only=True)
    profession_name = serializers.CharField(source="profession.name", read_only=True)
    confirmed_booking = serializers.SerializerMethodField()

    class Meta:
        model = Shift
        fields = [
            "id",
            "vacancy",
            "site",
            "site_id",
            "profession",
            "profession_id",
            "client_name",
            "site_name",
            "profession_name",
            "starts_at",
            "ends_at",
            "pay_rate",
            "bill_rate",
            "status",
            "notes",
            "confirmed_booking",
        ]
        read_only_fields = ["id", "vacancy", "bill_rate", "status"]

    def get_confirmed_booking(self, obj):
        confirmed = getattr(obj, "confirmed_bookings", None)
        if confirmed is None:
            confirmed = obj.bookings.filter(
                status=Booking.Status.CONFIRMED
            ).select_related("candidate")[:1]
        booking = next(iter(confirmed), None)
        return (
            ConfirmedBookingSummarySerializer(booking).data
            if booking is not None
            else None
        )

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        user = _context_user(self.context)
        if not user_can_view_candidate_pay_rates(user):
            representation.pop("pay_rate", None)
        if not user_can_view_client_charge_rates(user):
            representation.pop("bill_rate", None)
        return representation

    def validate(self, attrs):
        attrs = _validate_booking_times(super().validate(attrs), self.context)
        site = attrs.get("site", self.instance.site if self.instance else None)
        profession = attrs.get(
            "profession",
            self.instance.profession if self.instance else None,
        )
        if site is None or profession is None:
            return attrs
        approved = _configured_rates(site, profession)
        submitted_pay_rate = attrs.get("pay_rate")
        can_override = user_can_override_approved_rates(_context_user(self.context))
        if (
            submitted_pay_rate is not None
            and submitted_pay_rate != approved["pay_rate"]
            and not can_override
        ):
            raise serializers.ValidationError({
                "pay_rate": "You do not have permission to override the approved pay rate."
            })
        attrs["pay_rate"] = (
            submitted_pay_rate
            if can_override and submitted_pay_rate is not None
            else approved["pay_rate"]
        )
        return attrs

    def create(self, validated_data):
        validated_data["bill_rate"] = _configured_bill_rate(
            validated_data["site"],
            validated_data["profession"],
        )
        try:
            return super().create(validated_data)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(_validation_detail(exc)) from exc


class VacancyShiftInputSerializer(serializers.Serializer):
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    pay_rate = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=0,
        required=False,
    )

    def validate(self, attrs):
        _validate_booking_times(attrs, self.context)
        if attrs["ends_at"] <= attrs["starts_at"]:
            raise serializers.ValidationError(
                {"ends_at": "Shift end must be after its start."}
            )
        return attrs


class FacilityBookNowInputSerializer(serializers.Serializer):
    reference = serializers.CharField(max_length=200, allow_blank=True, required=False)
    site = serializers.PrimaryKeyRelatedField(
        queryset=Site.objects.filter(client__is_active=True).select_related("client")
    )
    profession = serializers.PrimaryKeyRelatedField(queryset=Profession.objects.all())
    candidate = serializers.PrimaryKeyRelatedField(queryset=Candidate.objects.all())
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    notes = serializers.CharField(allow_blank=True, required=False)

    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise serializers.ValidationError({
                "non_field_errors": ["Expected a JSON object."]
            })
        unknown_fields = sorted(set(data) - set(self.fields))
        if unknown_fields:
            raise serializers.ValidationError({
                field: ["This field is not accepted by Book now."]
                for field in unknown_fields
            })
        return super().to_internal_value(data)

    def validate(self, attrs):
        _validate_booking_times(attrs, self.context)
        if attrs["ends_at"] <= attrs["starts_at"]:
            raise serializers.ValidationError({
                "ends_at": "Shift end must be after its start."
            })
        return attrs


class CandidateNewShiftInputSerializer(serializers.Serializer):
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()

    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise serializers.ValidationError("Expected a JSON object.")
        unknown_fields = sorted(set(data) - set(self.fields))
        if unknown_fields:
            raise serializers.ValidationError({
                field: ["This field is not accepted when creating Candidate shifts."]
                for field in unknown_fields
            })
        return super().to_internal_value(data)

    def validate(self, attrs):
        _validate_booking_times(attrs, self.context)
        if attrs["ends_at"] <= attrs["starts_at"]:
            raise serializers.ValidationError({
                "ends_at": "Shift end must be after its start."
            })
        return attrs


class CandidateBookShiftsInputSerializer(serializers.Serializer):
    reference = serializers.CharField(max_length=200, allow_blank=True, required=False)
    site = serializers.PrimaryKeyRelatedField(
        queryset=Site.objects.filter(client__is_active=True).select_related("client")
    )
    profession = serializers.PrimaryKeyRelatedField(queryset=Profession.objects.all())
    candidate = serializers.PrimaryKeyRelatedField(queryset=Candidate.objects.all())
    shift_items = CandidateNewShiftInputSerializer(many=True)
    notes = serializers.CharField(allow_blank=True, required=False)

    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise serializers.ValidationError({
                "non_field_errors": ["Expected a JSON object."]
            })
        unknown_fields = sorted(set(data) - set(self.fields))
        if unknown_fields:
            raise serializers.ValidationError({
                field: ["This field is not accepted when creating Candidate shifts."]
                for field in unknown_fields
            })
        return super().to_internal_value(data)

    def validate_shift_items(self, value):
        if not value:
            raise serializers.ValidationError("Add at least one shift.")
        if len(value) > 100:
            raise serializers.ValidationError("Create at most 100 shifts at a time.")
        return value


class VacancySerializer(serializers.ModelSerializer):
    site = serializers.PrimaryKeyRelatedField(
        queryset=Site.objects.filter(client__is_active=True)
    )
    shift_items = VacancyShiftInputSerializer(many=True, write_only=True)
    shifts = ShiftSerializer(many=True, read_only=True)
    status = serializers.SerializerMethodField()

    class Meta:
        model = Vacancy
        fields = [
            "id",
            "reference",
            "site",
            "profession",
            "notes",
            "created_at",
            "status",
            "shift_items",
            "shifts",
        ]
        read_only_fields = ["id", "created_at", "status", "shifts"]

    def validate_shift_items(self, value):
        if not value:
            raise serializers.ValidationError("Add at least one shift.")
        rates = {item["pay_rate"] for item in value if "pay_rate" in item}
        if len(rates) > 1:
            raise serializers.ValidationError(
                "All shifts in a vacancy must use the same pay rate."
            )
        return value

    def validate(self, attrs):
        attrs = super().validate(attrs)
        site = attrs.get("site", self.instance.site if self.instance else None)
        profession = attrs.get(
            "profession",
            self.instance.profession if self.instance else None,
        )
        if site is None or profession is None:
            return attrs
        approved = _configured_rates(site, profession)
        can_override = user_can_override_approved_rates(_context_user(self.context))
        if not can_override and any(
            item.get("pay_rate", approved["pay_rate"]) != approved["pay_rate"]
            for item in attrs.get("shift_items", [])
        ):
            raise serializers.ValidationError({
                "shift_items": "You do not have permission to override the approved pay rate."
            })
        return attrs

    def get_status(self, obj):
        statuses = {shift.status for shift in obj.shifts.all()}
        if Shift.Status.OPEN in statuses:
            return "open"
        if statuses.intersection({Shift.Status.BOOKED, Shift.Status.COMPLETED}):
            return "filled"
        return "cancelled"

    @transaction.atomic
    def create(self, validated_data):
        shift_items = validated_data.pop("shift_items")
        site = validated_data["site"]
        profession = validated_data["profession"]
        approved = _configured_rates(site, profession)
        bill_rate = self.context.get("configured_bill_rate", approved["bill_rate"])
        can_override = user_can_override_approved_rates(_context_user(self.context))
        for shift_item in shift_items:
            submitted_pay_rate = shift_item.get("pay_rate")
            shift_item["pay_rate"] = (
                submitted_pay_rate
                if can_override and submitted_pay_rate is not None
                else approved["pay_rate"]
            )
            shift_item["bill_rate"] = bill_rate
        vacancy = Vacancy.objects.create(**validated_data)
        Shift.objects.bulk_create([
            Shift(
                vacancy=vacancy,
                site=vacancy.site,
                profession=vacancy.profession,
                notes=vacancy.notes,
                **shift_item,
            )
            for shift_item in shift_items
        ])
        first_shift = shift_items[0]
        if self.context.get("persist_rate_default", True):
            SiteProfessionRate.objects.update_or_create(
                site=vacancy.site,
                profession=vacancy.profession,
                defaults={
                    "pay_rate": approved["pay_rate"],
                    "bill_rate": approved["bill_rate"],
                },
            )
        return Vacancy.objects.select_related(
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
        ).get(pk=vacancy.pk)


class BookingSerializer(serializers.ModelSerializer):
    class Meta:
        model = Booking
        fields = ["id", "shift", "candidate", "status", "created_at"]
        read_only_fields = ["id", "created_at"]

    def create(self, validated_data):
        try:
            return super().create(validated_data)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(_validation_detail(exc)) from exc

    def update(self, instance, validated_data):
        try:
            return super().update(instance, validated_data)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(_validation_detail(exc)) from exc


class BookingSmsInputSerializer(serializers.Serializer):
    body = serializers.CharField(max_length=459, trim_whitespace=True)

    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise serializers.ValidationError({
                "non_field_errors": ["Expected a JSON object."]
            })
        unknown_fields = sorted(set(data) - set(self.fields))
        if unknown_fields:
            raise serializers.ValidationError({
                field: ["This field is not accepted when queuing a booking SMS."]
                for field in unknown_fields
            })
        return super().to_internal_value(data)
