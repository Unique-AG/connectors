<!-- confluence-page-id: 1953562662 -->
<!-- confluence-space-key: PUBDOC -->


## General

### What type of connector is this?

**Answer:** The SharePoint Connector is a pull-based synchronization service that periodically scans SharePoint sites and syncs flagged documents to the Unique knowledge base.

**Key characteristics:**

- Runs on a schedule (default: every 15 minutes)
- Pulls content from SharePoint (vs. push-based Power Automate v1)
- Requires explicit flagging of documents via a custom column
- Operates as a background service without user interaction

### How does this differ from the Power Automate connector (v1)?

**Answer:**

| Aspect | v1 (Power Automate) | v2 (SharePoint Connector) |
|--------|---------------------|---------------------------|
| Architecture | Push-based | Pull-based |
| Trigger | Power Automate flow | Scheduled scan |
| Dependencies | Power Automate license | None (standalone) |
| Deployment | Power Automate cloud | Kubernetes container |
| Control | Limited | Full control |

## Permissions

### Why Sites.Selected / Lists.SelectedOperations.Selected instead of Sites.Read.All?

**Answer:** `Sites.Selected` and `Lists.SelectedOperations.Selected` follow the principle of least privilege:

- **Sites.Read.All**: Grants access to ALL sites in the tenant
- **Sites.Selected**: Only grants access to explicitly approved sites
- **Lists.SelectedOperations.Selected**: Only grants access to explicitly approved document libraries

Benefits:

- Administrators control exactly which sites or libraries are accessible
- Each grant is auditable and revocable
- Meets enterprise security requirements
- Aligns with zero-trust principles

### Why do I need GroupMember.Read.All for permission sync?

**Answer:** SharePoint permissions often reference Entra ID (Azure AD) groups. To sync these permissions to Unique, the connector must:

1. Read the permission entry (group ID)
2. Expand the group to get member list
3. Map members to Unique users

Without `GroupMember.Read.All`, group-based permissions cannot be synchronized.

### Why can't I read SharePoint site group members?

**Answer:** SharePoint site groups have a visibility setting: "Who can view the membership of the group?"

If this is **not** set to "Everyone", the connector cannot read group members.

**Solutions:**

1. Set group visibility to "Everyone"
2. Add the app principal as a group member/owner
3. Grant Full Control to the app principal

### How do public and private SharePoint sites affect `Everyone` permissions?

**Answer:** Private and public sites can behave differently for tenant-wide visibility:

- **Private site:** Access is typically limited to explicit members/owners/visitors.
- **Public site (org-visible):** SharePoint can include tenant-wide principals such as `Everyone except external users` for read visibility.

The connector intentionally does not expand tenant-wide principals (`Everyone`, `Everyone except external users`) during permission sync. This avoids broad permission replication into Unique and can create a visible difference between SharePoint and Unique access behavior.

## Configuration

### What are the two ways to configure sites?

**Answer:** The connector supports two configuration sources:

| Source | Description | Use Case |
|--------|-------------|----------|
| `config_file` | Static YAML configuration | Simple deployments, fixed site list |
| `sharepoint_list` | Dynamic configuration from SharePoint list | Self-service, frequent changes |

**Static (YAML file):**

```yaml
sharepoint:
  sitesSource: config_file
  sites:
    - siteId: "xxx-xxx-xxx"
      syncColumnName: UniqueAI
      ingestionMode: recursive
      scopeId: scope_xxx
      syncMode: content_only
```

**Dynamic (SharePoint list):**

```yaml
sharepoint:
  sitesSource: sharepoint_list
  sharepointList:
    siteId: "config-site-id"
    listDisplayName: "SharePoint Sites to Sync"
```

### What columns are needed for the SharePoint configuration list?

**Answer:** When using `sharepoint_list` as the sites source, create a list with these columns:

