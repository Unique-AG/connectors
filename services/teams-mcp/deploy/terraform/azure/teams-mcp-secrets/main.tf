resource "azurerm_key_vault_secret" "manual_secret" {
  for_each        = var.secrets_placeholders
  content_type    = lookup(each.value, "content_type", "text/plain")
  expiration_date = lookup(each.value, "expiration_date", "2099-12-31T23:59:59Z")
  key_vault_id    = var.key_vault_id
  name            = "manual-${each.key}"
  value           = "<TO BE SET MANUALLY>"
  lifecycle {
    ignore_changes = [value, tags, content_type, expiration_date]
  }
}

# Auto-generated secrets using random providers
resource "random_password" "hmac_secret" {
  count   = var.auto_generate_secrets ? 1 : 0
  length  = 64
  special = true
}

resource "random_password" "webhook_secret" {
  count   = var.auto_generate_secrets ? 1 : 0
  length  = 128
  special = false # Webhook secret should be alphanumeric only
}

resource "random_id" "encryption_key" {
  count       = var.auto_generate_secrets ? 1 : 0
  byte_length = 32 # 256 bits for AES-256
}

# Store auto-generated secrets in Key Vault
resource "azurerm_key_vault_secret" "hmac_secret" {
  count           = var.auto_generate_secrets ? 1 : 0
  key_vault_id    = var.key_vault_id
  name            = "teams-mcp-hmac-secret"
  value           = random_password.hmac_secret[0].result
  expiration_date = "2099-12-31T23:59:59Z"
  content_type    = "text/plain"
}

resource "azurerm_key_vault_secret" "webhook_secret" {
  count           = var.auto_generate_secrets ? 1 : 0
  key_vault_id    = var.key_vault_id
  name            = "teams-mcp-webhook-secret"
  value           = random_password.webhook_secret[0].result
  expiration_date = "2099-12-31T23:59:59Z"
  content_type    = "text/plain"
}

resource "azurerm_key_vault_secret" "encryption_key" {
  count           = var.auto_generate_secrets ? 1 : 0
  key_vault_id    = var.key_vault_id
  name            = "teams-mcp-encryption-key"
  value           = random_id.encryption_key[0].hex
  expiration_date = "2099-12-31T23:59:59Z"
  content_type    = "text/plain"
}
