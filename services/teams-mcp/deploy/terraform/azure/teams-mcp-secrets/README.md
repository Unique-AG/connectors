# Teams MCP Secrets Terraform Module

**Status: ALPHA / EXPERIMENTAL**

This Terraform module manages secrets in Azure Key Vault required by the Teams MCP service.

## Purpose

This module provisions secrets needed for Teams MCP operation:
- Cryptographic secrets for security (HMAC, encryption, webhook validation)
- Placeholders for manually-set configuration secrets
- Automatic generation of secure random values

## Features

- **Auto-Generated Secrets**: Optionally generates cryptographic secrets using Terraform providers
- **Manual Secret Placeholders**: Creates Key Vault entries for secrets that must be set manually
- **Lifecycle Management**: Ignores changes to manual secrets after initial creation
- **Secure Defaults**: Uses appropriate length and character sets for each secret type

## Secrets Created

### Auto-Generated Secrets (when `auto_generate_secrets = true`)

| Secret Name | Description | Format | Length |
|-------------|-------------|--------|--------|
| `teams-mcp-hmac-secret` | HMAC secret for JWT token signing | Alphanumeric + special | 64 chars |
| `teams-mcp-webhook-secret` | Webhook validation secret for Microsoft Graph | Alphanumeric only | 128 chars |
| `teams-mcp-encryption-key` | AES-256 encryption key for data at rest | Hex-encoded | 32 bytes (64 hex chars) |

### Manual Secret Placeholders (Required)

| Secret Name | Description | Config Key | Required |
|-------------|-------------|------------|----------|
| `manual-teams-mcp-client-secret` | Microsoft Entra application client secret | `MICROSOFT_CLIENT_SECRET` | Yes |
| `manual-teams-mcp-database-url` | PostgreSQL connection URL | `DATABASE_URL` | Yes |
| `manual-teams-mcp-amqp-url` | AMQP/RabbitMQ connection URL | `AMQP_URL` | Yes |
| `manual-teams-mcp-public-webhook-url` | Public webhook URL for Microsoft Graph subscriptions | `MICROSOFT_PUBLIC_WEBHOOK_URL` | Yes |
| `manual-teams-mcp-unique-service-extra-headers` | JSON object with auth headers | `UNIQUE_SERVICE_EXTRA_HEADERS` | Yes |

### Non-Secret Configuration (Helm Values)

The following should be configured via Helm values instead of Key Vault:

| Helm Value | Environment Variable | Description |
|------------|---------------------|-------------|
| `mcpConfig.unique.apiBaseUrl` | `UNIQUE_API_BASE_URL` | Unique Public API base URL |
| `mcpConfig.unique.ingestionServiceBaseUrl` | `UNIQUE_INGESTION_SERVICE_BASE_URL` | Ingestion service URL (cluster_local mode) |
| `mcpConfig.app.selfUrl` | `SELF_URL` | MCP Server URL for OAuth callbacks |

### Unique Service Extra Headers (Secret)

The `UNIQUE_SERVICE_EXTRA_HEADERS` contains sensitive auth tokens (e.g., Authorization header) and must be stored as a secret. The value is a JSON string with the required headers depending on `serviceAuthMode`:

**For `cluster_local` mode** (in-cluster communication):
```json
{"x-company-id": "<company-id>", "x-user-id": "<user-id>"}
```

**For `external` mode** (external API access):
```json
{"authorization": "Bearer <app-key>", "x-app-id": "<app-id>", "x-user-id": "<user-id>", "x-company-id": "<company-id>"}
```

## Usage

### Basic Usage (Auto-Generate Secrets)

```hcl
module "teams_mcp_secrets" {
  source = "./azure/teams-mcp-secrets"

  key_vault_id = azurerm_key_vault.main.id

  # Auto-generate cryptographic secrets
  auto_generate_secrets = true
}

# Output secret names for reference
output "secret_names" {
  value = {
    hmac       = module.teams_mcp_secrets.hmac_secret_name
    webhook    = module.teams_mcp_secrets.webhook_secret_name
    encryption = module.teams_mcp_secrets.encryption_key_name
  }
}
```