| Column Display Name | Type | Required | Description |
|---------------------|------|----------|-------------|
| `siteId` | Single line text | Yes | SharePoint site ID (UUID) |
| `syncColumnName` | Single line text | Yes | Column marking files for sync |
| `ingestionMode` | Choice | Yes | `flat` or `recursive` |
| `uniqueScopeId` | Single line text | Yes | Unique scope ID |
| `syncStatus` | Choice | Yes | `active`, `inactive`, or `deleted` |
| `syncMode` | Choice | Yes | `content_only` or `content_and_permissions` |
| `maxFilesToIngest` | Number | No | Optional limit |
| `storeInternally` | Choice | No | `enabled` or `disabled` |
| `permissionsInheritanceMode` | Choice | No | Inheritance settings |

### How do I find SharePoint Site IDs?

**Answer:** Several methods are available:

**Method 1: Graph Explorer**

```
GET https://graph.microsoft.com/v1.0/sites/{hostname}:/{site-path}
```

Example:

```
GET https://graph.microsoft.com/v1.0/sites/contoso.sharepoint.com:/sites/marketing
```

**Method 2: PowerShell**

```powershell
Connect-PnPOnline -Url "https://contoso.sharepoint.com/sites/marketing" -Interactive
Get-PnPSite | Select-Object Id
```

**Method 3: SharePoint URL Pattern**

The site ID follows the format: `{hostname},{site-collection-id},{web-id}`

## Sync Behavior

### What happens when a file is deleted from SharePoint?

**Answer:** The file is automatically removed from the Unique knowledge base on the next sync cycle. The file diff mechanism detects:

- Files deleted from SharePoint
- Files with sync flag changed to "No"

Both are treated as deletions in Unique.

### What happens if I unflag a document?

**Answer:** Setting the sync column to "No" is treated as a deletion request. On the next sync cycle:

1. Connector detects the flag change
2. File is removed from Unique knowledge base
3. Local state is updated

### Are subfolders synced?

**Answer:** It depends on the `ingestionMode` setting for each site:

| Mode | Behavior |
|------|----------|
| `recursive` | Scans all subfolders, maintains folder hierarchy in Unique |
| `flat` | All flagged files go to a single root scope |

The sync column must be set on individual files (not folders).

### What file types are supported?

**Answer:** By default:

- PDF (`.pdf`)
- Word (`.docx`)
- Excel (`.xlsx`)
- PowerPoint (`.pptx`)
- Text (`.txt`)
- SharePoint pages (`.aspx`)

Additional types can be configured via `ALLOWED_MIME_TYPES`.

### What is the maximum file size?

**Answer:** Default is 50 MB, configurable via `maxFileSizeToIngestBytes` in the processing configuration. Larger files are skipped with a warning in the logs.

## Troubleshooting

### Why aren't my documents syncing?

**Checklist:**

1. Is the sync column set to "Yes" for the document?
2. Is the site configured (in YAML or SharePoint list)?
3. Is the site's `syncStatus` set to `active`?
4. Is the file type in `allowedMimeTypes`?
5. Is the file under `maxFileSizeToIngestBytes`?
6. Check connector logs for errors

### How does the connector behave when errors occur?

**Answer:** The connector uses scenario-based handling to keep sync cycles running:

- transient API/network issues are retried with backoff
- non-retryable item errors are logged and skipped
- configuration/authentication problems require operator action and can fail a cycle early

