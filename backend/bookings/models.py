from datetime import timedelta
from decimal import Decimal
import hashlib
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction

from bookings.storage import private_storage


LEGACY_ACCESS_RULE_FIELDS = (
    "cap_ts",
    "link_ts",
    "approve_ts",
    "export_ts",
    "link_conf",
    "export_inv",
    "edit_clients",
    "edit_cand",
    "edit_cons",
    "update_client_rates",
    "update_cand_rates",
    "override_can_rates",
    "man_users",
    "view_cons_report",
    "view_client_report",
    "view_can_report",
    "view_com_report",
    "view_profit_report",
    "submit_cand_live",
    "delete_files",
    "set_compliance",
    "assign_cons",
)


class Region(models.Model):
    code = models.CharField(max_length=16, unique=True)
    name = models.CharField(max_length=120, unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.code} — {self.name}"


class Department(models.Model):
    legacy_mysql_id = models.PositiveIntegerField(unique=True)
    name = models.CharField(max_length=120)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["legacy_mysql_id"]

    def __str__(self):
        return self.name


class RegionalDesk(models.Model):
    region = models.ForeignKey(
        Region,
        on_delete=models.PROTECT,
        related_name="regional_desks",
    )
    department = models.ForeignKey(
        Department,
        on_delete=models.PROTECT,
        related_name="regional_desks",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["region__name", "department__legacy_mysql_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["region", "department"],
                name="unique_desk_per_region",
            )
        ]

    def __str__(self):
        return f"{self.region.code} · {self.department.name}"


class Client(models.Model):
    name = models.CharField(max_length=200)
    legacy_mysql_id = models.PositiveIntegerField(null=True, blank=True, unique=True)
    region = models.CharField(max_length=120, blank=True)
    city = models.CharField(max_length=120, blank=True)
    is_active = models.BooleanField(default=True)
    accounting_code = models.CharField(
        max_length=40,
        null=True,
        blank=True,
        unique=True,
        help_text="Pastel Customer/account code used for finance exports.",
    )
    payroll_job_code = models.CharField(max_length=40, blank=True)
    billing_address = models.TextField(blank=True)
    vat_number = models.CharField(max_length=40, blank=True)
    requires_timesheet_confirmation = models.BooleanField(default=False)
    departments = models.ManyToManyField(
        Department,
        blank=True,
        related_name="clients",
    )

    def __str__(self):
        return self.name


class RegionalClient(models.Model):
    regional_desk = models.ForeignKey(
        RegionalDesk,
        on_delete=models.PROTECT,
        related_name="regional_clients",
    )
    client = models.ForeignKey(
        Client,
        on_delete=models.PROTECT,
        related_name="regional_clients",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = [
            "regional_desk__region__name",
            "regional_desk__department__legacy_mysql_id",
            "client__name",
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["regional_desk", "client"],
                name="unique_client_per_regional_desk",
            )
        ]

    def __str__(self):
        return f"{self.regional_desk} · {self.client.name}"


class Site(models.Model):
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="sites")
    name = models.CharField(max_length=200)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["client", "name"], name="unique_site_per_client")
        ]

    def __str__(self):
        return f"{self.client} — {self.name}"


class RegionalFacilityQuerySet(models.QuerySet):
    _SCOPE_FIELDS = {"regional_client", "regional_client_id", "site", "site_id"}

    def update(self, **kwargs):
        if self._SCOPE_FIELDS.intersection(kwargs):
            raise ValueError(
                "Regional Facility scope must be changed through RegionalFacility.save()."
            )
        return super().update(**kwargs)

    def bulk_create(self, objs, **kwargs):
        objs = list(objs)
        for obj in objs:
            obj.full_clean()
        return super().bulk_create(objs, **kwargs)

    def bulk_update(self, objs, fields, **kwargs):
        if self._SCOPE_FIELDS.intersection(fields):
            raise ValueError(
                "Regional Facility scope must be changed through RegionalFacility.save()."
            )
        return super().bulk_update(objs, fields, **kwargs)


class RegionalFacility(models.Model):
    regional_client = models.ForeignKey(
        RegionalClient,
        on_delete=models.PROTECT,
        related_name="regional_facilities",
    )
    site = models.ForeignKey(
        Site,
        on_delete=models.PROTECT,
        related_name="regional_facilities",
    )
    is_active = models.BooleanField(default=True)
    objects = RegionalFacilityQuerySet.as_manager()

    class Meta:
        ordering = [
            "regional_client__regional_desk__region__name",
            "regional_client__client__name",
            "site__name",
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["regional_client", "site"],
                name="unique_facility_per_regional_client",
            )
        ]

    def clean(self):
        super().clean()
        if not self.regional_client_id or not self.site_id:
            return
        if self.regional_client.client_id != self.site.client_id:
            raise ValidationError({
                "site": "The Facility must belong to the same Client as the regional hierarchy."
            })

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.regional_client} · {self.site.name}"


