from bookings.models import Department, LegacyUserProfile


def user_department_ids(user):
    """Return None for all-desk administrators, otherwise permitted Department PKs."""
    if not user or not user.is_authenticated or not user.is_staff:
        return ()
    if user.is_superuser:
        return None
    try:
        profile = user.legacy_profile
    except LegacyUserProfile.DoesNotExist:
        # Locally permissioned Django staff are administration identities rather
        # than imported desk users and retain all-desk visibility.
        return None
    if profile.man_users or profile.all_booking_departments:
        return None
    override_ids = tuple(
        profile.booking_departments.filter(is_active=True).values_list("id", flat=True)
    )
    if override_ids:
        return override_ids
    if not profile.assigned_desk:
        return ()
    return tuple(Department.objects.filter(
        legacy_mysql_id=profile.assigned_desk,
        is_active=True,
    ).values_list("id", flat=True))


def scope_queryset_to_user_departments(queryset, user, lookup="departments"):
    department_ids = user_department_ids(user)
    if department_ids is None:
        return queryset
    if not department_ids:
        return queryset.none()
    return queryset.filter(**{f"{lookup}__id__in": department_ids}).distinct()


def user_can_access_departments(user, department_manager):
    department_ids = user_department_ids(user)
    if department_ids is None:
        return True
    if not department_ids:
        return False
    return department_manager.filter(id__in=department_ids).exists()