Detailed behavior by scenario is documented in [Flows](./technical/flows.md#error-handling-strategy).

### Why do I see "Site not found" errors?

**Causes:**

- Incorrect site ID
- Site-specific permission not granted
- Site deleted or renamed

**Resolution:**

1. Verify site ID using Graph Explorer
2. Re-grant site access via PowerShell
3. Check site exists in SharePoint

### Why do I see "Access denied" errors?

**Causes:**

- `Sites.Selected` or `Lists.SelectedOperations.Selected` not granted for the site/library
- Admin consent not completed
- Certificate/credential issues

**Resolution:**

1. Grant site or library access via PowerShell
2. Complete admin consent in Azure Portal
3. Verify certificate configuration

### Why is sync taking too long?

**Possible causes:**

- Too many files to process
- Large file sizes
- API rate limiting
- Network latency

**Solutions:**

1. Increase `CONCURRENT_FILE_DOWNLOADS`
2. Review and reduce flagged files
3. Check for rate limit warnings in logs
4. Verify network connectivity

### Why is a public SharePoint site accessible, but its content is not visible in Unique for all users?

**Answer:** This usually occurs when SharePoint visibility is granted through tenant-wide groups such as `Everyone` or `Everyone except external users`.

- SharePoint may allow broad read access through those principals.
- The connector does not sync those tenant-wide principals to Unique permissions.

Resolution:

1. Grant access through explicit users/groups that are supported by connector permission sync.
2. Re-run permission sync after updating site permissions.
3. See [Permissions](./technical/permissions.md) and [Flows](./technical/flows.md) for supported resolution behavior.

### Why do I see `secretOrPrivateKey must be an asymmetric key when using RS256`?

**Answer:** The connector received private key material in an unsupported format.

Common causes:

- Key is provided as plain text that is not valid PEM/asymmetric key content
- Key and certificate do not match
- KeyVault-backed secret value does not contain the expected key file content

Resolution:

1. Provide private key content in a valid file-based PEM/asymmetric format.
2. Verify key/certificate pair consistency.
3. Reapply connector secret/config values and restart the pod.

## Multi-Tenant

### Can one connector serve multiple SharePoint tenants?

**Answer:** Not currently. Each SharePoint tenant requires a separate connector deployment. Multi-tenant support is planned for a future release.

**Workaround:** Deploy multiple connector instances, each configured for a different tenant.

### Can I sync from multiple SharePoint sites?

**Answer:** Yes, configure multiple sites in the tenant configuration:

**Static configuration:**

```yaml
sharepoint:
  sitesSource: config_file
  sites:
    - siteId: "site-id-1"
      # ... other settings
    - siteId: "site-id-2"
      # ... other settings
```

**Dynamic configuration:** Add multiple rows to the SharePoint configuration list.

Each site must have `Sites.Selected` or library-specific `Lists.SelectedOperations.Selected` permission granted separately.

## Performance

### What are the resource requirements?

**Answer:**

- Memory: ~2 GB
- CPU: 1 core
- Storage: Minimal (streaming, no local storage)

### What are the API rate limits?

**Answer:** Microsoft Graph limits:

- ~10,000 requests per 10 minutes per app
- 4 concurrent requests per resource type

The connector respects these limits via configurable rate limiting and exponential backoff.

## Certificates

### What certificate formats are supported, and do I need the thumbprint?

**Answer:** Generate certificates with OpenSSL or PowerShell and keep the deployment on connector-compatible asymmetric key/certificate material.

- OpenSSL output can be `.key` + `.crt` and optionally `.pfx`
- PowerShell commonly produces `.cer`/`.pfx`
- If needed, convert formats to the recommended PEM key/cert files before configuring the connector

After uploading the certificate to Entra App Registration, capture the **Thumbprint (SHA)** and add it to connector configuration where thumbprint is required by your deployment setup.

## Related Documentation

- [Operator Guide](./operator/README.md) - Deployment and operations
- [Authentication](./operator/authentication.md) - Auth setup details
- [Configuration](./operator/configuration.md) - Environment variables
- [Permissions](./technical/permissions.md) - API permissions

## Standard References

- [Microsoft Graph API](https://learn.microsoft.com/en-us/graph/overview) - Graph documentation
- [SharePoint REST API](https://learn.microsoft.com/en-us/sharepoint/dev/sp-add-ins/get-to-know-the-sharepoint-rest-service) - SharePoint REST
- [Sites.Selected](https://learn.microsoft.com/en-us/graph/api/site-get) - Sites.Selected permission
- [Lists.SelectedOperations.Selected](https://learn.microsoft.com/en-us/graph/permissions-reference#listsselectedoperationsselected) - Library-specific permission
