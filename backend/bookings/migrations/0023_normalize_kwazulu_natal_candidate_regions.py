from django.db import migrations


def normalize_candidate_regions(apps, schema_editor):
    candidate_model = apps.get_model("bookings", "Candidate")
    for historical_spelling in ("Kwazulu Natal", "Kwazulu-Natal"):
        candidate_model.objects.filter(
            home_region__iexact=historical_spelling
        ).update(home_region="KwaZulu-Natal")


class Migration(migrations.Migration):
    dependencies = [
        ("bookings", "0022_candidate_assigned_consultant_and_more"),
    ]

    operations = [
        migrations.RunPython(normalize_candidate_regions, migrations.RunPython.noop),
    ]