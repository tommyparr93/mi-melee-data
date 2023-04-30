from django.urls import path
from . import views

urlpatterns = [
    path('', views.PlayerListView.as_view(), name='home'),
    # path('<int:pk>/', player_detail, name='player_detail'),
    path('player', views.PlayerListView.as_view(), name='players'),
    path('<int:pk>/', views.PlayerDetailView.as_view(), name='player_detail'),
    path('tournaments', views.TournamentListView.as_view(), name='tournaments'),
    path('tournaments/<int:pk>', views.TournamentDetailView.as_view(), name='tournament_details'),
    path('regions', views.PlayerListView.as_view(), name='regions'),
]