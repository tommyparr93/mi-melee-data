from django.urls import path
from . import views
from .views import PrEligiblePlayerListView, PRSeasonListView, PRSeasonCreateView, PRSeasonAdminDetailView, HomeView

urlpatterns = [
    path('', HomeView.as_view(), name='home'),
    path('search/', views.GlobalSearchView.as_view(), name='global_search'),
    # path('<int:pk>/', player_detail, name='player_detail'),
    path('player', views.PlayerListView.as_view(), name='players'),
    path('player/<int:pk>/', views.PlayerDetailView.as_view(), name='player_detail'),
    path('tournaments', views.TournamentListView.as_view(), name='tournaments'),
    path('tournaments/<int:pk>', views.TournamentDetailView.as_view(), name='tournament_details'),
    path('regions', views.PlayerListView.as_view(), name='regions'),
    path('tournament_form', views.put_tournament, name='tournament_form'),
    path('pr_season/<int:pk>', views.PrSeasonDetailView.as_view(), name='pr_season_details'),
    path('join_duplicate', views.join_duplicate, name='join_duplicate'),
    path('pr-eligible-players/', PrEligiblePlayerListView.as_view(), name='pr_eligible_players'),
    path('pr-table/', views.pr_table, name='pr_table'),
    path('seasons/', PRSeasonListView.as_view(), name='pr_season_list'),
    path('seasons/add/', PRSeasonCreateView.as_view(), name='pr_season_create'),
    path('seasons/manage/<int:pk>/', PRSeasonAdminDetailView.as_view(), name='pr_season_admin_detail'),
    path('seasons/manage/<int:season_id>/add-player/', views.add_player_to_season, name='add_player_to_season'),

]
