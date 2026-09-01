from django.conf import settings
from django.contrib import admin, messages
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import FileResponse, HttpResponse, HttpResponseBadRequest, HttpResponseNotAllowed
from django.db.models import Q
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html

from bookings.department_scope import (
    scope_queryset_to_user_departments,
    user_department_ids,
)
from bookings.forms import (
    LegacyUserAccessAdminForm,
    RateExcelImportForm,
    TimesheetCaptureAdminForm,
    TimesheetDeclineAdminForm,
    TimesheetDocumentAdminForm,
)
from bookings.legacy_sync import execute_legacy_sync
from bookings.models import (
    Booking,
    BookingRule,
    Candidate,
    CandidateChangeAudit,
    CandidateProfileOption,
    CandidateWardMembership,
    Client,
    ClientProfessionRate,
    Department,
    FacilityExperience,
    FinanceExportBatch,
    FinanceSettings,
    Invoice,
    InvoiceLine,
    LegacyAccessPreset,
    LegacySyncRun,
    LegacyUserProfile,
    MfaDevice,
    Profession,
    Region,
    RegionalClient,
    RegionalDesk,
    RegionalFacility,
    Shift,
    Site,
    SiteProfessionRate,
    SmsMessage,
    Timesheet,
    TimesheetDocument,
    TimesheetEvent,
    TimesheetLine,
    Vacancy,
    Ward,
)
from bookings.permissions import (
    user_can_manage_bookings,
    user_can_manage_candidates,
    user_can_override_approved_rates,
    user_can_view_candidate_pay_rates,
    user_can_view_client_charge_rates,
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
from bookings.rate_excel import (
    CLIENT_RATE_HEADERS,
    SITE_RATE_HEADERS,
    RateWorkbookError,
    build_client_rate_workbook,
    build_site_rate_workbook,
    import_client_rate_workbook,
    import_site_rate_workbook,
)


def _has_legacy_operation(user, legacy_field, django_permission):
    if user.is_superuser:
        return True
    try:
        return bool(getattr(user.legacy_profile, legacy_field))
    except LegacyUserProfile.DoesNotExist:
        return user.has_perm(django_permission)


class MfaDeviceInline(admin.StackedInline):
    model = MfaDevice
    extra = 0
    can_delete = True
    fields = ["confirmed_at", "last_used_step", "updated_at"]
    readonly_fields = fields
    verbose_name = "Microsoft Authenticator enrollment"
    verbose_name_plural = "Microsoft Authenticator enrollment"

    def has_add_permission(self, request, obj=None):
        return False


class LegacyUserAccessInline(admin.StackedInline):
    model = LegacyUserProfile
    form = LegacyUserAccessAdminForm
    extra = 0
    can_delete = False
    filter_horizontal = ["booking_departments"]
    fieldsets = (
        (
            "Legacy source (read only)",
            {
                "fields": (
                    "legacy_mysql_id",
                    "assigned_desk",
                    "access_type",
                    "preset",
                    "link_conf",
                    "edit_cand",
                    "man_users",
                    "synced_at",
                ),
                "description": (
                    "These values come from the legacy system and are refreshed by sync. "
                    "Use the local controls below for durable Booking-system exceptions."
                ),
            },
        ),
        (
            "Booking-system access",
            {
                "fields": (
                    "booking_access_override",
                    "candidate_access_override",
                    "all_booking_departments",
                    "booking_departments",
                ),
                "description": (
                    "Leave permission overrides as Unknown to follow the legacy rules. "
                    "Specific departments take precedence over the legacy assigned desk."
                ),
            },
        ),
    )
    readonly_fields = [
        "legacy_mysql_id",
        "assigned_desk",
        "access_type",
        "preset",
        "link_conf",
        "edit_cand",
        "man_users",
        "synced_at",
    ]

    def has_add_permission(self, request, obj=None):
        return False


admin.site.unregister(get_user_model())


@admin.register(get_user_model())
class ImmployUserAdmin(UserAdmin):
    inlines = [LegacyUserAccessInline, MfaDeviceInline]
    list_display = [
        "username",
        "display_name",
        "is_active",
        "access_summary",
        "department_summary",
        "access_problem",
        "mfa_status",
    ]
    list_filter = [
        "is_active",
        "is_staff",
        "legacy_profile__assigned_desk",
        "legacy_profile__link_conf",
        "legacy_profile__edit_cand",
        "legacy_profile__all_booking_departments",
    ]
    list_select_related = ["mfa_device", "legacy_profile"]
    search_fields = ["username", "first_name", "last_name", "email"]
    readonly_fields = [*UserAdmin.readonly_fields, "mfa_status", "mfa_recovery_guidance"]
    fieldsets = (
        *UserAdmin.fieldsets,
        (
            "MFA recovery",
            {"fields": ("mfa_status", "mfa_recovery_guidance")},
        ),
    )

    @admin.display(description="MFA status")
    def mfa_status(self, obj):
        if obj is None:
            return "Not enrolled"
        return "Enabled" if hasattr(obj, "mfa_device") else "Not enrolled"

    @admin.display(description="Secure recovery")
    def mfa_recovery_guidance(self, obj):
        return (
            "To disable or reset MFA, select Delete on the Microsoft Authenticator "
            "enrollment below and save. This revokes the user's sessions. The user "
            "must then sign in with their password and enroll their own Authenticator "
            "from Sign-in security; administrators cannot create or view the MFA secret."
        )

    @admin.display(description="Name", ordering="first_name")
    def display_name(self, obj):
        return obj.get_full_name() or "—"

    @admin.display(description="Booking permissions")
    def access_summary(self, obj):
        booking = user_can_manage_bookings(obj)
        candidates = user_can_manage_candidates(obj)
        return format_html(
            '<strong style="color:{}">Booking: {}</strong><br>'
            '<span style="color:{}">Candidates: {}</span>',
            "#237804" if booking else "#b42318",
            "Yes" if booking else "No",
            "#237804" if candidates else "#b42318",
            "Yes" if candidates else "No",
        )

    @admin.display(description="Department scope")
    def department_summary(self, obj):
        department_ids = user_department_ids(obj)
        if department_ids is None:
            return "All Booking departments"
        if not department_ids:
            return "No department"
        return ", ".join(
            Department.objects.filter(pk__in=department_ids)
            .order_by("legacy_mysql_id")
            .values_list("name", flat=True)
        )

    @admin.display(description="Access check")
    def access_problem(self, obj):
        if not obj.is_active or not obj.is_staff:
            return "—"
        has_access = user_can_manage_bookings(obj) or user_can_manage_candidates(obj)
        if has_access and not user_department_ids(obj):
            return format_html(
                '<strong style="color:#b42318">{}</strong>',
                "No Booking department scope",
            )
        return format_html('<span style="color:#237804">{}</span>', "Ready")


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ["name", "legacy_mysql_id", "is_active"]
    list_filter = ["is_active"]
    search_fields = ["name"]
    readonly_fields = ["legacy_mysql_id", "name", "is_active"]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Region)
class RegionAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "is_active"]
    list_editable = ["is_active"]
    list_filter = ["is_active"]
    search_fields = ["name", "code"]


@admin.register(RegionalDesk)
class RegionalDeskAdmin(admin.ModelAdmin):
    list_display = ["region", "department", "is_active"]
    list_editable = ["is_active"]
    list_filter = ["region", "department", "is_active"]
    search_fields = ["region__name", "region__code", "department__name"]
    autocomplete_fields = ["region", "department"]
    list_select_related = ["region", "department"]


@admin.register(RegionalClient)
class RegionalClientAdmin(admin.ModelAdmin):
    list_display = ["regional_desk", "client", "is_active"]
    list_editable = ["is_active"]
    list_filter = [
        "regional_desk__region",
        "regional_desk__department",
        "is_active",
    ]
    search_fields = [
        "regional_desk__region__name",
        "regional_desk__department__name",
        "client__name",
    ]
    autocomplete_fields = ["regional_desk", "client"]
    list_select_related = [
        "regional_desk__region",
        "regional_desk__department",
        "client",
    ]


@admin.register(RegionalFacility)
class RegionalFacilityAdmin(admin.ModelAdmin):
    list_display = ["site", "regional_client", "is_active"]
    list_editable = ["is_active"]
    list_filter = [
        "regional_client__regional_desk__region",
        "regional_client__regional_desk__department",
        "is_active",
    ]
    search_fields = [
        "site__name",
        "regional_client__client__name",
        "regional_client__regional_desk__region__name",
    ]
    autocomplete_fields = ["regional_client", "site"]
    list_select_related = [
        "site__client",
        "regional_client__client",
        "regional_client__regional_desk__region",
        "regional_client__regional_desk__department",
    ]


@admin.register(Ward)
class WardAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "regional_facility", "is_active"]
    list_editable = ["is_active"]
    list_filter = [
        "regional_facility__regional_client__regional_desk__region",
        "regional_facility__regional_client__regional_desk__department",
        "is_active",
    ]
    search_fields = [
        "name",
        "code",
        "regional_facility__site__name",
        "regional_facility__regional_client__client__name",
    ]
    autocomplete_fields = ["regional_facility"]
    list_select_related = [
        "regional_facility__site",
        "regional_facility__regional_client__client",
        "regional_facility__regional_client__regional_desk__region",
        "regional_facility__regional_client__regional_desk__department",
    ]


@admin.register(CandidateWardMembership)
class CandidateWardMembershipAdmin(admin.ModelAdmin):
    list_display = ["candidate", "ward", "is_active"]
    list_editable = ["is_active"]
    list_filter = [
        "ward__regional_facility__regional_client__regional_desk__region",
        "ward__regional_facility__regional_client__regional_desk__department",
        "is_active",
    ]
    search_fields = [
        "candidate__first_name",
        "candidate__last_name",
        "ward__name",
        "ward__regional_facility__site__name",
    ]
    autocomplete_fields = ["candidate", "ward"]
    list_select_related = [
        "candidate",
        "ward__regional_facility__site",
        "ward__regional_facility__regional_client__client",
    ]


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ["name", "city", "region", "is_active", "legacy_mysql_id"]
    list_editable = ["city", "region"]
    list_filter = ["is_active", "departments"]
    search_fields = ["name", "city", "region"]
    filter_horizontal = ["departments"]

    def get_queryset(self, request):
        return scope_queryset_to_user_departments(
            super().get_queryset(request),
            request.user,
        )


@admin.register(Site)
class SiteAdmin(admin.ModelAdmin):
    list_display = ["name", "client"]
    list_filter = ["client"]
    search_fields = ["name", "client__name"]


@admin.register(Profession)
class ProfessionAdmin(admin.ModelAdmin):
    list_display = ["name", "legacy_mysql_id"]
    search_fields = ["name"]


