import pytest
from django.contrib import admin
from django.core.exceptions import ValidationError

from bookings.models import (
    Candidate,
    CandidateWardMembership,
    Client,
    Department,
    Region,
    RegionalClient,
    RegionalDesk,
    RegionalFacility,
    Site,
    Ward,
)


@pytest.mark.django_db
def test_regional_hierarchy_follows_the_approved_structure():
    region = Region.objects.get(code="WC")
    desk = Department.objects.create(legacy_mysql_id=3, name="Nursing")
    regional_desk = RegionalDesk.objects.create(region=region, department=desk)
    client = Client.objects.create(name="Mediclinic")
    regional_client = RegionalClient.objects.create(
        regional_desk=regional_desk,
        client=client,
    )
    facility = Site.objects.create(client=client, name="George")
    regional_facility = RegionalFacility.objects.create(
        regional_client=regional_client,
        site=facility,
    )
    ward = Ward.objects.create(regional_facility=regional_facility, name="ICU")
    candidate = Candidate.objects.create(first_name="Hierarchy", last_name="Candidate")
    membership = CandidateWardMembership.objects.create(
        ward=ward,
        candidate=candidate,
    )

    assert membership.ward.regional_facility.regional_client.client == client
    assert membership.ward.regional_facility.site == facility
    assert membership.ward.regional_facility.regional_client.regional_desk == regional_desk
    assert membership.ward.regional_facility.regional_client.regional_desk.region == region


@pytest.mark.django_db
def test_regional_facility_rejects_a_site_from_another_client():
    region = Region.objects.get(code="WC")
    desk = Department.objects.create(legacy_mysql_id=3, name="Nursing")
    regional_desk = RegionalDesk.objects.create(region=region, department=desk)
    regional_client = RegionalClient.objects.create(
        regional_desk=regional_desk,
        client=Client.objects.create(name="Expected client"),
    )
    other_site = Site.objects.create(
        client=Client.objects.create(name="Other client"),
        name="Other facility",
    )

    with pytest.raises(ValidationError, match="same Client"):
        RegionalFacility.objects.create(
            regional_client=regional_client,
            site=other_site,
        )


@pytest.mark.django_db
def test_regional_facility_bulk_create_cannot_bypass_client_integrity():
    region = Region.objects.get(code="WC")
    desk = Department.objects.create(legacy_mysql_id=3, name="Nursing")
    regional_desk = RegionalDesk.objects.create(region=region, department=desk)
    regional_client = RegionalClient.objects.create(
        regional_desk=regional_desk,
        client=Client.objects.create(name="Expected bulk client"),
    )
    other_site = Site.objects.create(
        client=Client.objects.create(name="Other bulk client"),
        name="Other bulk facility",
    )

    with pytest.raises(ValidationError, match="same Client"):
        RegionalFacility.objects.bulk_create([
            RegionalFacility(regional_client=regional_client, site=other_site)
        ])

    assert RegionalFacility.objects.count() == 0


@pytest.mark.django_db
def test_regional_facility_queryset_cannot_move_scope_without_validation():
    region = Region.objects.get(code="WC")
    desk = Department.objects.create(legacy_mysql_id=3, name="Nursing")
    regional_desk = RegionalDesk.objects.create(region=region, department=desk)
    client = Client.objects.create(name="Original client")
    regional_client = RegionalClient.objects.create(
        regional_desk=regional_desk,
        client=client,
    )
    site = Site.objects.create(client=client, name="Original facility")
    regional_facility = RegionalFacility.objects.create(
        regional_client=regional_client,
        site=site,
    )
    other_site = Site.objects.create(
        client=Client.objects.create(name="Update bypass client"),
        name="Update bypass facility",
    )

    with pytest.raises(ValueError, match="save"):
        RegionalFacility.objects.filter(pk=regional_facility.pk).update(
            site=other_site
        )

    regional_facility.refresh_from_db()
    assert regional_facility.site == site


@pytest.mark.django_db
def test_candidate_can_belong_to_multiple_wards_without_duplicate_identity():
    region = Region.objects.get(code="WC")
    desk = Department.objects.create(legacy_mysql_id=3, name="Nursing")
    regional_desk = RegionalDesk.objects.create(region=region, department=desk)
    client = Client.objects.create(name="Regional client")
    regional_client = RegionalClient.objects.create(
        regional_desk=regional_desk,
        client=client,
    )
    site = Site.objects.create(client=client, name="Regional facility")
    regional_facility = RegionalFacility.objects.create(
        regional_client=regional_client,
        site=site,
    )
    icu = Ward.objects.create(regional_facility=regional_facility, name="ICU")
    theatre = Ward.objects.create(
        regional_facility=regional_facility,
        name="Theatre",
    )
    candidate = Candidate.objects.create(first_name="One", last_name="Person")

    CandidateWardMembership.objects.create(ward=icu, candidate=candidate)
    CandidateWardMembership.objects.create(ward=theatre, candidate=candidate)

    assert candidate.ward_memberships.count() == 2
    assert Candidate.objects.filter(pk=candidate.pk).count() == 1


@pytest.mark.django_db
def test_all_regions_from_the_approved_hierarchy_are_seeded():
    assert set(Region.objects.values_list("code", "name")) == {
        ("WC", "Western Cape"),
        ("NC", "Northern Cape"),
        ("NW", "North West"),
        ("FS", "Free State"),
        ("GAU", "Gauteng"),
        ("EC", "Eastern Cape"),
        ("KZN", "KwaZulu-Natal"),
        ("MPUM", "Mpumalanga"),
        ("LIMPOPO", "Limpopo"),
    }


def test_hierarchy_entities_are_managed_through_django_admin():
    assert {
        Region,
        RegionalDesk,
        RegionalClient,
        RegionalFacility,
        Ward,
        CandidateWardMembership,
    }.issubset(admin.site._registry)