### Manual Secrets Only

```hcl
module "teams_mcp_secrets" {
  source = "./azure/teams-mcp-secrets"

  key_vault_id = azurerm_key_vault.main.id

  # Disable auto-generation (all secrets must be set manually)
  auto_generate_secrets = false

  # Add additional manual secret placeholders
  secrets_placeholders = {
    teams-mcp-client-secret = { create = true }
    teams-mcp-database-url  = { create = true }
    teams-mcp-hmac-secret   = { create = true }
    teams-mcp-webhook-secret = { create = true }
    teams-mcp-encryption-key = { create = true }
  }
}
```

### Custom Manual Secrets

```hcl
module "teams_mcp_secrets" {
  source = "./azure/teams-mcp-secrets"

  key_vault_id          = azurerm_key_vault.main.id
  auto_generate_secrets = true

  # Customize manual secrets
  secrets_placeholders = {
    teams-mcp-client-secret = {
      create          = true
      expiration_date = "2025-12-31T23:59:59Z" # Custom expiration
    }
    teams-mcp-database-url = {
      create = true
    }
    # Add additional custom secrets
    teams-mcp-api-key = {
      create = true
    }
  }
}
```

## Variables

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|----------|
| `key_vault_id` | Azure Key Vault ID where secrets will be stored | `string` | - | yes |
| `auto_generate_secrets` | Auto-generate cryptographic secrets | `bool` | `true` | no |
| `secrets_placeholders` | Map of manual secrets to create as placeholders | `map(object)` | See below | no |

### Default `secrets_placeholders`

```hcl
{
  teams-mcp-client-secret = { create = true, expiration_date = "2099-12-31T23:59:59Z" }
  teams-mcp-database-url  = { create = true, expiration_date = "2099-12-31T23:59:59Z" }
}
```

## Outputs

| Name | Description |
|------|-------------|
| `hmac_secret_name` | Name of auto-generated HMAC secret (null if disabled) |
| `webhook_secret_name` | Name of auto-generated webhook secret (null if disabled) |
| `encryption_key_name` | Name of auto-generated encryption key (null if disabled) |
| `manual_secrets` | List of manual secret names that need population |

## Post-Deployment Steps

After applying this module, you must set the manual secrets:

### Using Azure CLI

```bash
# Required secrets
# Set the Microsoft Entra client secret
az keyvault secret set \
  --vault-name <vault-name> \
  --name manual-teams-mcp-client-secret \
  --value "<client-secret-from-entra-module>"

# Set the database URL
az keyvault secret set \
  --vault-name <vault-name> \
  --name manual-teams-mcp-database-url \
  --value "postgresql://user:password@host:5432/teams_mcp?sslmode=require"

# Set the AMQP URL
az keyvault secret set \
  --vault-name <vault-name> \
  --name manual-teams-mcp-amqp-url \
  --value "amqp://user:password@rabbitmq:5672/teams-mcp"

# Set the public webhook URL
az keyvault secret set \
  --vault-name <vault-name> \
  --name manual-teams-mcp-public-webhook-url \
  --value "https://teams-mcp.example.com/webhooks/microsoft"

# Set the Unique service extra headers (JSON string with auth headers)
# For cluster_local mode:
az keyvault secret set \
  --vault-name <vault-name> \
  --name manual-teams-mcp-unique-service-extra-headers \
  --value '{"x-company-id":"<company-id>","x-user-id":"<user-id>"}'

# For external mode (with Authorization token):
# az keyvault secret set \
#   --vault-name <vault-name> \
#   --name manual-teams-mcp-unique-service-extra-headers \
#   --value '{"authorization":"Bearer <app-key>","x-app-id":"<app-id>","x-user-id":"<user-id>","x-company-id":"<company-id>"}'

# NOTE: The following are configured via Helm values, not Key Vault:
# - UNIQUE_API_BASE_URL -> mcpConfig.unique.apiBaseUrl
# - UNIQUE_INGESTION_SERVICE_BASE_URL -> mcpConfig.unique.ingestionServiceBaseUrl
# - SELF_URL -> mcpConfig.app.selfUrl
```

