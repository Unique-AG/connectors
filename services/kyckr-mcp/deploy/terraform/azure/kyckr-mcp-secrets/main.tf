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
# @description Shared bearer token protecting the /mcp endpoint
# @length 32 byte hex (64 hex chars)
# @type random_bytes#hex
# @env KYCKR_MCP_ACCESS_TOKEN
# ---
resource "random_bytes" "hex_mcp_access_token" {
  keepers = { version = var.secrets_to_create.hex_mcp_access_token.rotation_counter }
  length  = coalesce(var.secrets_to_create.hex_mcp_access_token.length, 32)
}
resource "azurerm_key_vault_secret" "hex_mcp_access_token" {
  count           = var.secrets_to_create.hex_mcp_access_token.create ? 1 : 0
  name            = var.secrets_to_create.hex_mcp_access_token.name
  value           = random_bytes.hex_mcp_access_token.hex
  content_type    = var.secrets_to_create.hex_mcp_access_token.content_type
  key_vault_id    = coalesce(var.key_vault_sensitive_id, var.key_vault_id)
  expiration_date = var.secrets_to_create.hex_mcp_access_token.expiration_date
}
