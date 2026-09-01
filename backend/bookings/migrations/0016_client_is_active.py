from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("bookings", "0015_add_mfa_account_generation"),
    ]

    operations = [
        migrations.AddField(
            model_name="client",
            name="is_active",
            field=models.BooleanField(default=True),
        ),
    ]