### Using Azure Portal

1. Navigate to your Key Vault in Azure Portal
2. Go to "Secrets" section
3. Find secrets prefixed with `manual-`
4. Click each secret and add a new version with the actual value
5. Ensure expiration dates are set appropriately

## Secret Rotation

### Auto-Generated Secrets

To rotate auto-generated secrets:

```bash
# Force recreation of all auto-generated secrets
terraform apply -replace='module.teams_mcp_secrets.random_password.hmac_secret[0]' \
                -replace='module.teams_mcp_secrets.random_password.webhook_secret[0]' \
                -replace='module.teams_mcp_secrets.random_id.encryption_key[0]'
```

> **Warning**: Rotating encryption keys will make existing encrypted data unreadable. Plan accordingly.

### Manual Secrets

Manual secrets are protected by lifecycle rules and won't be overwritten by Terraform. To rotate:

1. Update the secret value in Azure Key Vault (creates a new version)
2. Update your application to use the new secret
3. Optionally disable old secret versions

## Configuration Mapping

Map Key Vault secrets to Teams MCP environment variables:

### Core Configuration

| Key Vault Secret | Environment Variable | Config Path |
|------------------|---------------------|-------------|
| `teams-mcp-hmac-secret` | `AUTH_HMAC_SECRET` | `auth.hmacSecret` |
| `teams-mcp-encryption-key` | `ENCRYPTION_KEY` | `encryption.key` |

### Microsoft Configuration

| Key Vault Secret | Environment Variable | Config Path |
|------------------|---------------------|-------------|
| `manual-teams-mcp-client-secret` | `MICROSOFT_CLIENT_SECRET` | `microsoft.clientSecret` |
| `teams-mcp-webhook-secret` | `MICROSOFT_WEBHOOK_SECRET` | `microsoft.webhookSecret` |
| `manual-teams-mcp-public-webhook-url` | `MICROSOFT_PUBLIC_WEBHOOK_URL` | `microsoft.publicWebhookUrl` |

### Database Configuration

| Key Vault Secret | Environment Variable | Config Path |
|------------------|---------------------|-------------|
| `manual-teams-mcp-database-url` | `DATABASE_URL` | `database.url` |

### AMQP Configuration

| Key Vault Secret | Environment Variable | Config Path |
|------------------|---------------------|-------------|
| `manual-teams-mcp-amqp-url` | `AMQP_URL` | `amqp.url` |

### App Configuration (Non-Secret via Helm)

| Helm Value | Environment Variable | Config Path |
|------------|---------------------|-------------|
| `mcpConfig.app.selfUrl` | `SELF_URL` | `app.selfUrl` |

### Unique Configuration

**Non-secrets (via Helm ConfigMap):**

| Helm Value | Environment Variable | Config Path |
|------------|---------------------|-------------|
| `mcpConfig.unique.serviceAuthMode` | `UNIQUE_SERVICE_AUTH_MODE` | `unique.serviceAuthMode` |
| `mcpConfig.unique.apiBaseUrl` | `UNIQUE_API_BASE_URL` | `unique.apiBaseUrl` |
| `mcpConfig.unique.ingestionServiceBaseUrl` | `UNIQUE_INGESTION_SERVICE_BASE_URL` | `unique.ingestionServiceBaseUrl` |

**Secret (via Key Vault / Kubernetes Secret):**

