from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("bookings", "0017_legacysyncrun"),
    ]

    operations = [
        migrations.CreateModel(
            name="Department",
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
                ("legacy_mysql_id", models.PositiveIntegerField(unique=True)),
                ("name", models.CharField(max_length=120)),
                ("is_active", models.BooleanField(default=True)),
            ],
            options={
                "ordering": ["legacy_mysql_id"],
            },
        ),
    ]