class RateExcelAdminMixin:
    change_list_template = "admin/bookings/rates/change_list.html"
    import_headers = ()
    export_filename = "rates.xlsx"

    def has_view_permission(self, request, obj=None):
        return super().has_view_permission(request, obj) and (
            user_can_view_candidate_pay_rates(request.user)
            or user_can_view_client_charge_rates(request.user)
        )

    def has_change_permission(self, request, obj=None):
        return (
            super().has_change_permission(request, obj)
            and user_can_override_approved_rates(request.user)
            and (
                user_can_view_candidate_pay_rates(request.user)
                or user_can_view_client_charge_rates(request.user)
            )
        )

    def has_add_permission(self, request):
        return (
            super().has_add_permission(request)
            and user_can_override_approved_rates(request.user)
            and user_can_view_candidate_pay_rates(request.user)
            and user_can_view_client_charge_rates(request.user)
        )

    def has_delete_permission(self, request, obj=None):
        return (
            super().has_delete_permission(request, obj)
            and user_can_override_approved_rates(request.user)
        )

    def get_list_display(self, request):
        fields = list(super().get_list_display(request))
        if not user_can_view_candidate_pay_rates(request.user):
            fields.remove("pay_rate")
        if not user_can_view_client_charge_rates(request.user):
            fields.remove("bill_rate")
        return fields

    def get_exclude(self, request, obj=None):
        excluded = list(super().get_exclude(request, obj) or [])
        if not user_can_view_candidate_pay_rates(request.user):
            excluded.append("pay_rate")
        if not user_can_view_client_charge_rates(request.user):
            excluded.append("bill_rate")
        return excluded

    def get_readonly_fields(self, request, obj=None):
        readonly = list(super().get_readonly_fields(request, obj))
        if not user_can_override_approved_rates(request.user):
            if user_can_view_candidate_pay_rates(request.user):
                readonly.append("pay_rate")
            if user_can_view_client_charge_rates(request.user):
                readonly.append("bill_rate")
        return readonly

    def get_urls(self):
        opts = self.model._meta
        return [
            path(
                "import-xlsx/",
                self.admin_site.admin_view(self.import_xlsx_view),
                name=f"{opts.app_label}_{opts.model_name}_import_xlsx",
            ),
            path(
                "export-xlsx/",
                self.admin_site.admin_view(self.export_xlsx_view),
                name=f"{opts.app_label}_{opts.model_name}_export_xlsx",
            ),
        ] + super().get_urls()

    def has_rate_import_permission(self, request):
        return self.has_add_permission(request) and self.has_change_permission(request)

    def changelist_view(self, request, extra_context=None):
        return super().changelist_view(request, {
            **(extra_context or {}),
            "has_rate_import_permission": self.has_rate_import_permission(request),
        })

    def export_xlsx_view(self, request):
        if not (
            self.has_view_or_change_permission(request)
            and user_can_view_candidate_pay_rates(request.user)
            and user_can_view_client_charge_rates(request.user)
        ):
            raise PermissionDenied
        response = HttpResponse(
            self.build_workbook(request),
            content_type=(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
        )
        response["Content-Disposition"] = (
            f'attachment; filename="{self.export_filename}"'
        )
        return response

    def import_xlsx_view(self, request):
        if not self.has_rate_import_permission(request):
            raise PermissionDenied
        form = RateExcelImportForm(request.POST or None, request.FILES or None)
        if request.method == "POST" and form.is_valid():
            try:
                summary = self.import_workbook(request, form.cleaned_data["file"])
            except RateWorkbookError as exc:
                for error in exc.errors:
                    form.add_error("file", error)
            else:
                for obj, created in summary.entries:
                    if created:
                        self.log_addition(request, obj, "Imported from Excel")
                    else:
                        self.log_change(request, obj, "Updated from Excel")
                created_label = "rate" if summary.created == 1 else "rates"
                updated_label = "rate" if summary.updated == 1 else "rates"
                messages.success(
                    request,
                    f"{summary.created} {created_label} created and "
                    f"{summary.updated} {updated_label} updated.",
                )
                return redirect(
                    f"admin:{self.model._meta.app_label}_{self.model._meta.model_name}_changelist"
                )
        context = {
            **self.admin_site.each_context(request),
            "title": f"Import {self.model._meta.verbose_name_plural} from Excel",
            "opts": self.model._meta,
            "form": form,
            "expected_headers": self.import_headers,
        }
        return TemplateResponse(
            request,
            "admin/bookings/rates/import_xlsx.html",
            context,
        )


@admin.register(ClientProfessionRate)
class ClientProfessionRateAdmin(RateExcelAdminMixin, admin.ModelAdmin):
    import_headers = CLIENT_RATE_HEADERS
    export_filename = "IMMploy-client-rates.xlsx"
    list_display = [
        "client",
        "profession",
        "pay_rate",
        "bill_rate",
        "locally_managed",
        "legacy_mysql_id",
    ]
    list_filter = ["profession", "client__region"]
    search_fields = ["client__name", "profession__name"]
    readonly_fields = ["legacy_mysql_id", "locally_managed", "synced_at"]

    def get_queryset(self, request):
        return scope_queryset_to_user_departments(
            super().get_queryset(request),
            request.user,
            lookup="client__departments",
        )

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "client" and request is not None:
            kwargs["queryset"] = scope_queryset_to_user_departments(
                Client.objects.all(), request.user
            ).order_by("name")
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        obj.locally_managed = True
        super().save_model(request, obj, form, change)

    def build_workbook(self, request):
        clients = scope_queryset_to_user_departments(
            Client.objects.all(), request.user
        )
        return build_client_rate_workbook(
            self.get_queryset(request), clients, Profession.objects.all()
        )

    def import_workbook(self, request, uploaded):
        clients = scope_queryset_to_user_departments(
            Client.objects.all(), request.user
        )
        return import_client_rate_workbook(
            uploaded,
            self.get_queryset(request),
            clients,
            Profession.objects.all(),
        )


@admin.register(CandidateProfileOption)
class CandidateProfileOptionAdmin(admin.ModelAdmin):
    list_display = ["category", "label", "legacy_mysql_id", "parent_legacy_mysql_id", "is_active"]
    list_filter = ["category", "is_active"]
    search_fields = ["label"]
    readonly_fields = [
        "category",
        "label",
        "legacy_mysql_id",
        "parent_legacy_mysql_id",
        "is_active",
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Candidate)
class CandidateAdmin(admin.ModelAdmin):
    list_display = [
        "full_name",
        "compliance_status",
        "is_active",
        "home_area",
        "home_region",
        "legacy_mysql_id",
    ]
    list_editable = [
        "is_active",
        "home_area",
        "home_region",
    ]
    list_filter = [
        "is_active",
        "compliance_status",
        "departments",
        "professions",
    ]
    search_fields = [
        "first_name",
        "last_name",
        "email",
        "phone",
        "home_area",
        "home_region",
        "professions__name",
    ]
    filter_horizontal = ["professions", "departments"]
    readonly_fields = ["legacy_mysql_id", "profile_locally_managed"]
    fieldsets = [
        ("Candidate", {"fields": ["first_name", "last_name", "email", "phone"]}),
        (
            "Booking eligibility",
            {
                "description": (
                    "Candidate suggestions use active status, compliance, professions, "
                    "area and region. Booking overlap and shift capacity remain enforced."
                ),
                "fields": [
                    "is_active",
                    "compliance_status",
                    "departments",
                    "professions",
                    "home_area",
                    "home_region",
                    "postal_code",
                ],
            },
        ),
        (
            "Legacy source",
            {"fields": ["legacy_mysql_id", "profile_locally_managed"]},
        ),
        (
            "Payroll integration",
            {
                "description": (
                    "Required before approved timesheets can be included in a payroll export."
                ),
                "fields": ["payroll_code"],
            },
        ),
    ]

    def get_queryset(self, request):
        return scope_queryset_to_user_departments(
            super().get_queryset(request),
            request.user,
        )

    @staticmethod
    def _can_set_compliance(user):
        if user.is_superuser:
            return True
        try:
            return bool(user.legacy_profile.set_compliance)
        except LegacyUserProfile.DoesNotExist:
            return user.has_perm("bookings.change_candidate")

    def get_readonly_fields(self, request, obj=None):
        readonly = list(super().get_readonly_fields(request, obj))
        if not self._can_set_compliance(request.user):
            readonly.append("compliance_status")
        return readonly

    def save_model(self, request, obj, form, change):
        locally_managed_fields = {
            "first_name",
            "last_name",
            "email",
            "phone",
            "home_area",
            "home_region",
            "postal_code",
            "is_active",
            "professions",
        }
        if change and locally_managed_fields.intersection(form.changed_data):
            obj.profile_locally_managed = True
        super().save_model(request, obj, form, change)
        audited_admin_fields = locally_managed_fields | {
            "compliance_status",
            "departments",
            "payroll_code",
        }
        changed_fields = sorted(audited_admin_fields.intersection(form.changed_data))
        if change and changed_fields:
            CandidateChangeAudit.objects.create(
                candidate=obj,
                changed_by=request.user,
                changed_fields=changed_fields,
                before={},
                after={},
            )


@admin.register(CandidateChangeAudit)
class CandidateChangeAuditAdmin(admin.ModelAdmin):
    list_display = ["candidate", "changed_by", "changed_fields", "created_at"]
    list_filter = ["created_at"]
    search_fields = ["candidate__first_name", "candidate__last_name", "changed_by__username"]
    readonly_fields = [
        "candidate",
        "changed_by",
        "changed_fields",
        "before",
        "after",
        "created_at",
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(FacilityExperience)
class FacilityExperienceAdmin(admin.ModelAdmin):
    list_display = [
        "candidate",
        "client",
        "profession",
        "completed_shift_count",
        "last_worked_on",
    ]
    list_filter = ["profession", "client__region"]
    search_fields = [
        "candidate__first_name",
        "candidate__last_name",
        "client__name",
    ]


@admin.register(LegacyAccessPreset)
class LegacyAccessPresetAdmin(admin.ModelAdmin):
    list_display = ["description", "legacy_mysql_id", "link_conf", "man_users"]
    search_fields = ["description"]


class LegacyUserProfileAdmin(admin.ModelAdmin):
    list_display = [
        "user",
        "legacy_mysql_id",
        "assigned_desk",
        "access_type",
        "preset",
        "link_conf",
    ]
    search_fields = ["user__username", "user__first_name", "user__last_name"]
    list_filter = [
        "assigned_desk",
        "access_type",
        "preset",
        "link_conf",
        "man_users",
    ]


@admin.register(LegacySyncRun)
class LegacySyncRunAdmin(admin.ModelAdmin):
    change_list_template = "admin/bookings/legacysyncrun/change_list.html"
    list_display = [
        "created_at",
        "started_by",
        "dry_run",
        "status",
        "started_at",
        "finished_at",
    ]
    list_filter = ["dry_run", "status"]
    readonly_fields = [
        "started_by",
        "dry_run",
        "status",
        "source_counts",
        "imported_counts",
        "error_message",
        "created_at",
        "started_at",
        "finished_at",
    ]

    def get_urls(self):
        return [
            path(
                "run/",
                self.admin_site.admin_view(self.run_sync_view),
                name="bookings_legacysyncrun_run",
            )
        ] + super().get_urls()

    def has_view_permission(self, request, obj=None):
        return super().has_view_permission(request, obj) or request.user.has_perm(
            "bookings.run_legacy_sync"
        )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def run_sync_view(self, request):
        if not request.user.has_perm("bookings.run_legacy_sync"):
            raise PermissionDenied
        if request.method == "POST":
            action = request.POST.get("action")
            if action not in {"dry_run", "sync"}:
                return HttpResponseBadRequest("Select a valid synchronisation action.")
            sync_run = LegacySyncRun.objects.create(
                started_by=request.user,
                dry_run=action == "dry_run",
            )
            execute_legacy_sync(sync_run, settings.LEGACY_MYSQL_CONFIG)
            if sync_run.status == LegacySyncRun.Status.SUCCEEDED:
                messages.success(
                    request,
                    "Legacy dry run completed."
                    if sync_run.dry_run
                    else "Legacy reference-data synchronisation completed.",
                )
            else:
                messages.error(request, sync_run.error_message)
            return redirect("admin:bookings_legacysyncrun_changelist")
        if request.method != "GET":
            return HttpResponseNotAllowed(["GET", "POST"])
        context = {
            **self.admin_site.each_context(request),
            "title": "Read-only legacy synchronisation",
            "opts": self.model._meta,
        }
        return TemplateResponse(
            request,
            "admin/bookings/legacysyncrun/confirm_sync.html",
            context,
        )


@admin.register(MfaDevice)
class MfaDeviceAdmin(admin.ModelAdmin):
    list_display = ["user", "confirmed_at", "updated_at"]
    search_fields = ["user__username", "user__first_name", "user__last_name"]
    fields = ["user", "confirmed_at", "last_used_step", "updated_at"]
    readonly_fields = fields

    def has_add_permission(self, request):
        return False


@admin.register(BookingRule)
class BookingRuleAdmin(admin.ModelAdmin):
    list_display = [
        "overlap_rule",
        "minimum_rest_minutes",
        "updated_at",
    ]
    fields = [
        "overlap_rule",
        "prevent_candidate_overlap",
        "minimum_rest_minutes",
        "updated_at",
    ]
    readonly_fields = [
        "overlap_rule",
        "prevent_candidate_overlap",
        "updated_at",
    ]

    @admin.display(description="Mandatory rule")
    def overlap_rule(self, obj):
        return (
            "No Candidate double booking: one Candidate cannot have overlapping "
            "confirmed bookings, including at different Clients, facilities or locations."
        )

    def has_add_permission(self, request):
        return not BookingRule.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Shift)
class ShiftAdmin(admin.ModelAdmin):
    list_display = ["site", "profession", "starts_at", "ends_at", "status"]
    list_filter = ["status", "profession", "site__client"]
    search_fields = ["site__name", "site__client__name", "notes"]


@admin.register(Vacancy)
class VacancyAdmin(admin.ModelAdmin):
    list_display = ["reference", "site", "profession", "created_by", "created_at"]
    list_filter = ["profession", "site__client"]
    search_fields = ["reference", "site__name", "site__client__name", "notes"]


@admin.register(SiteProfessionRate)
class SiteProfessionRateAdmin(RateExcelAdminMixin, admin.ModelAdmin):
    import_headers = SITE_RATE_HEADERS
    export_filename = "IMMploy-facility-rates.xlsx"
    list_display = ["site", "profession", "pay_rate", "bill_rate", "updated_at"]
    list_filter = ["profession", "site__client"]
    search_fields = ["site__name", "site__client__name", "profession__name"]
    readonly_fields = ["updated_at"]

    def get_queryset(self, request):
        return scope_queryset_to_user_departments(
            super().get_queryset(request),
            request.user,
            lookup="site__client__departments",
        )

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "site" and request is not None:
            kwargs["queryset"] = scope_queryset_to_user_departments(
                Site.objects.select_related("client"),
                request.user,
                lookup="client__departments",
            ).order_by("client__name", "name")
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def build_workbook(self, request):
        sites = scope_queryset_to_user_departments(
            Site.objects.select_related("client"),
            request.user,
            lookup="client__departments",
        )
        return build_site_rate_workbook(
            self.get_queryset(request), sites, Profession.objects.all()
        )

    def import_workbook(self, request, uploaded):
        sites = scope_queryset_to_user_departments(
            Site.objects.select_related("client"),
            request.user,
            lookup="client__departments",
        )
        return import_site_rate_workbook(
            uploaded,
            self.get_queryset(request),
            sites,
            Profession.objects.all(),
        )


class ImmutableFinanceAdminMixin:
    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Timesheet)
