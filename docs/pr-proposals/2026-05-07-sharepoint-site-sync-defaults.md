# PR Proposal

## Ticket
UN-20464

## Title
feat(sharepoint-connector): configurable site-sync defaults via Helm

## Description
- Add a `sharepoint.siteDefaults` block (rendered by Helm) so deployment-level defaults fill in any per-site field except `siteId`.
- Per-site values from the SharePoint list or `config_file` always win when set; empty/whitespace cells fall through to deployment defaults, then to existing schema defaults.
- Backward compatible: tenants without `siteDefaults` keep today's behavior; failure mode (one bad row aborts the whole load) is preserved.
- Touches `sharepoint.schema.ts`, a new merger module, `SitesConfigurationService`, both example tenant configs, and the Helm chart `values.yaml` + a new helm-unittest case.
