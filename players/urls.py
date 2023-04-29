from django.urls import path
from . import views

urlpatterns = [
    path('', views.PlayerListView.as_view(), name='players'),
]