class TimesheetAdmin(ImmutableFinanceAdminMixin, admin.ModelAdmin):
    change_list_template = "admin/bookings/timesheet/change_list.html"
    change_form_template = "admin/bookings/timesheet/change_form.html"
    list_display = [
        "number",
        "candidate_name",
        "client_name",
        "status",
        "captured_at",
        "approved_at",
        "payroll_exported_at",
        "invoiced_at",
    ]
    list_filter = ["status", "booking__shift__site__client"]
    search_fields = [
        "number",
        "booking__candidate__first_name",
        "booking__candidate__last_name",
        "booking__shift__site__client__name",
    ]
    readonly_fields = [
        "booking",
        "number",
        "status",
        "captured_by",
        "captured_at",
        "submitted_at",
        "approved_by",
        "approved_at",
        "declined_by",
        "declined_at",
        "decline_reason",
        "payroll_ready_by",
        "payroll_ready_at",
        "payroll_exported_at",
        "invoiced_at",
    ]
    actions = [
        "approve_selected_timesheets",
        "stage_selected_timesheets_for_payroll",
        "generate_payroll_for_selected_timesheets",
        "generate_invoices_for_selected_timesheets",
    ]

    @admin.display(description="Candidate")
    def candidate_name(self, obj):
        return obj.booking.candidate.full_name

    @admin.display(description="Client")
    def client_name(self, obj):
        return obj.booking.shift.site.client.name

    def get_queryset(self, request):
        queryset = super().get_queryset(request).select_related(
            "booking__candidate",
            "booking__shift__site__client",
        )
        return scope_queryset_to_user_departments(
            queryset,
            request.user,
            lookup="booking__shift__site__client__departments",
        )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return self.has_view_permission(request, obj)

    def has_view_permission(self, request, obj=None):
        return request.user.is_staff and any([
            _has_legacy_operation(
                request.user, "cap_ts", "bookings.capture_timesheet"
            ),
            _has_legacy_operation(
                request.user, "link_ts", "bookings.link_timesheet_document"
            ),
            _has_legacy_operation(
                request.user, "link_conf", "bookings.link_client_confirmation"
            ),
            _has_legacy_operation(
                request.user, "approve_ts", "bookings.approve_timesheet"
            ),
            _has_legacy_operation(
                request.user, "export_ts", "bookings.export_payroll"
            ),
            _has_legacy_operation(
                request.user, "export_inv", "bookings.generate_invoice"
            ),
        ])

    def get_actions(self, request):
        actions = super().get_actions(request)
        if not _has_legacy_operation(
            request.user, "approve_ts", "bookings.approve_timesheet"
        ):
            actions.pop("approve_selected_timesheets", None)
        if not _has_legacy_operation(
            request.user, "export_ts", "bookings.export_payroll"
        ):
            actions.pop("stage_selected_timesheets_for_payroll", None)
            actions.pop("generate_payroll_for_selected_timesheets", None)
        if not _has_legacy_operation(
            request.user, "export_inv", "bookings.generate_invoice"
        ):
            actions.pop("generate_invoices_for_selected_timesheets", None)
        return actions

    def get_urls(self):
        return [
            path(
                "capture/",
                self.admin_site.admin_view(self.capture_view),
                name="bookings_timesheet_capture",
            ),
            path(
                "<int:object_id>/decline/",
                self.admin_site.admin_view(self.decline_view),
                name="bookings_timesheet_decline",
            ),
            path(
                "<int:object_id>/replace/",
                self.admin_site.admin_view(self.replace_view),
                name="bookings_timesheet_replace",
            ),
            path(
                "<int:object_id>/void/",
                self.admin_site.admin_view(self.void_view),
                name="bookings_timesheet_void",
            ),
            path(
                "<int:object_id>/confirmation/",
                self.admin_site.admin_view(self.confirmation_view),
                name="bookings_timesheet_confirmation",
            ),
            path(
                "<int:object_id>/documents/<int:document_id>/download/",
                self.admin_site.admin_view(self.document_download_view),
                name="bookings_timesheet_document_download",
            ),
        ] + super().get_urls()

    def changelist_view(self, request, extra_context=None):
        return super().changelist_view(request, {
            **(extra_context or {}),
            "can_capture_timesheet": _has_legacy_operation(
                request.user, "cap_ts", "bookings.capture_timesheet"
            ),
        })

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        timesheet = self.get_object(request, object_id) if object_id else None
        context = {**(extra_context or {})}
        if timesheet is not None:
            context.update({
                "can_decline_timesheet": (
                    timesheet.status == Timesheet.Status.SUBMITTED
                    and _has_legacy_operation(
                        request.user, "approve_ts", "bookings.approve_timesheet"
                    )
                ),
                "can_replace_timesheet": (
                    timesheet.status == Timesheet.Status.DECLINED
                    and (
                        _has_legacy_operation(
                            request.user, "link_ts", "bookings.link_timesheet_document"
                        )
                        or _has_legacy_operation(
                            request.user, "cap_ts", "bookings.capture_timesheet"
                        )
                    )
                ),
                "can_void_timesheet": (
                    timesheet.status == Timesheet.Status.DECLINED
                    and _has_legacy_operation(
                        request.user, "approve_ts", "bookings.approve_timesheet"
                    )
                ),
                "can_upload_confirmation": (
                    timesheet.status in {
                        Timesheet.Status.SUBMITTED,
                        Timesheet.Status.APPROVED,
                    }
                    and _has_legacy_operation(
                        request.user, "link_conf", "bookings.link_client_confirmation"
                    )
                ),
            })
        return super().changeform_view(
            request,
            object_id,
            form_url,
            extra_context=context,
        )

    def capture_view(self, request):
        if not _has_legacy_operation(
            request.user, "cap_ts", "bookings.capture_timesheet"
        ):
            raise PermissionDenied
        bookings = Booking.objects.filter(
            status=Booking.Status.CONFIRMED,
            shift__ends_at__lte=timezone.now(),
            timesheet__isnull=True,
        ).select_related("candidate", "shift__site__client")
        bookings = scope_queryset_to_user_departments(
            bookings,
            request.user,
            lookup="shift__site__client__departments",
        ).order_by("-shift__ends_at")
        form = TimesheetCaptureAdminForm(
            request.POST or None,
            request.FILES or None,
            booking_queryset=bookings,
        )
        if request.method == "POST" and form.is_valid():
            try:
                timesheet = capture_timesheet(
                    booking_id=form.cleaned_data["booking"].id,
                    actor=request.user,
                    number=form.cleaned_data["number"],
                    actual_start=form.cleaned_data["actual_start"],
                    actual_end=form.cleaned_data["actual_end"],
                    break_minutes=form.cleaned_data["break_minutes"],
                    source_document=form.cleaned_data["source_document"],
                )
            except ValidationError as exc:
                form.add_error(None, "; ".join(exc.messages))
            else:
                messages.success(
                    request,
                    f"Timesheet {timesheet.number} captured and submitted for approval.",
                )
                return redirect("admin:bookings_timesheet_changelist")
        context = {
            **self.admin_site.each_context(request),
            "title": "Capture completed-shift timesheet",
            "opts": self.model._meta,
            "form": form,
        }
        return TemplateResponse(
            request,
            "admin/bookings/timesheet/capture.html",
            context,
        )

    def _timesheet_or_deny(self, request, object_id):
        timesheet = self.get_queryset(request).filter(pk=object_id).first()
        if timesheet is None:
            raise PermissionDenied
        return timesheet

    def _operation_response(self, request, timesheet, form, title, submit_label):
        return TemplateResponse(
            request,
            "admin/bookings/timesheet/operation_form.html",
            {
                **self.admin_site.each_context(request),
                "title": title,
                "submit_label": submit_label,
                "opts": self.model._meta,
                "timesheet": timesheet,
                "form": form,
            },
        )

    def decline_view(self, request, object_id):
        if not _has_legacy_operation(
            request.user, "approve_ts", "bookings.approve_timesheet"
        ):
            raise PermissionDenied
        timesheet = self._timesheet_or_deny(request, object_id)
        form = TimesheetDeclineAdminForm(request.POST or None)
        if request.method == "POST" and form.is_valid():
            try:
                decline_timesheet(
                    timesheet_id=timesheet.id,
                    actor=request.user,
                    reason=form.cleaned_data["reason"],
                )
            except ValidationError as exc:
                form.add_error(None, "; ".join(exc.messages))
            else:
                messages.success(request, f"Timesheet {timesheet.number} declined.")
                return redirect("admin:bookings_timesheet_change", timesheet.id)
        return self._operation_response(
            request,
            timesheet,
            form,
            "Decline timesheet",
            "Decline and return for correction",
        )

    def replace_view(self, request, object_id):
        can_link = _has_legacy_operation(
            request.user, "link_ts", "bookings.link_timesheet_document"
        ) or _has_legacy_operation(
            request.user, "cap_ts", "bookings.capture_timesheet"
        )
        if not can_link:
            raise PermissionDenied
        timesheet = self._timesheet_or_deny(request, object_id)
        form = TimesheetDocumentAdminForm(request.POST or None, request.FILES or None)
        if request.method == "POST" and form.is_valid():
            try:
                replace_and_resubmit_timesheet(
                    timesheet_id=timesheet.id,
                    actor=request.user,
                    source_document=form.cleaned_data["document"],
                )
            except ValidationError as exc:
                form.add_error(None, "; ".join(exc.messages))
            else:
                messages.success(
                    request,
                    f"Replacement linked and timesheet {timesheet.number} resubmitted.",
                )
                return redirect("admin:bookings_timesheet_change", timesheet.id)
        return self._operation_response(
            request,
            timesheet,
            form,
            "Replace signed document",
            "Upload replacement and resubmit",
        )

    def void_view(self, request, object_id):
        if not _has_legacy_operation(
            request.user, "approve_ts", "bookings.approve_timesheet"
        ):
            raise PermissionDenied
        timesheet = self._timesheet_or_deny(request, object_id)
        form = TimesheetDeclineAdminForm(request.POST or None)
        if request.method == "POST" and form.is_valid():
            try:
                void_timesheet(
                    timesheet_id=timesheet.id,
                    actor=request.user,
                    reason=form.cleaned_data["reason"],
                )
            except ValidationError as exc:
                form.add_error(None, "; ".join(exc.messages))
            else:
                messages.success(
                    request,
                    f"Timesheet {timesheet.number} voided and retained for audit.",
                )
                return redirect("admin:bookings_timesheet_change", timesheet.id)
        return self._operation_response(
            request,
            timesheet,
            form,
            "Void duplicate/unusable timesheet",
            "Void and retain for audit",
        )

    def confirmation_view(self, request, object_id):
        if not _has_legacy_operation(
            request.user, "link_conf", "bookings.link_client_confirmation"
        ):
            raise PermissionDenied
        timesheet = self._timesheet_or_deny(request, object_id)
        form = TimesheetDocumentAdminForm(request.POST or None, request.FILES or None)
        if request.method == "POST" and form.is_valid():
            try:
                upload_client_confirmation(
                    timesheet_id=timesheet.id,
                    actor=request.user,
                    document=form.cleaned_data["document"],
                )
            except ValidationError as exc:
                form.add_error(None, "; ".join(exc.messages))
            else:
                messages.success(
                    request,
                    f"Client confirmation linked to {timesheet.number}.",
                )
                return redirect("admin:bookings_timesheet_change", timesheet.id)
        return self._operation_response(
            request,
            timesheet,
            form,
            "Upload Client confirmation",
            "Upload confirmation",
        )

    def document_download_view(self, request, object_id, document_id):
        if not self.has_view_permission(request):
            raise PermissionDenied
        timesheet = self._timesheet_or_deny(request, object_id)
        document = timesheet.documents.filter(pk=document_id).first()
        if document is None:
            raise PermissionDenied
        return FileResponse(
            document.file.open("rb"),
            as_attachment=True,
            filename=document.original_name,
            content_type=document.content_type,
        )

    @admin.action(description="Approve selected submitted timesheets")
    def approve_selected_timesheets(self, request, queryset):
        if not _has_legacy_operation(
            request.user, "approve_ts", "bookings.approve_timesheet"
        ):
            raise PermissionDenied
        completed = 0
        for timesheet_id in queryset.order_by("pk").values_list("pk", flat=True):
            try:
                approve_timesheet(timesheet_id=timesheet_id, actor=request.user)
            except ValidationError as exc:
                self.message_user(request, "; ".join(exc.messages), level=messages.ERROR)
            else:
                completed += 1
        if completed:
            self.message_user(request, f"{completed} timesheet(s) approved.")

    @admin.action(description="Stage selected approved timesheets for payroll")
    def stage_selected_timesheets_for_payroll(self, request, queryset):
        if not _has_legacy_operation(
            request.user, "export_ts", "bookings.export_payroll"
        ):
            raise PermissionDenied
        completed = 0
        for timesheet_id in queryset.order_by("pk").values_list("pk", flat=True):
            try:
                stage_timesheet_for_payroll(
                    timesheet_id=timesheet_id,
                    actor=request.user,
                )
            except ValidationError as exc:
                self.message_user(request, "; ".join(exc.messages), level=messages.ERROR)
            else:
                completed += 1
        if completed:
            self.message_user(
                request,
                f"{completed} timesheet(s) staged for payroll.",
            )

    @admin.action(description="Generate payroll file for selected approved timesheets")
    def generate_payroll_for_selected_timesheets(self, request, queryset):
        if not _has_legacy_operation(
            request.user, "export_ts", "bookings.export_payroll"
        ):
            raise PermissionDenied
        process_code = timezone.localtime().strftime("%Y-W%V-%H%M%S")
        try:
            batch = generate_payroll_export(
                timesheet_ids=list(queryset.values_list("pk", flat=True)),
                actor=request.user,
                process_code=process_code,
            )
        except ValidationError as exc:
            self.message_user(request, "; ".join(exc.messages), level=messages.ERROR)
        else:
            self.message_user(
                request,
                f"Payroll batch {batch.process_code} generated. "
                "Download it from Finance export batches.",
            )

    @admin.action(description="Generate invoice for selected payroll-exported timesheets")
    def generate_invoices_for_selected_timesheets(self, request, queryset):
        if not _has_legacy_operation(
            request.user, "export_inv", "bookings.generate_invoice"
        ):
            raise PermissionDenied
        grouped_ids = {}
        for row in queryset.values("pk", "booking__shift__site__client_id"):
            grouped_ids.setdefault(row["booking__shift__site__client_id"], []).append(
                row["pk"]
            )
        created = []
        for timesheet_ids in grouped_ids.values():
            try:
                created.append(generate_invoice(
                    timesheet_ids=timesheet_ids,
                    actor=request.user,
                    invoice_date=timezone.localdate(),
                ))
            except ValidationError as exc:
                self.message_user(request, "; ".join(exc.messages), level=messages.ERROR)
        if created:
            self.message_user(
                request,
                f"{len(created)} invoice(s) generated: "
                + ", ".join(invoice.number for invoice in created),
            )


