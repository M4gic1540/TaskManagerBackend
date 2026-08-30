from django.urls import path
from rest_framework_simplejwt.views import TokenBlacklistView, TokenRefreshView

from accounts.api.views import (
    CustomTokenObtainPairView,
    GoogleAuthMintView,
    MeView,
    TechnicianDeactivateView,
    TechnicianListCreateView,
    UserRoleChangeView,
)

urlpatterns = [
    path("auth/login/", CustomTokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("auth/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("auth/logout/", TokenBlacklistView.as_view(), name="token_blacklist"),
    path("auth/google-mint/", GoogleAuthMintView.as_view(), name="google-mint"),
    path("me/", MeView.as_view(), name="me"),
    path("technicians/", TechnicianListCreateView.as_view(), name="technician-list-create"),
    path("technicians/<int:user_id>/deactivate/", TechnicianDeactivateView.as_view(),
         name="technician-deactivate"),
    path("users/<int:user_id>/role/", UserRoleChangeView.as_view(), name="user-role-change"),
]
