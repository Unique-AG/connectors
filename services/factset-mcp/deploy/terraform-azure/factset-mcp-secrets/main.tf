resource "azurerm_key_vault_secret" "manual_secret" {
  for_each        = var.secrets_placeholders
  content_type    = lookup(each.value, "content_type", "text/plain")
  expiration_date = lookup(each.value, "expiration_date", "2099-12-31T23:59:59Z")
  key_vault_id    = var.key_vault_id
  name            = "manual-${each.key}"
  value           = "<TO BE SET MANUALLY>"
  lifecycle {
    ignore_changes = [value, tags, content_type]
  }
}

resource "random_password" "hmac_secret" {
  keepers = { version = 1 }
  length  = 32
  special = false
}

resource "azurerm_key_vault_secret" "hmac_secret" {
  content_type    = "text/plain"
  expiration_date = "2099-12-31T23:59:59Z"
  key_vault_id    = var.key_vault_id
  name            = "factset-hmac-secret"
  value           = random_password.hmac_secret.result
}

resource "random_id" "encryption_key" {
  byte_length = 32
  keepers     = { version = 1 }
}

resource "azurerm_key_vault_secret" "encryption_key" {
  content_type    = "text/hex"
  expiration_date = "2099-12-31T23:59:59Z"
  key_vault_id    = var.key_vault_id
  name            = "factset-encryption-key"
  value           = random_id.encryption_key.hex
}

resource "random_password" "psql_password" {
  keepers = { version = 1 }
  length  = 32
  special = false
}

resource "azurerm_key_vault_secret" "psql_password" {
  content_type    = "text/plain"
  expiration_date = "2099-12-31T23:59:59Z"
  key_vault_id    = var.key_vault_id
  name            = "factset-psql-password"
  value           = random_password.psql_password.result
}
