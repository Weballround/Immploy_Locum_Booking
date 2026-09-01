from django.db import migrations, models
import django.core.validators


def create_booking_rule(apps, schema_editor):
    booking_rule = apps.get_model("bookings", "BookingRule")
    booking_rule.objects.get_or_create(pk=1)


class Migration(migrations.Migration):
    dependencies = [
        ("bookings", "0023_normalize_kwazulu_natal_candidate_regions"),
    ]

    operations = [
        migrations.AddField(
            model_name="clientprofessionrate",
            name="locally_managed",
            field=models.BooleanField(default=False),
        ),
        migrations.CreateModel(
            name="BookingRule",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "prevent_candidate_overlap",
                    models.BooleanField(
                        default=True,
                        editable=False,
                        help_text=(
                            "Mandatory: a Candidate cannot hold overlapping confirmed "
                            "bookings, including at different Clients, facilities or locations."
                        ),
                    ),
                ),
                (
                    "minimum_rest_minutes",
                    models.PositiveIntegerField(
                        default=0,
                        help_text=(
                            "Minimum time required between a Candidate's confirmed bookings. "
                            "Use 0 to allow back-to-back shifts."
                        ),
                        validators=[django.core.validators.MaxValueValidator(1440)],
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Booking rule",
                "verbose_name_plural": "Booking rules",
            },
        ),
        migrations.RunPython(create_booking_rule, migrations.RunPython.noop),
    ]
