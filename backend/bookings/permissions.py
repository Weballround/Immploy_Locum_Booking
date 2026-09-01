from rest_framework.permissions import BasePermission, SAFE_METHODS

from bookings.models import LegacyUserProfile


def user_can_manage_bookings(user):
    if not user or not user.is_authenticated or not user.is_staff:
        return False
    try:
        profile = user.legacy_profile
    except LegacyUserProfile.DoesNotExist:
        return user.has_perm("bookings.manage_bookings")
    if profile.booking_access_override is not None:
        return profile.booking_access_override
    return profile.link_conf


def user_can_manage_candidates(user):
    if not user or not user.is_authenticated or not user.is_staff:
        return False
    try:
        profile = user.legacy_profile
    except LegacyUserProfile.DoesNotExist:
        return user.has_perm("bookings.manage_bookings")
    if profile.candidate_access_override is not None:
        return profile.candidate_access_override
    return profile.edit_cand


def user_can_view_candidate_pay_rates(user):
    if not user or not user.is_authenticated or not user.is_staff:
        return False
    if user.has_perm("bookings.view_candidate_pay_rates"):
        return True
    try:
        profile = user.legacy_profile
    except LegacyUserProfile.DoesNotExist:
        return False
    return bool(profile.update_cand_rates or profile.override_can_rates)


def user_can_view_client_charge_rates(user):
    if not user or not user.is_authenticated or not user.is_staff:
        return False
    if user.has_perm("bookings.view_client_charge_rates"):
        return True
    try:
        profile = user.legacy_profile
    except LegacyUserProfile.DoesNotExist:
        return False
    return bool(profile.update_client_rates or profile.view_profit_report)


def user_can_override_approved_rates(user):
    if not user or not user.is_authenticated or not user.is_staff:
        return False
    if user.has_perm("bookings.override_approved_rates"):
        return True
    try:
        profile = user.legacy_profile
    except LegacyUserProfile.DoesNotExist:
        return False
    return bool(profile.override_can_rates)


class CanManageBookings(BasePermission):
    message = "Your access rules do not allow this scheduling change."

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated or not user.is_staff:
            return False
        is_candidate_endpoint = getattr(view, "basename", None) == "candidate"
        if is_candidate_endpoint:
            action = getattr(view, "action", None)
            is_scheduling_read = (
                action == "compatible_shifts"
                or (action == "list" and "site" in request.query_params)
            )
            if is_scheduling_read:
                return user_can_manage_bookings(user)
            if request.method in SAFE_METHODS:
                return user_can_manage_bookings(user) or user_can_manage_candidates(user)
            return user_can_manage_candidates(user)
        return user_can_manage_bookings(user)
