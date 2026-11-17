-- Roll back add_match_outcome.sql.
-- Warning: walkover matches lose their outcome and will look like unplayed 0-0 matches again.

ALTER TABLE `match`
DROP COLUMN `outcome`,
DROP COLUMN `outcome_reason`,
DROP COLUMN `outcome_decided_by`,
DROP COLUMN `outcome_decided_at`;