@admin.register(TimesheetLine)
class TimesheetLineAdmin(ImmutableFinanceAdminMixin, admin.ModelAdmin):
    list_display = [
        "timesheet",
        "actual_start",
        "actual_end",
        "break_minutes",
        "rate_category",
        "pay_rate",
        "bill_rate",
    ]
    readonly_fields = [field.name for field in TimesheetLine._meta.fields]

    def has_view_permission(self, request, obj=None):
        return super().has_view_permission(request, obj) and (
            user_can_view_candidate_pay_rates(request.user)
            or user_can_view_client_charge_rates(request.user)
        )

    def get_list_display(self, request):
        fields = list(super().get_list_display(request))
        if not user_can_view_candidate_pay_rates(request.user):
            fields.remove("pay_rate")
        if not user_can_view_client_charge_rates(request.user):
            fields.remove("bill_rate")
        return fields

    def get_fields(self, request, obj=None):
        fields = list(super().get_fields(request, obj))
        if not user_can_view_candidate_pay_rates(request.user):
            fields.remove("pay_rate")
        if not user_can_view_client_charge_rates(request.user):
            fields.remove("bill_rate")
        return fields

    def get_queryset(self, request):
        return scope_queryset_to_user_departments(
            super().get_queryset(request),
            request.user,
            lookup="timesheet__booking__shift__site__client__departments",
        )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(TimesheetDocument)