class Ward(models.Model):
    regional_facility = models.ForeignKey(
        RegionalFacility,
        on_delete=models.PROTECT,
        related_name="wards",
    )
    name = models.CharField(max_length=160)
    code = models.CharField(max_length=40, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["regional_facility__site__name", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["regional_facility", "name"],
                name="unique_ward_per_regional_facility",
            )
        ]

    def __str__(self):
        return f"{self.regional_facility} · {self.name}"


class Profession(models.Model):
    name = models.CharField(max_length=120, unique=True)
    legacy_mysql_id = models.PositiveIntegerField(null=True, blank=True, unique=True)

    def __str__(self):
        return self.name


class ClientProfessionRate(models.Model):
    client = models.ForeignKey(
        Client,
        on_delete=models.CASCADE,
        related_name="profession_rates",
    )
    profession = models.ForeignKey(
        Profession,
        on_delete=models.CASCADE,
        related_name="client_rates",
    )
    legacy_mysql_id = models.PositiveIntegerField(null=True, blank=True, unique=True)
    locally_managed = models.BooleanField(default=False)
    pay_rate = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
    )
    bill_rate = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
    )
    synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["client", "profession"],
                name="unique_rate_per_client_profession",
            ),
            models.CheckConstraint(
                condition=models.Q(pay_rate__gte=0),
                name="client_profession_pay_rate_nonnegative",
            ),
            models.CheckConstraint(
                condition=models.Q(bill_rate__gte=0),
                name="client_profession_bill_rate_nonnegative",
            ),
        ]

    def __str__(self):
        return f"{self.client} · {self.profession}"


class CandidateProfileOption(models.Model):
    class Category(models.TextChoices):
        COUNTRY = "country", "Country"
        VISA_TYPE = "visa_type", "Visa type"
        LANGUAGE = "language", "Language"
        DIVISION = "division", "Division"
        CONSULTANT = "consultant", "Consultant"
        GENDER = "gender", "Gender"
        EMPLOYMENT_EQUITY = "employment_equity", "Employment equity"
        EDUCATION_LEVEL = "education_level", "Education level"
        QUALIFICATION = "qualification", "Qualification"
        QUALIFICATION_TYPE = "qualification_type", "Qualification type"
        SOURCE = "source", "Source"
        MARITAL_STATUS = "marital_status", "Marital status"
        DRIVERS_LICENSE = "drivers_license", "Driver's licence"
        FINGERPRINT_STATUS = "fingerprint_status", "Fingerprint status"
        CRIMINAL_CHECK = "criminal_check", "Criminal check"
        PROVINCE = "province", "Province"
        SUBURB = "suburb", "Suburb"

    category = models.CharField(max_length=32, choices=Category.choices)
    legacy_mysql_id = models.PositiveIntegerField()
    label = models.CharField(max_length=160)
    parent_legacy_mysql_id = models.PositiveIntegerField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["category", "label", "legacy_mysql_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["category", "legacy_mysql_id"],
                name="unique_candidate_profile_option",
            )
        ]

    def __str__(self):
        return f"{self.get_category_display()}: {self.label}"


