"""What the model is told about the `agent` views. Keep in sync with sql/agent_views.sql.

This sits in the cached system prompt because nearly every SQL question needs it.
Reading it from the cache costs less than an extra tool call per question.
"""

SCHEMA_GUIDE = """\
Database (PostgreSQL, read-only views), for when no other tool fits:

players(player_id, player, region, main_character, secondary_character, pr_eligible, pr_notable)
tournaments(tournament_id, tournament, date, year, city, state, in_michigan, venue_name, entrants, online)
sets(set_id, tournament_id, tournament, date, round, player1_id, player1, player2_id, player2, \
player1_score, player2_score, winner_id, winner, loser_id, loser, is_dq, pr_eligible)
player_sets(set_id, tournament_id, tournament, date, round, player_id, player, opponent_id, opponent, \
player_score, opponent_score, won, is_dq, pr_eligible)
placements(tournament_id, tournament, date, year, in_michigan, entrants, player_id, player, placement)
pr_seasons(season_id, season, start_date, end_date, is_active, ranked_players)
pr_rankings(season_id, season, start_date, end_date, player_id, player, rank, rank_label)

Notes:
- player_sets has each set twice, once from each player's side. Filter on player_id and count `won` \
for records. Use sets for per-set questions.
- Exclude DQs (NOT is_dq) when counting wins, losses or records with a query, unless asked otherwise.
- player_sets.pr_eligible describes the set, not the opponent. "Against PR-eligible players" also \
needs the opponent's players.pr_eligible, so prefer the PR head-to-head tool for that.
- Tags are not unique and some have a suffix like "Zain (#1, SSBMRank 2025)". Filter by player_id.
- Placement 1 is the winner. Ties share a number, so "top 8" is placement <= 8.
- pr_rankings.rank is NULL for honourable or intermediate mentions (see rank_label). A season with \
ranked_players = 0 has no published rankings.
- A PR season's events are those dated between its start_date and end_date.
- Select player_id whenever you name players, so you can link them. Results are capped, so aggregate \
and use ORDER BY with LIMIT.
- If a query fails, read the error, fix the query and try once more."""
