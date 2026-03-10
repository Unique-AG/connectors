UPDATE "inbox_configuration"
SET "filters" = "filters"
  || CASE WHEN NOT ("filters" ? 'ignoredSenders') THEN '{"ignoredSenders":[]}'::jsonb ELSE '{}'::jsonb END
  || CASE WHEN NOT ("filters" ? 'ignoredContents') THEN '{"ignoredContents":[]}'::jsonb ELSE '{}'::jsonb END
WHERE "filters" IS NOT NULL
  AND NOT ("filters" ? 'ignoredSenders' AND "filters" ? 'ignoredContents');
