"""What the model is told about the `agent` views, plus worked example queries.

Keep this in sync with sql/agent_views.sql. Short, concrete rules beat long prose
for small models; every rule here exists because a model got it wrong without it.
"""

SCHEMA_GUIDE = """\
DATABASE (PostgreSQL, read-only). Query these views with run_sql:

players(player_id, player, region, main_character, secondary_character, pr_eligible, pr_notable)
  - `player` is the tag. Tags are not unique; some include a suffix like "Zain (#1, SSBMRank 2025)".
tournaments(tournament_id, tournament, date, year, city, state, in_michigan, venue_name, entrants, online)
  - state is a 2-letter code ('MI', 'OH', ...). in_michigan = (state = 'MI').
sets(set_id, tournament_id, tournament, date, round, player1_id, player1, player2_id, player2,
     player1_score, player2_score, winner_id, winner, loser_id, loser, is_dq, pr_eligible)
  - one row per set. Use for "who won the set" questions and tournament brackets.
player_sets(set_id, tournament_id, tournament, date, round, player_id, player, opponent_id, opponent,
            player_score, opponent_score, won, is_dq, pr_eligible)
  - EVERY SET APPEARS TWICE, once from each player's side. Use this for a player's wins, losses,
    records and head-to-heads: filter on player_id (or player) and count `won`.
placements(tournament_id, tournament, date, year, in_michigan, entrants, player_id, player, placement)
  - placement 1 = winner, 2 = runner-up. "Top 8" means placement <= 8 (ties share a number, e.g. 5, 7).
pr_seasons(season_id, season, start_date, end_date, is_active, ranked_players)
  - a season with ranked_players = 0 has no published rankings yet.
pr_rankings(season_id, season, start_date, end_date, player_id, player, rank, rank_label)
  - rank 1 is best. rank is NULL for honourable/intermediate mentions (rank_label 'HM'/'IM').

RULES
- Exclude DQs (is_dq = false) when counting wins, losses, records or head-to-heads.
- Head-to-heads match the website when you also filter pr_eligible = true; say which you used.
- Players are tags; match with ILIKE and check you got the right person. When a tag is ambiguous,
  prefer the player with the most sets, or show the candidates.
- "Michigan" events: in_michigan = true. Out-of-state: in_michigan = false.
- A PR season's events are the tournaments whose date is between the season's start_date and end_date.
- Only SELECT. Results are capped at 200 rows, so aggregate and use ORDER BY ... LIMIT.
- If a query errors, read the message, fix the query and try again.
"""

EXAMPLES = """\
EXAMPLE QUERIES

-- Zain's set record (no DQs)
SELECT count(*) FILTER (WHERE won) AS wins, count(*) FILTER (WHERE NOT won) AS losses
FROM player_sets WHERE player_id = 6126 AND NOT is_dq;

-- Head-to-head between two player ids, as the website counts it
SELECT player, count(*) FILTER (WHERE won) AS wins, count(*) FILTER (WHERE NOT won) AS losses
FROM player_sets
WHERE player_id = 6126 AND opponent_id = 1000 AND NOT is_dq AND pr_eligible
GROUP BY player;

-- Most Michigan tournament wins in 2025
SELECT player, count(*) AS wins FROM placements
WHERE placement = 1 AND in_michigan AND year = 2025
GROUP BY player ORDER BY wins DESC LIMIT 10;

-- Latest PR season that has rankings, top 5
SELECT season, rank, player FROM pr_rankings
WHERE season_id = (SELECT season_id FROM pr_seasons WHERE ranked_players > 0
                   ORDER BY start_date DESC LIMIT 1)
  AND rank IS NOT NULL
ORDER BY rank LIMIT 5;

-- Biggest Michigan events of 2024
SELECT tournament, date, entrants FROM tournaments
WHERE in_michigan AND year = 2024 ORDER BY entrants DESC NULLS LAST LIMIT 5;

-- Who a player has beaten most often
SELECT opponent, count(*) AS wins FROM player_sets
WHERE player_id = 6126 AND won AND NOT is_dq
GROUP BY opponent ORDER BY wins DESC LIMIT 5;
"""
