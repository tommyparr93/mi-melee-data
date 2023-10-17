
-- QUERY TO UPDATE / ASSIGN ALL TOURNAMENTS TO MATCH THEIR PR SEASONS LISTED IN THE PR SEASON TABLE
BEGIN TRANSACTION;
UPDATE tournament
SET pr_season_id = pr_season.id
FROM pr_season
WHERE   tournament.date >= pr_season.start_date AND
        tournament.date <= pr_season.end_date;
select * from tournament;
COMMIT;

-- QUERY TO IDENTIFY ALL DUPLICATE NAMES IN DB
-- AND TO SEE WHICH ACCT HAS THE HIGHER NUMBER OF SETS PLAYED TO IDENTIFY THE MAIN ACCOUNT
SELECT p.id, p.name , p.main_account_id, count(*) as total_sets
FROM player p
JOIN set s ON (p.id = s.player1 OR p.id = s.player2)
WHERE LOWER(p.name) IN (
    SELECT LOWER(name)
    FROM player
    GROUP BY LOWER(name)
    HAVING COUNT(*) > 1
)
GROUP BY p.id
ORDER BY p.name ASC;


-- FIX DUPLICATE IDS FOR WINNER ID
UPDATE public.set
SET winner_id = CASE
    WHEN player1_score > player2_score THEN player1
    WHEN player2_score > player1_score THEN player2
    ELSE winner_id -- keep the current winner_id if scores are equal
END
WHERE winner_id != player1 AND winner_id != player2;


-- find players with most tournaments and sets

SELECT
    p.name,
	p.region_code,
    COUNT(DISTINCT s.id) as set_count,
	COUNT(DISTINCT t.id) as "appearances"

FROM
    player p
LEFT JOIN (
    SELECT player1 as player_id, id, tournament_id FROM "set"
    UNION
    SELECT player2 as player_id, id, tournament_id FROM "set"
) s ON s.player_id = p.id
JOIN tournament t ON t.id = s.tournament_id
WHERE
    t.pr_season_id = 2
GROUP BY
    p.name,
	p.region_code
	ORDER BY appearances desc



-- update tournament region to michigan

UPDATE tournament
SET region_code = 7
WHERE city IN (
    'Ann Arbor',
    'Dearborn',
    'Fraser',
    'Grand Rapids',
    'Ypsilanti',
    'Walker',
    'Bay City',
    'Midland',
    'Allendale Charter Township',
    'Mount Pleasant',
    'Detroit',
    'Houghton',
    'Lansing',
    'East Lansing'
);