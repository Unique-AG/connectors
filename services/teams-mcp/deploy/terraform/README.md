# Teams MCP Terraform Configuration

This directory contains Terraform modules for provisioning Azure resources required by the Teams MCP service.

## Overview

The Teams MCP service requires:
1. An Azure Entra (AD) application with appropriate Microsoft Graph API permissions
2. Secrets stored in Azure Key Vault for configuration and authentication

## Modules

### `azure/teams-mcp-entra-application`

Creates and configures an Azure Entra application with the required Microsoft Graph API permissions for Teams MCP:

- **User.Read.All** - Read all users' profiles
- **OnlineMeetings.Read.All** - Read all online meetings
- **OnlineMeetingRecording.Read.All** - Read all online meeting recordings
- **OnlineMeetingTranscript.Read.All** - Read all online meeting transcripts

The module also supports:
- OAuth redirect URI configuration
- Federated identity credentials for workload identity (OIDC)
- Certificate-based authentication
- Optional client secret generation

See [azure/teams-mcp-entra-application/README.md](azure/teams-mcp-entra-application/README.md) for detailed documentation.

### `azure/teams-mcp-secrets`

Manages secrets in Azure Key Vault required by Teams MCP:

**Auto-generated secrets** (when enabled):
- HMAC secret for token signing (64 characters)
- Webhook secret for Microsoft Graph subscriptions (128 characters)
- Encryption key for data at rest (256-bit AES key)

**Manual secrets** (placeholders created):
- Microsoft Entra client secret
- PostgreSQL database connection URL
- AMQP/RabbitMQ connection URL
- Public webhook URL for Microsoft Graph subscriptions
- Unique API base URL
- Self URL for OAuth callbacks
- Unique configuration (optional, for external or cluster_local modes)

See [azure/teams-mcp-secrets/README.md](azure/teams-mcp-secrets/README.md) for detailed documentation.

## Quick Start

### Prerequisites

- Terraform ~> 1.10
- Azure CLI authenticated with appropriate permissions
- An Azure Key Vault for storing secrets

### Example Usage

```hcl
# Configure the Azure provider
terraform {
  required_providers {
    azuread = {
      source  = "hashicorp/azuread"
      version = "~> 3"
    }
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4"
    }
  }
}

provider "azuread" {}
provider "azurerm" {
  features {}
}

# Create the Entra application
module "teams_mcp_app" {
  source = "./azure/teams-mcp-entra-application"

  display_name = "Unique AI Teams MCP - Production"
  redirect_uris = [
    "https://teams-mcp.example.com/auth/microsoft/callback"
  ]

  # Enable service principal and grant admin consent
  service_principal_configuration = {
    notes = "Service principal for Teams MCP production"
  }

  # Optional: Create a client secret
  create_client_secret = true

  # Optional: Configure federated identity for AKS workload identity
  federated_identity_credentials = {
    "production-aks-cluster" = {
      issuer  = "https://switzerlandnorth.oic.prod-aks.azure.com/<tenant_id>/<cluster_guid>/"
      subject = "system:serviceaccount:teams-mcp:teams-mcp-sa"
    }
  }
}

# Create secrets in Key Vault
module "teams_mcp_secrets" {
  source = "./azure/teams-mcp-secrets"

  key_vault_id = azurerm_key_vault.main.id

  # Auto-generate cryptographic secrets
  auto_generate_secrets = true
}

# Outputs
output "client_id" {
  value = module.teams_mcp_app.client_id
}

output "client_secret" {
  value     = module.teams_mcp_app.client_secret_value
  sensitive = true
}
```

### Post-Deployment Steps