| Key Vault Secret | Environment Variable | Config Path |
|------------------|---------------------|-------------|
| `manual-teams-mcp-unique-service-extra-headers` | `UNIQUE_SERVICE_EXTRA_HEADERS` | `unique.serviceExtraHeaders` |

The `serviceExtraHeaders` contains auth-related headers as a JSON string. See the "Unique Service Extra Headers (Secret)" section above for required headers based on auth mode.

### Using CSI Driver (Recommended for Kubernetes)

```yaml
apiVersion: secrets-store.csi.x-k8s.io/v1
kind: SecretProviderClass
metadata:
  name: teams-mcp-secrets
spec:
  provider: azure
  parameters:
    keyvaultName: "<vault-name>"
    tenantId: "<tenant-id>"
    objects: |
      array:
        # Auto-generated secrets
        - objectName: "teams-mcp-hmac-secret"
          objectType: "secret"
          objectAlias: "hmac-secret"
        - objectName: "teams-mcp-webhook-secret"
          objectType: "secret"
          objectAlias: "webhook-secret"
        - objectName: "teams-mcp-encryption-key"
          objectType: "secret"
          objectAlias: "encryption-key"
        # Required manual secrets
        - objectName: "manual-teams-mcp-client-secret"
          objectType: "secret"
          objectAlias: "client-secret"
        - objectName: "manual-teams-mcp-database-url"
          objectType: "secret"
          objectAlias: "database-url"
        - objectName: "manual-teams-mcp-amqp-url"
          objectType: "secret"
          objectAlias: "amqp-url"
        - objectName: "manual-teams-mcp-public-webhook-url"
          objectType: "secret"
          objectAlias: "public-webhook-url"
        - objectName: "manual-teams-mcp-unique-service-extra-headers"
          objectType: "secret"
          objectAlias: "unique-service-extra-headers"
        # NOTE: The following are configured via Helm values (ConfigMap), not Key Vault:
        # - UNIQUE_API_BASE_URL -> mcpConfig.unique.apiBaseUrl
        # - UNIQUE_INGESTION_SERVICE_BASE_URL -> mcpConfig.unique.ingestionServiceBaseUrl
        # - SELF_URL -> mcpConfig.app.selfUrl
```

## Security Considerations

### Auto-Generated Secrets

- **Stored in State**: Auto-generated secrets are stored in Terraform state
- **State Security**: Ensure your Terraform state is encrypted and access-controlled
- **Rotation**: Plan rotation strategy before using auto-generated secrets in production

### Manual Secrets

- **Protected by Lifecycle**: Manual secrets ignore Terraform changes after creation
- **Version Control**: Key Vault maintains version history for audit and rollback
- **Access Control**: Use Key Vault access policies or RBAC to limit who can read secrets

### Best Practices

1. **Enable Key Vault Soft Delete**: Protect against accidental deletion
2. **Set Expiration Dates**: Force periodic rotation of secrets
3. **Use Managed Identities**: Avoid storing credentials for Key Vault access
4. **Monitor Access**: Enable Key Vault logging and monitor access patterns
5. **Separate Secrets**: Use different Key Vaults for dev/staging/production

## Secret Format Requirements

### HMAC Secret
- **Length**: At least 64 characters (auto-generated)
- **Format**: Any characters including special characters
- **Purpose**: Sign and verify JWT tokens

### Webhook Secret
- **Length**: Exactly 128 characters (Microsoft requirement)
- **Format**: Alphanumeric only (A-Za-z0-9)
- **Purpose**: Validate Microsoft Graph webhook notifications

### Encryption Key
- **Length**: Exactly 32 bytes (256 bits)
- **Format**: Hex-encoded (64 hex characters) or Base64
- **Purpose**: AES-256-GCM encryption for data at rest

### Database URL
- **Format**: PostgreSQL connection string
- **Example**: `postgresql://user:password@host:5432/database?sslmode=require`
- **Purpose**: Connect to PostgreSQL database

