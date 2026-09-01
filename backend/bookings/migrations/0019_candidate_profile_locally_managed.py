from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("bookings", "0018_department"),
    ]

    operations = [
        migrations.AddField(
            model_name="candidate",
            name="profile_locally_managed",
            field=models.BooleanField(default=False),
        ),
    ]
