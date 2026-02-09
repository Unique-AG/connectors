resource "azurerm_key_vault_secret" "manual_secret" {
  for_each        = { for k, v in var.secrets_placeholders : k => v if v.create }
  content_type    = lookup(each.value, "content_type", "text/plain")
  expiration_date = lookup(each.value, "expiration_date", "2099-12-31T23:59:59Z")
  key_vault_id    = var.key_vault_id
  name            = "manual-${each.key}"
  value           = "<TO BE SET MANUALLY>"
  lifecycle {
    ignore_changes = [value, tags, content_type, expiration_date]
  }
}

# ---
# @description HMAC secret for token signing
# @length 32 byte hex (64 hex chars)
# @type random_bytes#hex
# @env AUTH_HMAC_SECRET
# ---
resource "random_bytes" "hex_hmac_secret" {
  keepers = { version = var.secrets_to_create.hex_hmac_secret.rotation_counter }
  length  = coalesce(var.secrets_to_create.hex_hmac_secret.length, 32)
}
resource "azurerm_key_vault_secret" "hex_hmac_secret" {
  count           = var.secrets_to_create.hex_hmac_secret.create ? 1 : 0
  name            = var.secrets_to_create.hex_hmac_secret.name
  value           = random_bytes.hex_hmac_secret.hex
  content_type    = var.secrets_to_create.hex_hmac_secret.content_type
  key_vault_id    = coalesce(var.key_vault_sensitive_id, var.key_vault_id)
  expiration_date = var.secrets_to_create.hex_hmac_secret.expiration_date
}

# ---
# @description Webhook secret for Microsoft webhook validation (spoof protection)
# @length 64 byte hex (128 hex chars)
# @type random_bytes#hex
# @env MICROSOFT_WEBHOOK_SECRET
# ---
resource "random_bytes" "hex_webhook_secret" {
  keepers = { version = var.secrets_to_create.hex_webhook_secret.rotation_counter }
  length  = coalesce(var.secrets_to_create.hex_webhook_secret.length, 64)
}
resource "azurerm_key_vault_secret" "hex_webhook_secret" {
  count           = var.secrets_to_create.hex_webhook_secret.create ? 1 : 0
  name            = var.secrets_to_create.hex_webhook_secret.name
  value           = random_bytes.hex_webhook_secret.hex
  content_type    = var.secrets_to_create.hex_webhook_secret.content_type
  key_vault_id    = coalesce(var.key_vault_sensitive_id, var.key_vault_id)
  expiration_date = var.secrets_to_create.hex_webhook_secret.expiration_date
}

# ---
# @description Encryption key for encrypting stored data (AES-256)
# @length 32 byte hex (64 hex chars / 256 bits)
# @type random_bytes#hex
# @env ENCRYPTION_KEY
# ---
resource "random_bytes" "hex_encryption_key" {
  keepers = { version = var.secrets_to_create.hex_encryption_key.rotation_counter }
  length  = coalesce(var.secrets_to_create.hex_encryption_key.length, 32)
}
resource "azurerm_key_vault_secret" "hex_encryption_key" {
  count           = var.secrets_to_create.hex_encryption_key.create ? 1 : 0
  name            = var.secrets_to_create.hex_encryption_key.name
  value           = random_bytes.hex_encryption_key.hex
  content_type    = var.secrets_to_create.hex_encryption_key.content_type
  key_vault_id    = coalesce(var.key_vault_sensitive_id, var.key_vault_id)
  expiration_date = var.secrets_to_create.hex_encryption_key.expiration_date
}
