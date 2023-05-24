
-- QUERY TO UPDATE / ASSIGN ALL TOURNAMENTS TO MATCH THEIR PR SEASONS LISTED IN THE PR SEASON TABLE
BEGIN TRANSACTION;
UPDATE tournament
SET pr_season_id = pr_season.id
FROM pr_season
WHERE   tournament.date >= pr_season.start_date AND
        tournament.date <= pr_season.end_date;
select * from tournament;
COMMIT;