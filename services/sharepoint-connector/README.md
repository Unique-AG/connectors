# SharePoint Connector

A service that connects to SharePoint Online for document and data integration with Unique's ingestion pipeline.

## Prerequisites

### Microsoft 365 / SharePoint Online Setup

#### Required Graph API Permissions

The SharePoint connector requires the following Microsoft Graph API permissions to operate:

| Permission | Type | Purpose | Justification |
|------------|------|---------|---------------|
| `Sites.Read.All` | Application | Read site information and document libraries | Required to discover and list SharePoint sites and their document libraries |
| `Files.Read.All` | Application | Read files and folders from document libraries | Required to scan, list, and download file contents from SharePoint document libraries |

#### Permission Scopes Explained

**Sites.Read.All**
- Allows the application to read all site collections without a signed-in user
- Required for: `/sites/{site-id}/drives` endpoint
- Used to discover available SharePoint sites and their document libraries

**Files.Read.All**
- Allows the application to read all files in all site collections without a signed-in user
- Required for: `/drives/{drive-id}/items/{item-id}/children` and `/drives/{drive-id}/items/{item-id}/content` endpoints
- Used to scan document libraries, list files, and download file contents

### Environment Configuration
Check `env.example` file for a full .env example/ 

### Monitoring

The service exposes standard metrics and health endpoints:
- `/probe` - Health check endpoint
- `/metrics` - Prometheus metrics (if configured)
- Structured logging with correlation IDs for request tracing

## Troubleshooting

### `Invalid hostname for this tenancy`
Double-check the `Sites` you are supplying. Sites are UUIDs (`00000000-0000-0000-0000-000000000000` format) and not names or URL/URIs.

A site ID can be grabbed from suffixing `_api/site/id` to your site, like `https://<your-site>.sharepoint.com/sites/<real-site>/_api/site/id` ([Test](https://uniqueapp.sharepoint.com/sites/UniqueAG/_api/site/id)) and then using `Edm.Guid`.

### `Error scraping target: Get "http://10.1.16.45:51346/metrics": context deadline exceeded`

The chart comes with ingress network policies enabled. In case your scraper is deployed in another namespace or anywhere actually, you must explicitly allow that.

**Example**
```yaml
    …
connector:
  networkPolicy:
    ingress:
    - from:
        - podSelector:
            matchLabels:
                app.kubernetes.io/managed-by: prometheus-operator
```