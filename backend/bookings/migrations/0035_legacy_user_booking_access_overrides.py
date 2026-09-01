from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("bookings", "0034_smsmessage"),
    ]

    operations = [
        migrations.AddField(
            model_name="legacyuserprofile",
            name="all_booking_departments",
            field=models.BooleanField(
                default=False,
                help_text="Grant access to every active Booking department.",
            ),
        ),
        migrations.AddField(
            model_name="legacyuserprofile",
            name="booking_access_override",
            field=models.BooleanField(
                blank=True,
                default=None,
                help_text="Leave unknown to use the synchronized legacy booking rule.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="legacyuserprofile",
            name="booking_departments",
            field=models.ManyToManyField(
                blank=True,
                help_text=(
                    "Optional local Booking scope. When empty, the synchronized assigned "
                    "desk is used unless all departments is selected."
                ),
                related_name="user_access_overrides",
                to="bookings.department",
            ),
        ),
        migrations.AddField(
            model_name="legacyuserprofile",
            name="candidate_access_override",
            field=models.BooleanField(
                blank=True,
                default=None,
                help_text="Leave unknown to use the synchronized legacy Candidate rule.",
                null=True,
            ),
        ),
    ]