
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