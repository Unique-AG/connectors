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
