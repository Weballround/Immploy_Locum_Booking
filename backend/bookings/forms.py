from django import forms

from bookings.models import Booking, LegacyUserProfile


class LegacyUserAccessAdminForm(forms.ModelForm):
    class Meta:
        model = LegacyUserProfile
        fields = [
            "booking_access_override",
            "candidate_access_override",
            "all_booking_departments",
            "booking_departments",
        ]

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("all_booking_departments") and cleaned.get("booking_departments"):
            raise forms.ValidationError(
                "Choose either all Booking departments or specific Booking departments, not both."
            )
        return cleaned


class RateExcelImportForm(forms.Form):
    file = forms.FileField(
        label="Excel workbook",
        help_text="Upload the downloaded .xlsx rate workbook (maximum 5 MB).",
    )

    def clean_file(self):
        uploaded = self.cleaned_data["file"]
        if not uploaded.name.lower().endswith(".xlsx"):
            raise forms.ValidationError("Upload an Excel .xlsx workbook.")
        if uploaded.size > 5 * 1024 * 1024:
            raise forms.ValidationError("The Excel workbook must be 5 MB or smaller.")
        return uploaded


class TimesheetCaptureAdminForm(forms.Form):
    booking = forms.ModelChoiceField(queryset=Booking.objects.none())
    number = forms.CharField(max_length=80, label="Timesheet number")
    actual_start = forms.DateTimeField(
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"})
    )
    actual_end = forms.DateTimeField(
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"})
    )
    break_minutes = forms.IntegerField(min_value=0, initial=0)
    source_document = forms.FileField(
        help_text="Signed PDF, JPG, JPEG or PNG; maximum 10 MB."
    )

    def __init__(self, *args, booking_queryset, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["booking"].queryset = booking_queryset


class TimesheetDeclineAdminForm(forms.Form):
    reason = forms.CharField(
        min_length=3,
        max_length=1000,
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text="Give the actionable reason the capturer must correct.",
    )


class TimesheetDocumentAdminForm(forms.Form):
    document = forms.FileField(
        help_text="PDF, JPG, JPEG or PNG; maximum 10 MB."
    )
