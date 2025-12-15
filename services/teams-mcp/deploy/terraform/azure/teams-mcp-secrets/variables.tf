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
      - teams-mcp-unique-api-base-url: Unique Public API base URL (UNIQUE_API_BASE_URL)
      - teams-mcp-unique-service-extra-headers: Extra headers for cluster_local mode (UNIQUE_SERVICE_EXTRA_HEADERS) - optional
      - teams-mcp-unique-ingestion-service-base-url: Ingestion service URL for cluster_local mode (UNIQUE_INGESTION_SERVICE_BASE_URL) - optional
      - teams-mcp-unique-app-key: API key for external mode (UNIQUE_APP_KEY) - optional
      - teams-mcp-unique-app-id: App ID for external mode (UNIQUE_APP_ID) - optional
      - teams-mcp-unique-auth-user-id: User ID for external mode (UNIQUE_AUTH_USER_ID) - optional
      - teams-mcp-unique-auth-company-id: Company ID for external mode (UNIQUE_AUTH_COMPANY_ID) - optional

      App Configuration (app.config.ts):
      - teams-mcp-self-url: The URL of the MCP Server for OAuth callbacks (SELF_URL)
    */
    teams-mcp-client-secret           = { create = true, expiration_date = "2099-12-31T23:59:59Z" }
    teams-mcp-database-url            = { create = true, expiration_date = "2099-12-31T23:59:59Z" }
    teams-mcp-amqp-url                = { create = true, expiration_date = "2099-12-31T23:59:59Z" }
    teams-mcp-public-webhook-url      = { create = true, expiration_date = "2099-12-31T23:59:59Z" }
    teams-mcp-unique-api-base-url     = { create = true, expiration_date = "2099-12-31T23:59:59Z" }
    teams-mcp-self-url                = { create = true, expiration_date = "2099-12-31T23:59:59Z" }
    # Optional secrets for Unique configuration (external mode)
    teams-mcp-unique-app-key          = { create = false, expiration_date = "2099-12-31T23:59:59Z" }
    teams-mcp-unique-app-id           = { create = false, expiration_date = "2099-12-31T23:59:59Z" }
    teams-mcp-unique-auth-user-id     = { create = false, expiration_date = "2099-12-31T23:59:59Z" }
    teams-mcp-unique-auth-company-id  = { create = false, expiration_date = "2099-12-31T23:59:59Z" }
    # Optional secrets for Unique configuration (cluster_local mode)
    teams-mcp-unique-service-extra-headers        = { create = false, expiration_date = "2099-12-31T23:59:59Z" }
    teams-mcp-unique-ingestion-service-base-url   = { create = false, expiration_date = "2099-12-31T23:59:59Z" }
  }
}

variable "auto_generate_secrets" {
  description = "Whether to auto-generate cryptographic secrets (HMAC secret, webhook secret, encryption key). Set to false if you want to manage these manually."
  type        = bool
  default     = true
}
