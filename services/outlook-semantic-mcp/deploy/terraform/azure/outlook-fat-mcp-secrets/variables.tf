variable "key_vault_id" {
  description = "The ID of the key vault, all created secrets will be placed here."
  type        = string
}

variable "key_vault_sensitive_id" {
  description = "The ID of the sensitive key vault for auto-generated secrets. If set, takes precedence over key_vault_id for secrets_to_create. Pass null to use key_vault_id."
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
      Manual secrets that need to be set based on Outlook Semantic MCP configuration:

      Microsoft Configuration (microsoft.config.ts):
      - outlook-semantic-mcp-client-secret: The Microsoft Entra application client secret (MICROSOFT_CLIENT_SECRET)

      Database Configuration (database.config.ts):
      - outlook-semantic-mcp-database-url: PostgreSQL connection URL (DATABASE_URL)

      AMQP Configuration (amqp.config.ts):
      - outlook-semantic-mcp-amqp-url: AMQP/RabbitMQ connection URL (AMQP_URL)
    */
    outlook-semantic-mcp-client-secret = { create = true, expiration_date = "2099-12-31T23:59:59Z" }
    outlook-semantic-mcp-database-url  = { create = true, expiration_date = "2099-12-31T23:59:59Z" }
    outlook-semantic-mcp-amqp-url      = { create = true, expiration_date = "2099-12-31T23:59:59Z" }
  }
}

variable "secrets_to_create" {
  description = "List of secrets that are automatically generated and should be placed in the sensitive key vault. Increment a counter to rotate the secret."
  type = map(object({
    content_type     = optional(string, "text/plain")
    create           = optional(bool, true)
    expiration_date  = optional(string, "2099-12-31T23:59:59Z")
    length           = optional(number)
    name             = optional(string)
    rotation_counter = optional(number, 0)
  }))
  default = {
    /**
      Auto-generated secrets (hex output from random_id):

      Secret format requirements (from src/config/*.config.ts and .env.example):
      - HMAC Secret: 64-char hex (openssl rand -hex 32) -> length=32
      - Webhook Secret: 128-char hex (openssl rand -hex 64) -> length=64
      - Encryption Key: 64-char hex / 32 bytes (openssl rand -hex 32) -> length=32
    */
    hex_hmac_secret    = { create = true, name = "outlook-semantic-mcp-hmac-secret", content_type = "text/hex", rotation_counter = 0, expiration_date = "2099-12-31T23:59:59Z" }
    hex_webhook_secret = { create = true, name = "outlook-semantic-mcp-webhook-secret", content_type = "text/hex", rotation_counter = 0, expiration_date = "2099-12-31T23:59:59Z" }
    hex_encryption_key = { create = true, name = "outlook-semantic-mcp-encryption-key", content_type = "text/hex", rotation_counter = 0, expiration_date = "2099-12-31T23:59:59Z" }
  }
}