class Candidate(models.Model):
    class ComplianceStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        CLEARED = "cleared", "Cleared"
        EXPIRED = "expired", "Expired"

    class Sex(models.TextChoices):
        FEMALE = "female", "Female"
        MALE = "male", "Male"
        UNSPECIFIED = "unspecified", "Unspecified"

    class SexSource(models.TextChoices):
        LEGACY = "legacy", "Legacy"
        MANUAL = "manual", "Manual"
        SA_ID = "sa_id", "South African ID"

    class CitizenshipStatus(models.TextChoices):
        CITIZEN = "citizen", "South African citizen"
        PERMANENT_RESIDENT = "permanent_resident", "Permanent resident"
        REFUGEE = "refugee", "Refugee"

    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    preferred_name = models.CharField(max_length=100, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    identity_number = models.CharField(max_length=32, blank=True)
    is_sa_id = models.BooleanField(default=False)
    passport_number = models.CharField(max_length=64, blank=True)
    visa_type = models.CharField(max_length=120, blank=True)
    visa_start = models.DateField(null=True, blank=True)
    visa_end = models.DateField(null=True, blank=True)
    visa_selected = models.BooleanField(default=False)
    country_of_origin = models.CharField(max_length=160, blank=True)
    nationality = models.CharField(max_length=160, blank=True)
    home_language = models.CharField(max_length=160, blank=True)
    is_locum = models.BooleanField(default=False)
    is_permanent = models.BooleanField(default=False)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    home_phone = models.CharField(max_length=40, blank=True)
    other_contact = models.CharField(max_length=120, blank=True)
    physical_address = models.TextField(blank=True)
    legacy_mysql_id = models.PositiveIntegerField(null=True, blank=True, unique=True)
    home_area = models.CharField(max_length=120, blank=True)
    home_region = models.CharField(max_length=120, blank=True)
    postal_code = models.CharField(max_length=16, blank=True)
    note = models.TextField(blank=True)
    division = models.CharField(max_length=120, blank=True)
    assigned_consultant = models.CharField(max_length=160, blank=True)
    sex = models.CharField(max_length=16, choices=Sex.choices, blank=True)
    sex_source = models.CharField(
        max_length=16,
        choices=SexSource.choices,
        blank=True,
    )
    citizenship_status = models.CharField(
        max_length=24,
        choices=CitizenshipStatus.choices,
        blank=True,
    )
    employment_equity = models.CharField(max_length=120, blank=True)
    is_disabled = models.BooleanField(default=False)
    fingerprint_status = models.CharField(max_length=120, blank=True)
    criminal_check = models.CharField(max_length=120, blank=True)
    drivers_license = models.CharField(max_length=120, blank=True)
    owns_car = models.BooleanField(default=False)
    qualification = models.CharField(max_length=160, blank=True)
    qualification_types = models.JSONField(default=list, blank=True)
    education_level = models.CharField(max_length=160, blank=True)
    source = models.CharField(max_length=160, blank=True)
    marital_status = models.CharField(max_length=80, blank=True)
    other_languages = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)
    payroll_code = models.CharField(max_length=40, null=True, blank=True, unique=True)
    profile_locally_managed = models.BooleanField(default=False)
    compliance_status = models.CharField(
        max_length=20,
        choices=ComplianceStatus.choices,
        default=ComplianceStatus.PENDING,
    )
    professions = models.ManyToManyField(Profession, related_name="candidates")
    departments = models.ManyToManyField(
        Department,
        blank=True,
        related_name="candidates",
    )
    wards = models.ManyToManyField(
        Ward,
        through="CandidateWardMembership",
        related_name="candidates",
        blank=True,
    )

    class Meta:
        ordering = ["first_name", "last_name"]

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    def __str__(self):
        return self.full_name


class CandidateWardMembership(models.Model):
    candidate = models.ForeignKey(
        Candidate,
        on_delete=models.CASCADE,
        related_name="ward_memberships",
    )
    ward = models.ForeignKey(
        Ward,
        on_delete=models.PROTECT,
        related_name="candidate_memberships",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["ward__name", "candidate__first_name", "candidate__last_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["candidate", "ward"],
                name="unique_candidate_ward_membership",
            )
        ]

    def __str__(self):
        return f"{self.candidate} · {self.ward}"


class CandidateChangeAudit(models.Model):
    candidate = models.ForeignKey(
        Candidate,
        on_delete=models.PROTECT,
        related_name="change_audits",
    )
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="candidate_change_audits",
    )
    changed_fields = models.JSONField(default=list)
    before = models.JSONField(default=dict)
    after = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]


class FacilityExperience(models.Model):
    candidate = models.ForeignKey(
        Candidate,
        on_delete=models.CASCADE,
        related_name="facility_experiences",
    )
    client = models.ForeignKey(
        Client,
        on_delete=models.CASCADE,
        related_name="candidate_experiences",
    )
    profession = models.ForeignKey(
        Profession,
        on_delete=models.PROTECT,
        related_name="facility_experiences",
    )
    completed_shift_count = models.PositiveIntegerField(default=0)
    total_hours = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    last_worked_on = models.DateField(null=True, blank=True)
    synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["candidate", "client", "profession"],
                name="unique_candidate_facility_role_experience",
            )
        ]

    def __str__(self):
        return f"{self.candidate} at {self.client} ({self.profession})"


class LoginAttempt(models.Model):
    key = models.CharField(max_length=80, primary_key=True)
    failures = models.PositiveSmallIntegerField(default=0)
    expires_at = models.DateTimeField(db_index=True)


class MfaDevice(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="mfa_device",
    )
    secret_ciphertext = models.BinaryField()
    confirmed_at = models.DateTimeField()
    last_used_step = models.BigIntegerField(blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Microsoft Authenticator for {self.user.get_username()}"


class MfaTrustedBrowser(models.Model):
    device = models.ForeignKey(
        MfaDevice,
        on_delete=models.CASCADE,
        related_name="trusted_browsers",
    )
    token_digest = models.CharField(max_length=64, unique=True)
    password_fingerprint = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField(db_index=True)


class MfaAccountState(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="mfa_account_state",
    )
    generation = models.PositiveBigIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)