class TimesheetDocumentAdmin(ImmutableFinanceAdminMixin, admin.ModelAdmin):
    list_display = ["timesheet", "kind", "original_name", "uploaded_by", "uploaded_at", "is_current"]
    exclude = ["file"]
    readonly_fields = [
        field.name for field in TimesheetDocument._meta.fields if field.name != "file"
    ] + ["secure_download"]

    def get_queryset(self, request):
        return scope_queryset_to_user_departments(
            super().get_queryset(request),
            request.user,
            lookup="timesheet__booking__shift__site__client__departments",
        )

    @admin.display(description="Document")
    def secure_download(self, obj):
        if not obj or not obj.file:
            return "—"
        url = reverse(
            "admin:bookings_timesheet_document_download",
            args=[obj.timesheet_id, obj.id],
        )
        return format_html('<a href="{}">Download {}</a>', url, obj.original_name)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(TimesheetEvent)
class TimesheetEventAdmin(ImmutableFinanceAdminMixin, admin.ModelAdmin):
    list_display = ["timesheet", "action", "actor", "from_status", "to_status", "created_at"]
    readonly_fields = [field.name for field in TimesheetEvent._meta.fields]

    def get_queryset(self, request):
        return scope_queryset_to_user_departments(
            super().get_queryset(request),
            request.user,
            lookup="timesheet__booking__shift__site__client__departments",
        )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(FinanceSettings)
