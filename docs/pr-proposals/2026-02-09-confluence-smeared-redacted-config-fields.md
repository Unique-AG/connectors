# PR Proposal

## Title
feat(confluence-connector): add Smeared class for diagnostic data protection in config fields

## Description
- Port `Smeared` class and `smear()` utility from sharepoint-connector for partial masking of diagnostic identifiers in production logs
- Add `LOGS_DIAGNOSTICS_DATA_POLICY` env var to control smearing behavior (conceal/disclose)
- Apply `Smeared` to `auth.email`, `auth.username`, and `serviceExtraHeaders` identifier fields
- Existing `Redacted` fields (secrets) remain unchanged