class LegacyAccessRules(models.Model):
    cap_ts = models.BooleanField(default=False)
    link_ts = models.BooleanField(default=False)
    approve_ts = models.BooleanField(default=False)
    export_ts = models.BooleanField(default=False)
    link_conf = models.BooleanField(default=False)
    export_inv = models.BooleanField(default=False)
    edit_clients = models.BooleanField(default=False)
    edit_cand = models.BooleanField(default=False)
    edit_cons = models.BooleanField(default=False)
    update_client_rates = models.BooleanField(default=False)
    update_cand_rates = models.BooleanField(default=False)
    override_can_rates = models.BooleanField(default=False)
    man_users = models.BooleanField(default=False)
    view_cons_report = models.BooleanField(default=False)
    view_client_report = models.BooleanField(default=False)
    view_can_report = models.BooleanField(default=False)
    view_com_report = models.BooleanField(default=False)
    view_profit_report = models.BooleanField(default=False)
    submit_cand_live = models.BooleanField(default=False)
    delete_files = models.BooleanField(default=False)
    set_compliance = models.BooleanField(default=False)
    assign_cons = models.BooleanField(default=False, null=True)

    class Meta:
        abstract = True


class LegacyAccessPreset(LegacyAccessRules):
    legacy_mysql_id = models.PositiveIntegerField(unique=True)
    description = models.CharField(max_length=100)

    def __str__(self):
        return self.description


class LegacyUserProfile(LegacyAccessRules):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="legacy_profile",
    )
    legacy_mysql_id = models.PositiveIntegerField(unique=True)
    access_type = models.PositiveIntegerField(default=0)
    preset = models.ForeignKey(
        LegacyAccessPreset,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="users",
    )
    assigned_desk = models.PositiveIntegerField(default=0)
    booking_access_override = models.BooleanField(
        null=True,
        blank=True,
        default=None,
        help_text="Leave unknown to use the synchronized legacy booking rule.",
    )
    candidate_access_override = models.BooleanField(
        null=True,
        blank=True,
        default=None,
        help_text="Leave unknown to use the synchronized legacy Candidate rule.",
    )
    all_booking_departments = models.BooleanField(
        default=False,
        help_text="Grant access to every active Booking department.",
    )
    booking_departments = models.ManyToManyField(
        Department,
        blank=True,
        related_name="user_access_overrides",
        help_text=(
            "Optional local Booking scope. When empty, the synchronized assigned desk "
            "is used unless all departments is selected."
        ),
    )
    synced_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Legacy access for {self.user}"


class Vacancy(models.Model):
    reference = models.CharField(max_length=200, blank=True)
    site = models.ForeignKey(
        Site,
        on_delete=models.PROTECT,
        related_name="vacancies",
    )
    profession = models.ForeignKey(
        Profession,
        on_delete=models.PROTECT,
        related_name="vacancies",
    )
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="created_vacancies",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.reference or f"Vacancy {self.pk}"


class SiteProfessionRate(models.Model):
    site = models.ForeignKey(
        Site,
        on_delete=models.CASCADE,
        related_name="profession_rates",
    )
    profession = models.ForeignKey(
        Profession,
        on_delete=models.CASCADE,
        related_name="site_rates",
    )
    pay_rate = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
    )
    bill_rate = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["site", "profession"],
                name="unique_rate_per_site_profession",
            )
        ]

    def __str__(self):
        return f"{self.site} · {self.profession}"


