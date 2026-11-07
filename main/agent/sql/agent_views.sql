-- Semantic layer for the Ask Tom agent.
--
-- The agent's database role can only SELECT from the views in the `agent`
-- schema. They hide the awkward parts of the raw schema (player1/player2
-- symmetry, DQ scores of -1, text PR ranks, the composite-key results table)
-- so a small model can write correct SQL.
--
-- Run as the app's table owner with:  python manage.py setup_agent_db
-- Safe to re-run: every view is CREATE OR REPLACE / dropped and recreated.

CREATE SCHEMA IF NOT EXISTS agent;

DROP VIEW IF EXISTS agent.player_sets, agent.sets, agent.placements, agent.pr_rankings,
    agent.pr_seasons, agent.tournaments, agent.players CASCADE;

CREATE VIEW agent.players AS
SELECT p.id                      AS player_id,
       p.name                    AS player,
       r.name                    AS region,
       mc.name                   AS main_character,
       sc.name                   AS secondary_character,
       COALESCE(p.pr_eligible, false) AS pr_eligible,
       COALESCE(p.pr_notable, false)  AS pr_notable
FROM public.player p
LEFT JOIN public.region r     ON r.id = p.region_code
LEFT JOIN public."character" mc ON mc.id = p.main_char_id
LEFT JOIN public."character" sc ON sc.id = p.secondary_char_id;

CREATE VIEW agent.tournaments AS
SELECT t.id                                   AS tournament_id,
       t.name                                 AS tournament,
       t.date,
       EXTRACT(YEAR FROM t.date)::int         AS year,
       t.city,
       t.state,
       (t.state = 'MI')                       AS in_michigan,
       t.venue_name,
       t.entrant_count                        AS entrants,
       COALESCE(t.online, false)              AS online
FROM public.tournament t;

CREATE VIEW agent.sets AS
SELECT s.id                                   AS set_id,
       s.tournament_id,
       t.name                                 AS tournament,
       t.date,
       s.location                             AS round,
       s.player1                              AS player1_id,
       p1.name                                AS player1,
       s.player2                              AS player2_id,
       p2.name                                AS player2,
       s.player1_score,
       s.player2_score,
       s.winner_id,
       pw.name                                AS winner,
       CASE WHEN s.winner_id = s.player1 THEN s.player2 ELSE s.player1 END AS loser_id,
       CASE WHEN s.winner_id = s.player1 THEN p2.name ELSE p1.name END     AS loser,
       (s.player1_score < 0 OR s.player2_score < 0)                       AS is_dq,
       s.pr_eligible
FROM public."set" s
JOIN public.tournament t ON t.id = s.tournament_id
LEFT JOIN public.player p1 ON p1.id = s.player1
LEFT JOIN public.player p2 ON p2.id = s.player2
LEFT JOIN public.player pw ON pw.id = s.winner_id;

-- One row per player per set: every set appears twice, once from each side.
-- Use this for records, wins, losses and head-to-heads.
CREATE VIEW agent.player_sets AS
SELECT set_id, tournament_id, tournament, date, round,
       player1_id AS player_id, player1 AS player,
       player2_id AS opponent_id, player2 AS opponent,
       player1_score AS player_score, player2_score AS opponent_score,
       (winner_id = player1_id) AS won,
       is_dq, pr_eligible
FROM agent.sets
UNION ALL
SELECT set_id, tournament_id, tournament, date, round,
       player2_id, player2,
       player1_id, player1,
       player2_score, player1_score,
       (winner_id = player2_id),
       is_dq, pr_eligible
FROM agent.sets;

CREATE VIEW agent.placements AS
SELECT tr.tournament_id,
       t.name           AS tournament,
       t.date,
       EXTRACT(YEAR FROM t.date)::int AS year,
       (t.state = 'MI') AS in_michigan,
       t.entrant_count  AS entrants,
       tr.player_id,
       p.name           AS player,
       tr.placement
FROM public.tournament_results tr
JOIN public.tournament t ON t.id = tr.tournament_id
JOIN public.player p     ON p.id = tr.player_id;

CREATE VIEW agent.pr_seasons AS
SELECT s.id         AS season_id,
       s.name       AS season,
       s.start_date,
       s.end_date,
       s.is_active,
       (SELECT count(*) FROM public.pr_season_results r WHERE r.pr_season_id = s.id) AS ranked_players
FROM public.pr_season s;

CREATE VIEW agent.pr_rankings AS
SELECT s.id          AS season_id,
       s.name        AS season,
       s.start_date,
       s.end_date,
       r.player_id,
       p.name        AS player,
       CASE WHEN r.rank ~ '^[0-9]+$' THEN r.rank::int END AS rank,
       r.rank        AS rank_label
FROM public.pr_season_results r
JOIN public.pr_season s ON s.id = r.pr_season_id
JOIN public.player p    ON p.id = r.player_id;

-- The agent role (created by create_agent_role.sql) reads these views only.
GRANT USAGE ON SCHEMA agent TO mimelee_agent;
GRANT SELECT ON ALL TABLES IN SCHEMA agent TO mimelee_agent;
