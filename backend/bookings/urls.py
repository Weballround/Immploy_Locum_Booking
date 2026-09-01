from rest_framework.routers import DefaultRouter

from bookings.views import BookingViewSet, CandidateViewSet, ShiftViewSet, VacancyViewSet

router = DefaultRouter()
router.register("bookings", BookingViewSet, basename="booking")
router.register("candidates", CandidateViewSet, basename="candidate")
router.register("shifts", ShiftViewSet, basename="shift")
router.register("vacancies", VacancyViewSet, basename="vacancy")

urlpatterns = router.urls