class BookingRule(models.Model):
    """Singleton booking policy edited through Django Admin."""

    prevent_candidate_overlap = models.BooleanField(
        default=True,
        editable=False,
        help_text=(
            "Mandatory: a Candidate cannot hold overlapping confirmed bookings, "
            "including at different Clients, facilities or locations."
        ),
    )
    minimum_rest_minutes = models.PositiveIntegerField(
        default=0,
        validators=[MaxValueValidator(1440)],
        help_text=(
            "Minimum time required between a Candidate's confirmed bookings. "
            "Use 0 to allow back-to-back shifts."
        ),
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Booking rule"
        verbose_name_plural = "Booking rules"

    def save(self, *args, **kwargs):
        self.pk = 1
        self.prevent_candidate_overlap = True
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("The mandatory booking rule cannot be deleted.")

    @classmethod
    def current(cls):
        rule = cls.objects.filter(pk=1).only("minimum_rest_minutes").first()
        return rule or cls(pk=1, minimum_rest_minutes=0)

    def __str__(self):
        return "No Candidate double booking"


class ShiftQuerySet(models.QuerySet):
    _SCOPE_FIELDS = {
        "vacancy",
        "vacancy_id",
        "site",
        "site_id",
        "profession",
        "profession_id",
    }

    def update(self, **kwargs):
        if self._SCOPE_FIELDS.intersection(kwargs):
            raise ValueError("Shift scope must be changed through Shift.save().")
        return super().update(**kwargs)

    def bulk_create(self, objs, **kwargs):
        objs = list(objs)
        vacancy_ids = {shift.vacancy_id for shift in objs if shift.vacancy_id}
        vacancy_scopes = {
            row["id"]: (row["site_id"], row["profession_id"])
            for row in Vacancy.objects.filter(pk__in=vacancy_ids).values(
                "id", "site_id", "profession_id"
            )
        }
        for shift in objs:
            vacancy_scope = vacancy_scopes.get(shift.vacancy_id)
            if vacancy_scope and (
                shift.site_id != vacancy_scope[0]
                or shift.profession_id != vacancy_scope[1]
            ):
                raise ValidationError({
                    "vacancy": "A shift must use the same facility and role as its vacancy."
                })
            if shift.status != "open":
                raise ValidationError({
                    "status": "New shifts created in bulk must start open."
                })
        return super().bulk_create(objs, **kwargs)


class Shift(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        BOOKED = "booked", "Booked"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    vacancy = models.ForeignKey(
        Vacancy,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="shifts",
    )
    objects = ShiftQuerySet.as_manager()
    site = models.ForeignKey(Site, on_delete=models.PROTECT, related_name="shifts")
    profession = models.ForeignKey(
        Profession, on_delete=models.PROTECT, related_name="shifts"
    )
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    pay_rate = models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(0)]
    )
    bill_rate = models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(0)]
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["starts_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(ends_at__gt=models.F("starts_at")),
                name="shift_ends_after_start",
            ),
            models.CheckConstraint(
                condition=models.Q(pay_rate__gte=0), name="shift_pay_rate_nonnegative"
            ),
            models.CheckConstraint(
                condition=models.Q(bill_rate__gte=0), name="shift_bill_rate_nonnegative"
            ),
        ]

    def clean(self):
        super().clean()
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            raise ValidationError({"ends_at": "Shift end must be after its start."})
        if self.vacancy_id:
            vacancy_scope = Vacancy.objects.filter(pk=self.vacancy_id).values(
                "site_id", "profession_id"
            ).first()
            if vacancy_scope and (
                self.site_id != vacancy_scope["site_id"]
                or self.profession_id != vacancy_scope["profession_id"]
            ):
                raise ValidationError({
                    "vacancy": "A shift must use the same facility and role as its vacancy."
                })
        if self.status in [self.Status.OPEN, self.Status.BOOKED]:
            has_confirmation = bool(
                self.pk
                and self.bookings.filter(status=Booking.Status.CONFIRMED).exists()
            )
            expected_status = self.Status.BOOKED if has_confirmation else self.Status.OPEN
            if self.status != expected_status:
                raise ValidationError({
                    "status": "Open and booked statuses are managed by confirmed bookings."
                })

    def save(self, *args, **kwargs):
        if not self.pk:
            self.full_clean()
            return super().save(*args, **kwargs)
        with transaction.atomic():
            Shift.objects.select_for_update().get(pk=self.pk)
            self.full_clean()
            return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.site} | {self.starts_at:%Y-%m-%d %H:%M}"


class BookingQuerySet(models.QuerySet):
    def delete(self):
        candidate_ids = list(self.values_list("pk", flat=True))
        if not candidate_ids:
            return 0, {}
        with transaction.atomic():
            locked_bookings = list(
                self.select_for_update()
                .filter(pk__in=candidate_ids)
                .order_by("pk")
                .values("pk", "shift_id")
            )
            booking_ids = [row["pk"] for row in locked_bookings]
            if not booking_ids:
                return 0, {}
            shift_ids = sorted({row["shift_id"] for row in locked_bookings})
            list(
                Shift.objects.select_for_update()
                .filter(pk__in=shift_ids)
                .order_by("pk")
            )
            locked_queryset = self.model._base_manager.filter(pk__in=booking_ids)
            result = models.QuerySet.delete(locked_queryset)
            for shift_id in shift_ids:
                self.model._sync_shift_status(shift_id)
            return result


