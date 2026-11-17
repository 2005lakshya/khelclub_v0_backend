-- Add match outcome columns to the match table.
--
-- `status`  stays the lifecycle field (pending -> on-going -> completed).
-- `outcome` says HOW a finished match was decided: 'normal' (played and scored),
--           'walkover', and later 'forfeit', 'bye', ...
--
-- `outcome` is a VARCHAR, not an ENUM, on purpose: valid values live in one place
-- in code (match_outcomes.py), so adding a new outcome needs no schema migration.
--
-- Every existing row gets outcome = 'normal', so all existing behaviour is unchanged.

ALTER TABLE `match`
ADD COLUMN `outcome` VARCHAR(20) NOT NULL DEFAULT 'normal',
ADD COLUMN `outcome_reason` VARCHAR(255) NULL,
ADD COLUMN `outcome_decided_by` VARCHAR(100) NULL,
ADD COLUMN `outcome_decided_at` DATETIME NULL;
