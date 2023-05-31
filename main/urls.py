from django.urls import path
from . import views

urlpatterns = [
    path('', views.PlayerListView.as_view(), name='home'),
    # path('<int:pk>/', player_detail, name='player_detail'),
    path('player', views.PlayerListView.as_view(), name='players'),
    path('player/<int:pk>/', views.PlayerDetailView.as_view(), name='player_detail'),
    path('tournaments', views.TournamentListView.as_view(), name='tournaments'),
    path('tournaments/<int:pk>', views.TournamentDetailView.as_view(), name='tournament_details'),
    path('regions', views.PlayerListView.as_view(), name='regions'),
    path('tournament_form', views.put_tournament, name='tournament_form'),
    path('pr_form', views.process_pr_csv, name='pr_form'),
    path('pr_season_form', views.create_pr_season, name='pr_season_from'),
    path('pr_season/<int:pk>', views.PrSeasonDetailView.as_view(), name='pr_season_details')
]