class LegacySyncRun(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        BLOCKED = "blocked", "Blocked"

    started_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="legacy_sync_runs",
    )
    dry_run = models.BooleanField(default=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    source_counts = models.JSONField(default=dict, blank=True)
    imported_counts = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        permissions = [
            (
                "run_legacy_sync",
                "Can run the read-only legacy synchronisation",
            ),
        ]

    def __str__(self):
        mode = "dry run" if self.dry_run else "sync"
        return f"Legacy {mode} #{self.pk or 'new'} ({self.status})"


class Booking(models.Model):
    class Status(models.TextChoices):
        OFFERED = "offered", "Offered"
        CONFIRMED = "confirmed", "Confirmed"
        CANCELLED = "cancelled", "Cancelled"

    shift = models.ForeignKey(Shift, on_delete=models.PROTECT, related_name="bookings")
    candidate = models.ForeignKey(
        Candidate, on_delete=models.PROTECT, related_name="bookings"
    )
    objects = BookingQuerySet.as_manager()
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.OFFERED
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        permissions = [
            ("manage_bookings", "Can create, update and delete bookings"),
            ("view_candidate_pay_rates", "Can view Candidate pay rates"),
            (
                "view_client_charge_rates",
                "Can view Client charges and profitability",
            ),
            ("override_approved_rates", "Can override approved rates"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["shift"],
                condition=models.Q(status="confirmed"),
                name="one_confirmed_booking_per_shift",
            )
        ]

    def clean(self):
        super().clean()
        if self.status != self.Status.CONFIRMED or not self.candidate_id or not self.shift_id:
            return
        if Booking.objects.filter(
            shift_id=self.shift_id, status=self.Status.CONFIRMED,
        ).exclude(pk=self.pk).exists():
            raise ValidationError({"shift": "Shift already has a confirmed booking."})
        was_confirmed_here = bool(
            self.pk
            and Booking.objects.filter(
                pk=self.pk,
                shift_id=self.shift_id,
                status=self.Status.CONFIRMED,
            ).exists()
        )
        if self.shift.status != Shift.Status.OPEN and not (
            self.shift.status == Shift.Status.BOOKED and was_confirmed_here
        ):
            raise ValidationError({"shift": "Only an open shift can be confirmed."})
        if not self.candidate.is_active:
            raise ValidationError({"candidate": "Inactive candidates cannot be booked."})
        if self.candidate.compliance_status != Candidate.ComplianceStatus.CLEARED:
            raise ValidationError(
                {"candidate": "Candidate must be compliance-cleared before confirmation."}
            )
        if not self.candidate.professions.filter(pk=self.shift.profession_id).exists():
            raise ValidationError(
                {"candidate": "Candidate does not have the required profession for this shift."}
            )
        overlap_exists = Booking.objects.filter(
            candidate_id=self.candidate_id,
            status=self.Status.CONFIRMED,
            shift__starts_at__lt=self.shift.ends_at,
            shift__ends_at__gt=self.shift.starts_at,
        ).exclude(pk=self.pk).exists()
        if overlap_exists:
            raise ValidationError({
                "candidate": (
                    "Candidate is already booked in another confirmed booking "
                    "that overlaps this shift, regardless of location."
                )
            })
        rest_minutes = BookingRule.current().minimum_rest_minutes
        if rest_minutes:
            minimum_rest = timedelta(minutes=rest_minutes)
            rest_conflict = Booking.objects.filter(
                candidate_id=self.candidate_id,
                status=self.Status.CONFIRMED,
                shift__starts_at__lt=self.shift.ends_at + minimum_rest,
                shift__ends_at__gt=self.shift.starts_at - minimum_rest,
            ).exclude(pk=self.pk).exists()
            if rest_conflict:
                raise ValidationError({
                    "candidate": (
                        f"Candidate requires a minimum rest period of {rest_minutes} "
                        "minutes between confirmed bookings."
                    )
                })

    def save(self, *args, **kwargs):
        with transaction.atomic():
            previous = None
            if self.pk:
                previous = Booking.objects.select_for_update().filter(pk=self.pk).values(
                    "shift_id", "candidate_id", "status"
                ).first()
            if self.pk and not self._state.adding and previous is None:
                raise ValidationError("This booking no longer exists.")
            update_fields = kwargs.get("update_fields")
            if previous and update_fields is not None:
                updated = set(update_fields)
                if updated.isdisjoint({"shift", "shift_id"}):
                    self.shift_id = previous["shift_id"]
                if updated.isdisjoint({"candidate", "candidate_id"}):
                    self.candidate_id = previous["candidate_id"]
                if "status" not in updated:
                    self.status = previous["status"]
            shift_ids = {shift_id for shift_id in [
                self.shift_id,
                previous["shift_id"] if previous else None,
            ] if shift_id}
            locked_shifts = {
                shift.pk: shift
                for shift in Shift.objects.select_for_update()
                .filter(pk__in=shift_ids)
                .order_by("pk")
            }
            if self.shift_id:
                self.shift = locked_shifts[self.shift_id]
            if self.candidate_id:
                self.candidate = Candidate.objects.select_for_update().get(
                    pk=self.candidate_id
                )
            self.full_clean()
            super().save(*args, **kwargs)
            for shift_id in shift_ids:
                self._sync_shift_status(shift_id)

    def delete(self, *args, **kwargs):
        with transaction.atomic():
            locked_booking = Booking.objects.select_for_update().get(pk=self.pk)
            shift_id = locked_booking.shift_id
            Shift.objects.select_for_update().get(pk=shift_id)
            result = super().delete(*args, **kwargs)
            self._sync_shift_status(shift_id)
            return result

    @classmethod
    def _sync_shift_status(cls, shift_id):
        has_confirmation = cls.objects.filter(
            shift_id=shift_id, status=cls.Status.CONFIRMED
        ).exists()
        Shift.objects.filter(
            pk=shift_id, status__in=[Shift.Status.OPEN, Shift.Status.BOOKED]
        ).update(
            status=Shift.Status.BOOKED if has_confirmation else Shift.Status.OPEN
        )

    def __str__(self):
        return f"{self.candidate} → {self.shift}"


class SmsMessage(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        PROCESSING = "processing", "Processing"
        ACCEPTED = "accepted", "Accepted by provider"
        FAILED = "failed", "Failed"

    booking = models.OneToOneField(
        Booking,
        on_delete=models.PROTECT,
        related_name="confirmation_sms",
    )
    candidate = models.ForeignKey(
        Candidate,
        on_delete=models.PROTECT,
        related_name="sms_messages",
    )
    destination = models.CharField(max_length=16)
    body = models.TextField()
    customer_id = models.CharField(max_length=80, unique=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.QUEUED,
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="requested_sms_messages",
    )
    requested_at = models.DateTimeField(auto_now_add=True)
    processing_started_at = models.DateTimeField(null=True, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    provider_event_id = models.CharField(max_length=80, blank=True)
    attempt_count = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True)

    class Meta:
        ordering = ["-requested_at", "-id"]
        permissions = [
            ("send_booking_sms", "Can queue booking confirmation SMS messages"),
        ]

    def __str__(self):
        return f"Booking SMS #{self.pk or 'new'} ({self.status})"


class Timesheet(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Submitted for approval"
        DECLINED = "declined", "Declined"
        APPROVED = "approved", "Approved"
        VOID = "void", "Void"

    booking = models.OneToOneField(
        Booking,
        on_delete=models.PROTECT,
        related_name="timesheet",
    )
    number = models.CharField(max_length=80, unique=True)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    captured_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="captured_timesheets",
    )
    captured_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approved_timesheets",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    declined_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="declined_timesheets",
    )
    declined_at = models.DateTimeField(null=True, blank=True)
    decline_reason = models.TextField(blank=True)
    payroll_ready_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="payroll_staged_timesheets",
    )
    payroll_ready_at = models.DateTimeField(null=True, blank=True)
    payroll_exported_at = models.DateTimeField(null=True, blank=True)
    invoiced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-captured_at", "-id"]
        permissions = [
            ("capture_timesheet", "Can capture timesheets"),
            ("approve_timesheet", "Can approve or decline timesheets"),
            ("export_payroll", "Can generate payroll exports"),
            ("generate_invoice", "Can generate invoices"),
            ("export_accounting", "Can generate accounting exports"),
        ]

    def __str__(self):
        return self.number