### Client Secret
- **Format**: Generated by Microsoft Entra
- **Length**: Typically 40-50 characters
- **Purpose**: Authenticate the application to Microsoft Graph

### Public Webhook URL
- **Format**: HTTPS URL
- **Example**: `https://teams-mcp.example.com/webhooks/microsoft`
- **Purpose**: Receive Microsoft Graph webhook notifications

### AMQP URL
- **Format**: AMQP connection string
- **Example**: `amqp://user:password@rabbitmq:5672/teams-mcp`
- **Purpose**: Connect to RabbitMQ for message queueing

### Self URL
- **Format**: HTTPS URL
- **Example**: `https://teams-mcp.example.com`
- **Purpose**: OAuth callback URL for user authentication
- **Note**: This is now configured via Helm values (`mcpConfig.app.selfUrl`), not as a secret

## Non-Secret Configuration

Configuration values that don't need to be secrets are configured via Helm values:

| Environment Variable | Helm Value | Description |
|---------------------|------------|-------------|
| `MICROSOFT_CLIENT_ID` | `mcpConfig.microsoft.clientId` | Microsoft Entra application client ID |
| `PORT` | `mcpConfig.app.port` | HTTP port to bind (default: 51345) |
| `SELF_URL` | `mcpConfig.app.selfUrl` | MCP Server URL for OAuth callbacks |
| `UNIQUE_SERVICE_AUTH_MODE` | `mcpConfig.unique.serviceAuthMode` | Auth mode for Unique API (cluster_local/external) |
| `UNIQUE_API_BASE_URL` | `mcpConfig.unique.apiBaseUrl` | Unique Public API base URL |
| `UNIQUE_API_VERSION` | `mcpConfig.unique.apiVersion` | Unique API version (default: 2023-12-06) |
| `UNIQUE_ROOT_SCOPE_PATH` | `mcpConfig.unique.rootScopePath` | Root scope path for uploads (default: Teams-MCP) |
| `UNIQUE_USER_FETCH_CONCURRENCY` | `mcpConfig.unique.userFetchConcurrency` | Concurrency for user fetching (default: 5) |
| `UNIQUE_INGESTION_SERVICE_BASE_URL` | `mcpConfig.unique.ingestionServiceBaseUrl` | Ingestion service URL (cluster_local mode) |

> **Note**: `UNIQUE_SERVICE_EXTRA_HEADERS` is a **secret** (loaded via `server.envVars`) as it may contain Authorization tokens.

Additional environment variables configured directly in `server.env`:

| Environment Variable | Description |
|---------------------|-------------|
| `NODE_ENV` | Application environment (production/development/test) |
| `LOG_LEVEL` | Logging level (info/debug/trace) |

## Troubleshooting

### Secret Not Found

If your application can't find secrets:
1. Verify Key Vault name is correct
2. Check that secrets exist in Key Vault
3. Ensure application has proper Key Vault access (RBAC or access policy)
4. Verify secret names match exactly (case-sensitive)

### Invalid Encryption Key

If encryption fails:
1. Verify key is exactly 32 bytes (64 hex characters)
2. Check hex encoding is valid
3. Ensure no whitespace or newlines in the key

### Webhook Validation Fails

If webhook validation fails:
1. Verify webhook secret is exactly 128 characters
2. Check it's alphanumeric only (no special characters)
3. Ensure secret matches what was configured in Microsoft Graph subscription

## Requirements

| Name | Version |
|------|---------|
| terraform | ~> 1.10 |
| azurerm | ~> 4 |
| random | ~> 3 |

## Related Documentation

- [Azure Key Vault Best Practices](https://learn.microsoft.com/en-us/azure/key-vault/general/best-practices)
- [Secrets Store CSI Driver](https://secrets-store-csi-driver.sigs.k8s.io/)
- [Teams MCP Configuration](../../../README.md)
