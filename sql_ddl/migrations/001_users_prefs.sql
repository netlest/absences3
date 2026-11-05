-- Persist calendar view preferences per user instead of per session.
-- Databases created from sql_ddl/schema.sql after this change already have
-- the column; the statement is idempotent, so running it there is harmless.
ALTER TABLE users ADD COLUMN IF NOT EXISTS prefs JSONB NOT NULL DEFAULT '{}'::jsonb;

-- Carry over the view each user last saved in a session (the newest session
-- that has prefs), so the upgrade doesn't reset anyone's calendar view.
-- Only fills users with no prefs yet, so re-running is harmless.
UPDATE users u
SET prefs = s.prefs
FROM (
    SELECT DISTINCT ON (user_id) user_id, prefs
    FROM (
        SELECT (convert_from(data, 'UTF8')::jsonb ->> 'user_id')::int AS user_id,
               convert_from(data, 'UTF8')::jsonb -> 'prefs' AS prefs,
               expiry
        FROM sessions
        WHERE data IS NOT NULL
    ) d
    WHERE jsonb_typeof(prefs) = 'object' AND prefs <> '{}'::jsonb
    ORDER BY user_id, expiry DESC NULLS LAST
) s
WHERE u.id = s.user_id AND u.prefs = '{}'::jsonb;
