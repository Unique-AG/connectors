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

# Auto-generated secrets using random_bytes (hex output)
#
# All secrets use random_bytes with .hex output to match the documented format:
# - openssl rand -hex N produces 2*N hex characters
# - random_bytes with length=N and .hex produces 2*N hex characters
#
# Secret format requirements (from src/config/*.config.ts and .env.example):
# - HMAC Secret: 64-char hex (openssl rand -hex 32) -> random_bytes length=32
# - Webhook Secret: 128-char hex (openssl rand -hex 64) -> random_bytes length=64
# - Encryption Key: 64-char hex / 32 bytes (openssl rand -hex 32) -> random_bytes length=32

resource "random_bytes" "hmac_secret" {
  length = 32 # Outputs 64 hex chars via .hex
  # Maps to AUTH_HMAC_SECRET - used for HMAC token signing
}

resource "random_bytes" "webhook_secret" {
  length = 64 # Outputs 128 hex chars via .hex
  # Maps to MICROSOFT_WEBHOOK_SECRET - used for webhook validation (spoof protection)
}

resource "random_bytes" "encryption_key" {
  length = 32 # 256 bits for AES-256, outputs 64 hex chars via .hex
  # Maps to ENCRYPTION_KEY - used for encrypting stored data
}

# Store auto-generated secrets in Key Vault
resource "azurerm_key_vault_secret" "hmac_secret" {
  key_vault_id    = var.key_vault_id
  name            = "teams-mcp-hmac-secret"
  value           = random_bytes.hmac_secret.hex
  expiration_date = "2099-12-31T23:59:59Z"
  content_type    = "text/hex"
}

resource "azurerm_key_vault_secret" "webhook_secret" {
  key_vault_id    = var.key_vault_id
  name            = "teams-mcp-webhook-secret"
  value           = random_bytes.webhook_secret.hex
  expiration_date = "2099-12-31T23:59:59Z"
  content_type    = "text/hex"
}

resource "azurerm_key_vault_secret" "encryption_key" {
  key_vault_id    = var.key_vault_id
  name            = "teams-mcp-encryption-key"
  value           = random_bytes.encryption_key.hex
  expiration_date = "2099-12-31T23:59:59Z"
  content_type    = "text/hex"
}
