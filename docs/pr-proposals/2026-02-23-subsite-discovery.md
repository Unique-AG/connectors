# PR Proposal

## Ticket

UN-17398

## Title

feat(sharepoint-connector): recursively discover and sync subsite content

## Description

- Add support for configuring subsites as sites to be synced by using compound ID
- Introduce `subsitesScan` configuration option (default: `disabled`) to control subsite discovery per site
- Add `SubsiteDiscoveryService` to recursively discover subsites via `GET /sites/{siteId}/sites` Graph API endpoint
- Update sync orchestration to fetch drives and ASPX pages from all discovered subsites, merging them into the parent site's sync
- Verify orphan scope cleanup covers discovered subsites (handled via root site prefix)
- Update documentation to reflect new configuration and permissions
