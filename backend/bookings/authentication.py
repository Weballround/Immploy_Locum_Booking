from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class CaseInsensitiveModelBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        user_model = get_user_model()
        username = username or kwargs.get(user_model.USERNAME_FIELD)
        if not isinstance(username, str) or not isinstance(password, str):
            return None
        try:
            user = user_model._default_manager.get(
                **{f"{user_model.USERNAME_FIELD}__iexact": username}
            )
        except (user_model.DoesNotExist, user_model.MultipleObjectsReturned):
            user_model().set_password(password)
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