class FinanceSettingsAdmin(admin.ModelAdmin):
    list_display = [
        "invoice_issuer_legal_name",
        "invoice_issuer_vat_number",
        "vat_percent",
        "sales_contra_account",
        "updated_at",
    ]

    def has_add_permission(self, request):
        return request.user.is_superuser and not FinanceSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Invoice)
class InvoiceAdmin(ImmutableFinanceAdminMixin, admin.ModelAdmin):
    list_display = [
        "number",
        "invoice_date",
        "client_name",
        "accounting_code",
        "subtotal",
        "vat_amount",
        "total",
        "pastel_exported_at",
    ]
    list_filter = ["invoice_date", "client"]
    search_fields = ["number", "client_name", "accounting_code"]
    exclude = ["document"]
    readonly_fields = [
        field.name for field in Invoice._meta.fields if field.name != "document"
    ] + ["document_download"]
    actions = ["generate_pastel_for_selected_invoices"]

    def get_queryset(self, request):
        return scope_queryset_to_user_departments(
            super().get_queryset(request),
            request.user,
            lookup="client__departments",
        )

    def has_add_permission(self, request):
        return False

    def has_view_permission(self, request, obj=None):
        return (
            super().has_view_permission(request, obj)
            and user_can_view_client_charge_rates(request.user)
        )

    def has_change_permission(self, request, obj=None):
        return (
            user_can_view_client_charge_rates(request.user)
            and _has_legacy_operation(
                request.user, "export_inv", "bookings.export_accounting"
            )
        )

    @admin.display(description="Invoice document")
    def document_download(self, obj):
        if not obj or not obj.document:
            return "—"
        url = reverse("admin:bookings_invoice_document", args=[obj.id])
        return format_html('<a href="{}">Download invoice PDF</a>', url)

    def get_urls(self):
        return [
            path(
                "<int:object_id>/document/",
                self.admin_site.admin_view(self.document_view),
                name="bookings_invoice_document",
            ),
        ] + super().get_urls()

    def document_view(self, request, object_id):
        if not (
            user_can_view_client_charge_rates(request.user)
            and _has_legacy_operation(
                request.user, "export_inv", "bookings.export_accounting"
            )
        ):
            raise PermissionDenied
        invoice = self.get_queryset(request).filter(pk=object_id).first()
        if invoice is None or not invoice.document:
            raise PermissionDenied
        return FileResponse(
            invoice.document.open("rb"),
            as_attachment=True,
            filename=f"{invoice.number}.pdf",
            content_type="application/pdf",
        )

    @admin.action(description="Generate Pastel sales CSV for selected invoices")
    def generate_pastel_for_selected_invoices(self, request, queryset):
        if not (
            user_can_view_client_charge_rates(request.user)
            and _has_legacy_operation(
                request.user, "export_inv", "bookings.export_accounting"
            )
        ):
            raise PermissionDenied
        try:
            batch = generate_pastel_export(
                invoice_ids=list(queryset.values_list("pk", flat=True)),
                actor=request.user,
            )
        except ValidationError as exc:
            self.message_user(request, "; ".join(exc.messages), level=messages.ERROR)
        else:
            self.message_user(
                request,
                f"Pastel batch {batch.process_code} generated. "
                "Download it from Finance export batches.",
            )


