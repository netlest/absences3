-- PostgreSQL compatible view
CREATE OR REPLACE VIEW v_absences AS
WITH RECURSIVE split_periods AS (
        SELECT abs.id,
        abs.object_id,
        g.id group_id,
        o.user_id,
        abs.type_id,
        abs.abs_date_start,
        LEAST(abs.abs_date_end, (date_trunc('month'::text, abs.abs_date_start::timestamp with time zone) + '1 mon'::interval - '1 day'::interval)::date) AS abs_date_end,
        abs.description,
        at.color AS at_color,
        at.name AS at_name
        FROM absences abs
            LEFT JOIN absence_types at ON abs.type_id = at.id
            LEFT JOIN objects o ON abs.object_id = o.id
            LEFT JOIN groups g ON o.group_id = g.id
    UNION ALL
        SELECT sp.id,
        sp.object_id,
        sp.group_id,
        sp.user_id,
        sp.type_id,
        (sp.abs_date_end + '1 day'::interval)::date AS abs_date_start,
        LEAST(abs.abs_date_end, (date_trunc('month'::text, sp.abs_date_end + '1 day'::interval) + '1 mon'::interval - '1 day'::interval)::date) AS abs_date_end,
        sp.description,
        sp.at_color,
        sp.at_name
        FROM split_periods sp
            JOIN absences abs ON sp.id = abs.id
        WHERE sp.abs_date_end < abs.abs_date_end
    )
SELECT
	*,
    abs_date_end - abs_date_start + 1 AS duration
FROM split_periods;