class TimesheetLine(models.Model):
    class RateCategory(models.TextChoices):
        NORMAL = "normal", "Normal / day"
        SATURDAY = "saturday", "Saturday"
        SUNDAY = "sunday", "Sunday"
        OVERTIME = "overtime", "Overtime"
        STANDBY = "standby", "Standby"
        NIGHT = "night", "Night"
        PUBLIC_HOLIDAY = "public_holiday", "Public holiday"
        STANDBY_HOLIDAY = "standby_holiday", "Standby Holiday"
        STANDBY_SUNDAY = "standby_sunday", "Standby Sunday"
        STANDBY_WEEK = "standby_week", "Standby Week"

    timesheet = models.ForeignKey(
        Timesheet,
        on_delete=models.PROTECT,
        related_name="lines",
    )
    actual_start = models.DateTimeField()
    actual_end = models.DateTimeField()
    break_minutes = models.PositiveIntegerField(default=0)
    rate_category = models.CharField(
        max_length=24,
        choices=RateCategory.choices,
        default=RateCategory.NORMAL,
    )
    pay_rate = models.DecimalField(max_digits=10, decimal_places=2)
    bill_rate = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        ordering = ["actual_start", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(actual_end__gt=models.F("actual_start")),
                name="timesheet_line_ends_after_start",
            ),
            models.CheckConstraint(
                condition=models.Q(pay_rate__gte=0),
                name="timesheet_line_pay_rate_nonnegative",
            ),
            models.CheckConstraint(
                condition=models.Q(bill_rate__gte=0),
                name="timesheet_line_bill_rate_nonnegative",
            ),
        ]

    @property
    def worked_hours(self):
        seconds = Decimal(str((self.actual_end - self.actual_start).total_seconds()))
        hours = seconds / Decimal("3600") - Decimal(self.break_minutes) / Decimal("60")
        return hours.quantize(Decimal("0.01"))

    def clean(self):
        super().clean()
        if self.actual_start and self.actual_end:
            if self.actual_end <= self.actual_start:
                raise ValidationError({"actual_end": "Worked end must be after start."})
            duration_minutes = int(
                (self.actual_end - self.actual_start).total_seconds() // 60
            )
            if self.break_minutes >= duration_minutes:
                raise ValidationError({
                    "break_minutes": "Break must be shorter than the worked interval."
                })


def timesheet_document_path(instance, filename):
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    return f"timesheets/{instance.timesheet_id}/{uuid.uuid4().hex}.{extension}"


