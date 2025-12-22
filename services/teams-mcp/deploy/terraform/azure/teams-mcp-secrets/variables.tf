variable "key_vault_id" {
  description = "The ID of the key vault, all created secrets will be placed here."
  type        = string
}

variable "secrets_placeholders" {
  description = "Map of secrets that are manually created and need to be placed in the core key vault. The manual- prefix is prepended automatically."
  type = map(object({
    create          = optional(bool, true)
    expiration_date = optional(string, "2099-12-31T23:59:59Z")
  }))
  default = {
    /**
      Manual secrets that need to be set based on Teams MCP configuration:

      Microsoft Configuration (microsoft.config.ts):
      - teams-mcp-client-secret: The Microsoft Entra application client secret (MICROSOFT_CLIENT_SECRET)
      - teams-mcp-public-webhook-url: Public webhook URL for Microsoft Graph subscriptions (MICROSOFT_PUBLIC_WEBHOOK_URL)

      Database Configuration (database.config.ts):
      - teams-mcp-database-url: PostgreSQL connection URL (DATABASE_URL)

      AMQP Configuration (amqp.config.ts):
      - teams-mcp-amqp-url: AMQP/RabbitMQ connection URL (AMQP_URL)

      Unique Configuration (unique.config.ts):
      The config uses a discriminated union based on serviceAuthMode (cluster_local or external).
      Both modes use serviceExtraHeaders as a JSON object containing auth-related headers.
      - teams-mcp-unique-service-extra-headers: JSON object with auth headers (UNIQUE_SERVICE_EXTRA_HEADERS)
        For cluster_local: {"x-company-id": "...", "x-user-id": "..."}
        For external: {"authorization": "Bearer ...", "x-app-id": "...", "x-user-id": "...", "x-company-id": "..."}

      NOTE: Non-sensitive URLs should be configured via Helm values instead of Key Vault:
      - UNIQUE_API_BASE_URL -> mcpConfig.unique.apiBaseUrl
      - UNIQUE_INGESTION_SERVICE_BASE_URL -> mcpConfig.unique.ingestionServiceBaseUrl

      App Configuration (app.config.ts):
      NOTE: Non-sensitive URLs should be configured via Helm values instead of Key Vault:
      - SELF_URL -> mcpConfig.app.selfUrl
    */
    teams-mcp-client-secret              = { create = true, expiration_date = "2099-12-31T23:59:59Z" }
    teams-mcp-database-url               = { create = true, expiration_date = "2099-12-31T23:59:59Z" }
    teams-mcp-amqp-url                   = { create = true, expiration_date = "2099-12-31T23:59:59Z" }
    teams-mcp-public-webhook-url         = { create = true, expiration_date = "2099-12-31T23:59:59Z" }
    teams-mcp-unique-service-extra-headers = { create = true, expiration_date = "2099-12-31T23:59:59Z" }
  }
}

variable "auto_generate_secrets" {
  description = "Whether to auto-generate cryptographic secrets (HMAC secret, webhook secret, encryption key). Set to false if you want to manage these manually."
  type        = bool
  default     = true
}
