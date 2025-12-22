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

      Database Configuration (database.config.ts):
      - teams-mcp-database-url: PostgreSQL connection URL (DATABASE_URL)

      AMQP Configuration (amqp.config.ts):
      - teams-mcp-amqp-url: AMQP/RabbitMQ connection URL (AMQP_URL)

      Auto-generated secrets (see main.tf):
      - teams-mcp-hmac-secret: 64-char hex (AUTH_HMAC_SECRET)
      - teams-mcp-webhook-secret: 128-char hex (MICROSOFT_WEBHOOK_SECRET)
      - teams-mcp-encryption-key: 64-char hex (ENCRYPTION_KEY)

      NOTE: Non-sensitive values should be configured via Helm values instead of Key Vault:
      - SELF_URL -> mcpConfig.app.selfUrl
      - MICROSOFT_PUBLIC_WEBHOOK_URL -> mcpConfig.microsoft.publicWebhookUrl
      - UNIQUE_API_BASE_URL -> mcpConfig.unique.apiBaseUrl
      - UNIQUE_INGESTION_SERVICE_BASE_URL -> mcpConfig.unique.ingestionServiceBaseUrl
      - UNIQUE_SERVICE_EXTRA_HEADERS -> mcpConfig.unique.serviceExtraHeaders
    */
    teams-mcp-client-secret = { create = true, expiration_date = "2099-12-31T23:59:59Z" }
    teams-mcp-database-url  = { create = true, expiration_date = "2099-12-31T23:59:59Z" }
    teams-mcp-amqp-url      = { create = true, expiration_date = "2099-12-31T23:59:59Z" }
  }
}
