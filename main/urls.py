from django.urls import path
from . import views

urlpatterns = [
    path('', views.PlayerListView.as_view(), name='players'),
    # path('<int:pk>/', player_detail, name='player_detail'),
    path('<int:pk>/', views.PlayerDetailView.as_view(), name='player_detail'),
    path('tournaments', views.PlayerListView.as_view(), name='tournaments'),
    path('regions', views.PlayerListView.as_view(), name='regions'),
]