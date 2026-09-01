from bookings.models import Candidate, Client


def canonical_candidate_region(region):
    cleaned_region = " ".join((region or "").strip().split())
    normalized_key = " ".join(cleaned_region.replace("-", " ").split()).casefold()
    if normalized_key == "kwazulu natal":
        return "KwaZulu-Natal"
    return cleaned_region


def candidate_location_options(department_ids=None):
    locations_by_region = {}
    candidates = Candidate.objects.filter(is_active=True)
    clients = Client.objects.filter(is_active=True)
    if department_ids is not None:
        candidates = candidates.filter(departments__id__in=department_ids).distinct()
        clients = clients.filter(departments__id__in=department_ids).distinct()
    location_rows = list(
        candidates.values_list(
            "home_region", "home_area"
        ).order_by("home_region", "home_area")
    ) + list(
        clients.values_list(
            "region", "city"
        ).order_by("region", "city")
    )
    for raw_region, raw_area in location_rows:
        region = canonical_candidate_region(raw_region)
        area = raw_area.strip()
        if not region:
            continue
        region_entry = locations_by_region.setdefault(
            region.casefold(),
            {"region": region, "areas": {}},
        )
        if area:
            region_entry["areas"].setdefault(area.casefold(), area)
    return [
        {
            "region": entry["region"],
            "areas": sorted(entry["areas"].values(), key=str.casefold),
        }
        for entry in sorted(
            locations_by_region.values(),
            key=lambda item: item["region"].casefold(),
        )
    ]


def canonical_candidate_location(region, area):
    normalized_region = canonical_candidate_region(region).casefold()
    normalized_area = area.strip().casefold()
    for location in candidate_location_options():
        if location["region"].casefold() != normalized_region:
            continue
        for configured_area in location["areas"]:
            if configured_area.casefold() == normalized_area:
                return location["region"], configured_area
    return None
