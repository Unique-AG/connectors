UPDATE "inbox_configuration"
SET "filters" = ("filters" - 'dateFrom') || jsonb_build_object('ignoredBefore', "filters" -> 'dateFrom')
WHERE "filters" ? 'dateFrom';
