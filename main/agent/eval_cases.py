"""Questions with known answers for scoring agent backends (manage.py eval_agent).

Every case's expected answer is computed live by a reference query against the
`agent` views, so the scores stay right as data changes. Checks are deliberately
lenient about wording and strict about facts: the answer must contain the right
name(s) and/or number(s).

check kinds
  top      reference rows are (name, value) ordered best-first; the answer must name one of the
           players tied for the top value (and include the value when need_value is set)
  names    every name in the reference's first column must appear
  number   the single reference number must appear (within `tol`)
"""

# The player with this exact tag who has the most sets (tags are not unique).
def _pid(tag):
    return (f"(SELECT player_id FROM agent.player_sets WHERE player = '{tag}' "
            f"GROUP BY player_id ORDER BY count(*) DESC LIMIT 1)")


_DAWN = "(SELECT season_id FROM agent.pr_seasons WHERE season = '2026 Dawn')"
_SF25 = "(SELECT season_id FROM agent.pr_seasons WHERE season = '2025 Summer-Fall')"

CASES = [
    # ---- easy: one lookup ----
    dict(id='e1', level='easy', question='Who won Tipped Off 16?', check='names',
         sql="SELECT player FROM agent.placements WHERE tournament ILIKE 'Tipped Off 16%' AND placement = 1"),
    dict(id='e2', level='easy', question='Who was ranked number 1 on the 2026 Dawn power rankings?', check='names',
         sql=f"SELECT player FROM agent.pr_rankings WHERE season_id = {_DAWN} AND rank = 1"),
    dict(id='e3', level='easy', question='Who were the top 3 on the 2025 Summer-Fall PR?', check='names',
         sql=f"SELECT player FROM agent.pr_rankings WHERE season_id = {_SF25} AND rank <= 3 ORDER BY rank"),
    dict(id='e4', level='easy', question='What rank was Ferrety on the 2025 Summer-Fall power rankings?', check='number',
         sql=f"SELECT rank FROM agent.pr_rankings WHERE season_id = {_SF25} AND player = 'Ferrety'"),
    dict(id='e5', level='easy', question='How many PR seasons have published rankings?', check='number',
         sql="SELECT count(*) FROM agent.pr_seasons WHERE ranked_players > 0"),
    dict(id='e6', level='easy', question='Who got second at Tipped Off 16?', check='names',
         sql="SELECT player FROM agent.placements WHERE tournament ILIKE 'Tipped Off 16%' AND placement = 2"),

    # ---- medium: one aggregate query ----
    dict(id='m1', level='medium', question='How many tournaments in Michigan were held in 2024?', check='number',
         sql="SELECT count(*) FROM agent.tournaments WHERE in_michigan AND year = 2024"),
    dict(id='m2', level='medium', question='Which player won the most Michigan tournaments in 2025?', check='top',
         sql="SELECT player, count(*) FROM agent.placements WHERE placement = 1 AND in_michigan AND year = 2025 "
             "GROUP BY player ORDER BY 2 DESC LIMIT 10"),
    dict(id='m3', level='medium', question='What was the biggest Michigan tournament by entrants in 2025?', check='top',
         sql="SELECT tournament, entrants FROM agent.tournaments WHERE in_michigan AND year = 2025 "
             "AND entrants IS NOT NULL ORDER BY entrants DESC LIMIT 5"),
    dict(id='m4', level='medium', question='How many sets has Ferrety won, not counting DQs?', check='number',
         sql=f"SELECT count(*) FROM agent.player_sets WHERE player_id = {_pid('Ferrety')} AND won AND NOT is_dq"),
    dict(id='m5', level='medium', question='Which opponent has Ferrety beaten the most times?', check='top',
         sql=f"SELECT opponent, count(*) FROM agent.player_sets WHERE player_id = {_pid('Ferrety')} "
             "AND won AND NOT is_dq GROUP BY opponent ORDER BY 2 DESC LIMIT 10"),
    dict(id='m6', level='medium', question='Other than Michigan, which state has hosted the most tournaments in the data?',
         check='top',
         sql="SELECT state, count(*) FROM agent.tournaments WHERE NOT in_michigan AND state IS NOT NULL "
             "GROUP BY state ORDER BY 2 DESC LIMIT 5"),
    dict(id='m7', level='medium', question='How many different players won at least one Michigan tournament in 2025?',
         check='number',
         sql="SELECT count(DISTINCT player_id) FROM agent.placements WHERE placement = 1 AND in_michigan AND year = 2025"),
    dict(id='m8', level='medium', question='Who has lost to Negat!ve the most times?', check='top',
         sql=f"SELECT opponent, count(*) FROM agent.player_sets WHERE player_id = {_pid('Negat!ve')} "
             "AND won AND NOT is_dq GROUP BY opponent ORDER BY 2 DESC LIMIT 10"),
    dict(id='m9', level='medium', question='Which player entered the most Michigan tournaments in 2025?', check='top',
         sql="SELECT player, count(*) FROM agent.placements WHERE in_michigan AND year = 2025 "
             "GROUP BY player ORDER BY 2 DESC LIMIT 10"),

    # ---- hard: several steps or careful definitions ----
    dict(id='h1', level='hard', question='Who had the most top-8 finishes at Michigan tournaments in 2025?', check='top',
         sql="SELECT player, count(*) FROM agent.placements WHERE placement <= 8 AND in_michigan AND year = 2025 "
             "GROUP BY player ORDER BY 2 DESC LIMIT 10"),
    dict(id='h2', level='hard',
         question="What was Ferrety's set win percentage in 2025, excluding DQs? Round to the nearest whole percent.",
         check='number', tol=1,
         sql=f"SELECT round(100.0 * count(*) FILTER (WHERE won) / count(*)) FROM agent.player_sets "
             f"WHERE player_id = {_pid('Ferrety')} AND NOT is_dq AND extract(year FROM date) = 2025"),
    dict(id='h3', level='hard',
         question='Among players ranked on the 2026 Dawn PR, who has played the most sets overall (excluding DQs)?',
         check='top',
         sql=f"SELECT ps.player, count(*) FROM agent.player_sets ps WHERE NOT ps.is_dq AND ps.player_id IN "
             f"(SELECT player_id FROM agent.pr_rankings WHERE season_id = {_DAWN}) "
             "GROUP BY ps.player_id, ps.player ORDER BY 2 DESC LIMIT 10"),
    dict(id='h4', level='hard',
         question='How many Michigan tournaments did the 2025 Summer-Fall number 1 win during that PR season?',
         check='number',
         sql=f"SELECT count(*) FROM agent.placements pl, agent.pr_seasons s WHERE s.season_id = {_SF25} "
             f"AND pl.player_id = (SELECT player_id FROM agent.pr_rankings WHERE season_id = {_SF25} AND rank = 1) "
             "AND pl.placement = 1 AND pl.in_michigan AND pl.date BETWEEN s.start_date AND s.end_date"),
    dict(id='h5', level='hard',
         question='Against players ranked in the top 5 of the 2026 Dawn PR, which player outside that top 5 has '
                  'the most set wins (excluding DQs)?',
         check='top',
         sql=f"WITH t5 AS (SELECT player_id FROM agent.pr_rankings WHERE season_id = {_DAWN} AND rank <= 5) "
             "SELECT player, count(*) FROM agent.player_sets WHERE won AND NOT is_dq "
             "AND opponent_id IN (SELECT player_id FROM t5) AND player_id NOT IN (SELECT player_id FROM t5) "
             "GROUP BY player_id, player ORDER BY 2 DESC LIMIT 10"),
    dict(id='h6', level='hard', question='What was the average number of entrants at Michigan tournaments in 2025?',
         check='number', tol=1,
         sql="SELECT round(avg(entrants)) FROM agent.tournaments WHERE in_michigan AND year = 2025"),
]