1. **Set manual secrets** in Azure Key Vault:
   ```bash
   # Required secrets
   az keyvault secret set --vault-name <vault-name> \
     --name manual-teams-mcp-client-secret \
     --value "<client-secret-from-terraform-output>"

   az keyvault secret set --vault-name <vault-name> \
     --name manual-teams-mcp-database-url \
     --value "postgresql://user:pass@host:5432/dbname?sslmode=require"

   az keyvault secret set --vault-name <vault-name> \
     --name manual-teams-mcp-amqp-url \
     --value "amqp://user:pass@rabbitmq:5672/teams-mcp"

   az keyvault secret set --vault-name <vault-name> \
     --name manual-teams-mcp-public-webhook-url \
     --value "https://teams-mcp.example.com/webhooks/microsoft"

   az keyvault secret set --vault-name <vault-name> \
     --name manual-teams-mcp-unique-api-base-url \
     --value "https://api.unique.example.com"

   az keyvault secret set --vault-name <vault-name> \
     --name manual-teams-mcp-self-url \
     --value "https://teams-mcp.example.com"
   ```

2. **Configure your Teams MCP deployment** with the following environment variables:

   **Core Configuration:**
   - `AUTH_HMAC_SECRET`: From Key Vault `teams-mcp-hmac-secret`
   - `ENCRYPTION_KEY`: From Key Vault `teams-mcp-encryption-key`

   **Microsoft Configuration:**
   - `MICROSOFT_CLIENT_ID`: From Terraform output `client_id`
   - `MICROSOFT_CLIENT_SECRET`: From Key Vault `manual-teams-mcp-client-secret`
   - `MICROSOFT_WEBHOOK_SECRET`: From Key Vault `teams-mcp-webhook-secret`
   - `MICROSOFT_PUBLIC_WEBHOOK_URL`: From Key Vault `manual-teams-mcp-public-webhook-url`

   **Database Configuration:**
   - `DATABASE_URL`: From Key Vault `manual-teams-mcp-database-url`

   **AMQP Configuration:**
   - `AMQP_URL`: From Key Vault `manual-teams-mcp-amqp-url`

   **App Configuration:**
   - `SELF_URL`: From Key Vault `manual-teams-mcp-self-url`
   - `PORT`: (optional) Default is 9542
   - `NODE_ENV`: (optional) production/development/test
   - `LOG_LEVEL`: (optional) info/debug/trace

   **Unique Configuration:**
   - `UNIQUE_API_BASE_URL`: From Key Vault `manual-teams-mcp-unique-api-base-url`
   - `UNIQUE_API_VERSION`: (optional) Default is 2023-12-06
   - `UNIQUE_ROOT_SCOPE_PATH`: (optional) Default is Teams-MCP
   - `UNIQUE_SERVICE_AUTH_MODE`: cluster_local or external
   - For external mode: `UNIQUE_APP_KEY`, `UNIQUE_APP_ID`, `UNIQUE_AUTH_USER_ID`, `UNIQUE_AUTH_COMPANY_ID`
   - For cluster_local mode: `UNIQUE_SERVICE_EXTRA_HEADERS`, `UNIQUE_INGESTION_SERVICE_BASE_URL`

3. **Grant the application access** to Microsoft Graph API by visiting the Azure Portal and granting admin consent, or use the Terraform module with `service_principal_configuration` to automatically grant consent.

## Security Considerations

- The client secret is sensitive and should be stored securely
- Auto-generated secrets (HMAC, webhook, encryption) are stored in Key Vault
- Consider using managed identities or federated credentials instead of client secrets when possible
- Ensure your Terraform state is encrypted and access-controlled
- Rotate secrets regularly according to your security policy

## Architecture Notes

- The Teams MCP application uses **application permissions** (not delegated) to access Microsoft Graph
- OAuth redirect URIs are required for user authentication flow
- Webhook secret must be exactly 128 characters for Microsoft Graph subscriptions
- Encryption key must be 32 bytes (256 bits) for AES-256-GCM encryption

## Related Documentation

- [Microsoft Graph API Permissions](https://learn.microsoft.com/en-us/graph/permissions-reference)
- [Azure Workload Identity](https://azure.github.io/azure-workload-identity/)
- [Teams MCP Configuration Guide](../../README.md)