@admin.register(InvoiceLine)
class InvoiceLineAdmin(ImmutableFinanceAdminMixin, admin.ModelAdmin):
    list_display = [
        "invoice",
        "timesheet_number",
        "candidate_name",
        "worked_hours",
        "bill_rate",
        "amount",
    ]
    readonly_fields = [field.name for field in InvoiceLine._meta.fields]

    def has_view_permission(self, request, obj=None):
        return (
            super().has_view_permission(request, obj)
            and user_can_view_client_charge_rates(request.user)
        )

    def get_queryset(self, request):
        return scope_queryset_to_user_departments(
            super().get_queryset(request),
            request.user,
            lookup="invoice__client__departments",
        )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(SmsMessage)
class SmsMessageAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "booking",
        "candidate",
        "status",
        "attempt_count",
        "requested_by",
        "requested_at",
        "accepted_at",
    ]
    list_filter = ["status", "requested_at", "accepted_at"]
    search_fields = ["customer_id", "provider_event_id"]
    readonly_fields = [field.name for field in SmsMessage._meta.fields]

    def get_queryset(self, request):
        return scope_queryset_to_user_departments(
            super().get_queryset(request),
            request.user,
            lookup="booking__shift__site__client__departments",
        )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(FinanceExportBatch)
class FinanceExportBatchAdmin(ImmutableFinanceAdminMixin, admin.ModelAdmin):
    list_display = [
        "kind",
        "process_code",
        "status",
        "file_name",
        "generated_by",
        "generated_at",
        "upload_confirmed_at",
    ]
    list_filter = ["kind", "status", "generated_at"]
    search_fields = ["process_code", "file_name", "sha256"]
    exclude = ["content"]
    readonly_fields = [
        "kind",
        "status",
        "process_code",
        "file_name",
        "sha256",
        "timesheets",
        "invoices",
        "generated_by",
        "generated_at",
        "upload_confirmed_by",
        "upload_confirmed_at",
    ]
    actions = ["confirm_external_upload"]

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        can_payroll = _has_legacy_operation(
            request.user, "export_ts", "bookings.export_payroll"
        )
        can_accounting = _has_legacy_operation(
            request.user, "export_inv", "bookings.export_accounting"
        )
        if not can_payroll and not can_accounting:
            return queryset.none()
        if not request.user.is_superuser and not (can_payroll and can_accounting):
            if can_payroll:
                queryset = queryset.filter(kind=FinanceExportBatch.Kind.PAYROLL)
            else:
                queryset = queryset.filter(
                    kind__in=[
                        FinanceExportBatch.Kind.PASTEL_SALES,
                        FinanceExportBatch.Kind.PASTEL_CREDIT,
                    ]
                )
        department_ids = user_department_ids(request.user)
        if department_ids is None:
            return queryset
        if not department_ids:
            return queryset.none()
        return queryset.filter(
            Q(timesheets__booking__shift__site__client__departments__id__in=department_ids)
            | Q(invoices__client__departments__id__in=department_ids)
        ).distinct()

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser or any([
            _has_legacy_operation(
                request.user, "export_ts", "bookings.export_payroll"
            ),
            _has_legacy_operation(
                request.user, "export_inv", "bookings.export_accounting"
            ),
        ])

    def get_urls(self):
        return [
            path(
                "<int:object_id>/download/",
                self.admin_site.admin_view(self.download_view),
                name="bookings_financeexportbatch_download",
            ),
        ] + super().get_urls()

    def download_view(self, request, object_id):
        batch = self.get_queryset(request).filter(pk=object_id).first()
        if batch is None:
            raise PermissionDenied
        content_type = "text/csv" if batch.kind.startswith("pastel") else "text/plain"
        response = HttpResponse(batch.content, content_type=f"{content_type}; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{batch.file_name}"'
        return response

    @admin.action(description="Confirm selected files were uploaded to the external system")
    def confirm_external_upload(self, request, queryset):
        if not self.has_change_permission(request):
            raise PermissionDenied
        try:
            updated = confirm_export_upload(
                batch_ids=list(queryset.values_list("pk", flat=True)),
                actor=request.user,
            )
        except ValidationError as exc:
            self.message_user(request, "; ".join(exc.messages), level=messages.ERROR)
        else:
            self.message_user(
                request,
                f"External upload confirmed for {updated} batch(es).",
            )


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ["candidate", "shift", "status", "created_at"]
    list_filter = ["status"]
    search_fields = ["candidate__first_name", "candidate__last_name"]