class TimesheetDocument(models.Model):
    class Kind(models.TextChoices):
        SOURCE = "source", "Signed timesheet"
        CLIENT_CONFIRMATION = "client_confirmation", "Client confirmation / motivation"

    timesheet = models.ForeignKey(
        Timesheet,
        on_delete=models.PROTECT,
        related_name="documents",
    )
    kind = models.CharField(max_length=32, choices=Kind.choices, default=Kind.SOURCE)
    file = models.FileField(storage=private_storage, upload_to=timesheet_document_path)
    original_name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=120)
    size = models.PositiveBigIntegerField()
    sha256 = models.CharField(max_length=64)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="uploaded_timesheet_documents",
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)
    is_current = models.BooleanField(default=True)

    class Meta:
        ordering = ["-uploaded_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["timesheet", "kind"],
                condition=models.Q(is_current=True),
                name="one_current_document_per_timesheet_kind",
            ),
        ]

    @staticmethod
    def digest(uploaded):
        digest = hashlib.sha256()
        for chunk in uploaded.chunks():
            digest.update(chunk)
        uploaded.seek(0)
        return digest.hexdigest()


class TimesheetEvent(models.Model):
    timesheet = models.ForeignKey(
        Timesheet,
        on_delete=models.PROTECT,
        related_name="events",
    )
    action = models.CharField(max_length=40)
    from_status = models.CharField(max_length=16)
    to_status = models.CharField(max_length=16)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="timesheet_events",
    )
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]


class FinanceSettings(models.Model):
    vat_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("15.00"))
    sales_contra_account = models.CharField(max_length=40, default="4000")
    invoice_issuer_legal_name = models.CharField(max_length=200, blank=True)
    invoice_issuer_vat_number = models.CharField(max_length=40, blank=True)
    invoice_issuer_address = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Finance setting"

    def save(self, *args, **kwargs):
        self.pk = 1
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Finance settings cannot be deleted.")

    @classmethod
    def current(cls):
        return cls.objects.filter(pk=1).first() or cls(pk=1)


def invoice_document_path(instance, filename):
    return f"invoices/{instance.invoice_date:%Y}/{instance.number}.pdf"


class Invoice(models.Model):
    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="invoices")
    number = models.CharField(max_length=40, null=True, blank=True, unique=True)
    invoice_date = models.DateField()
    client_name = models.CharField(max_length=200)
    accounting_code = models.CharField(max_length=40)
    client_billing_address = models.TextField(default="")
    client_vat_number = models.CharField(max_length=40, blank=True)
    issuer_legal_name = models.CharField(max_length=200, default="")
    issuer_vat_number = models.CharField(max_length=40, blank=True)
    issuer_address = models.TextField(default="")
    subtotal = models.DecimalField(max_digits=14, decimal_places=2)
    vat_percent = models.DecimalField(max_digits=5, decimal_places=2)
    vat_amount = models.DecimalField(max_digits=14, decimal_places=2)
    total = models.DecimalField(max_digits=14, decimal_places=2)
    document = models.FileField(
        storage=private_storage,
        upload_to=invoice_document_path,
        blank=True,
    )
    generated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="generated_invoices",
    )
    generated_at = models.DateTimeField(auto_now_add=True)
    pastel_exported_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-invoice_date", "-id"]

    def __str__(self):
        return self.number or f"Invoice {self.pk}"


class InvoiceLine(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="lines")
    timesheet = models.ForeignKey(
        Timesheet,
        on_delete=models.PROTECT,
        related_name="invoice_lines",
    )
    timesheet_number = models.CharField(max_length=80)
    candidate_name = models.CharField(max_length=220)
    description = models.CharField(max_length=255)
    worked_hours = models.DecimalField(max_digits=10, decimal_places=2)
    bill_rate = models.DecimalField(max_digits=10, decimal_places=2)
    amount = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        ordering = ["id"]


class FinanceExportBatch(models.Model):
    class Kind(models.TextChoices):
        PAYROLL = "payroll", "Payroll"
        PASTEL_SALES = "pastel_sales", "Pastel sales"
        PASTEL_CREDIT = "pastel_credit", "Pastel credit notes"

    class Status(models.TextChoices):
        GENERATED = "generated", "Generated"
        UPLOAD_CONFIRMED = "upload_confirmed", "External upload confirmed"
        VOID = "void", "Void"

    kind = models.CharField(max_length=24, choices=Kind.choices)
    status = models.CharField(
        max_length=24,
        choices=Status.choices,
        default=Status.GENERATED,
    )
    process_code = models.CharField(max_length=80)
    file_name = models.CharField(max_length=180)
    content = models.TextField()
    sha256 = models.CharField(max_length=64)
    timesheets = models.ManyToManyField(Timesheet, related_name="export_batches", blank=True)
    invoices = models.ManyToManyField(Invoice, related_name="export_batches", blank=True)
    generated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="generated_finance_exports",
    )
    generated_at = models.DateTimeField(auto_now_add=True)
    upload_confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="confirmed_finance_exports",
    )
    upload_confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-generated_at", "-id"]
