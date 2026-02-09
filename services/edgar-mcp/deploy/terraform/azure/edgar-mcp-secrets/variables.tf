variable "key_vault_id" {
  description = "The ID of the key vault, all created secrets will be placed here."
  type        = string
}

variable "secrets_placeholders" {
  description = "Map of secrets that are manually created and need to be placed in the core key vault. The manual- prefix is prepended automatically."
  type = map(object({
    content_type    = optional(string, "text/plain")
    create          = optional(bool, true)
    expiration_date = optional(string, "2099-12-31T23:59:59Z")
  }))
  default = {
    /**
      Manual secrets that need to be set based on Edgar MCP configuration:

      Database Configuration (config.py):
      - edgar-mcp-database-url: PostgreSQL connection URL (DB_URL)

      RabbitMQ Configuration (config.py):
      - edgar-mcp-rabbitmq-url: AMQP/RabbitMQ connection URL (RABBITMQ_URL)
    */
    edgar-mcp-database-url = { create = true, expiration_date = "2099-12-31T23:59:59Z" }
    edgar-mcp-rabbitmq-url = { create = true, expiration_date = "2099-12-31T23:59:59Z" }
  }
}
