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
# @description Shared api-key protecting the /mcp endpoint (passed as the `api-key` query parameter)
# @length 32 byte hex (64 hex chars)
# @type random_bytes#hex
# @env MCP_API_KEY
# ---
resource "random_bytes" "hex_mcp_api_key" {
  keepers = { version = var.secrets_to_create.hex_mcp_api_key.rotation_counter }
  length  = coalesce(var.secrets_to_create.hex_mcp_api_key.length, 32)
}
resource "azurerm_key_vault_secret" "hex_mcp_api_key" {
  count           = var.secrets_to_create.hex_mcp_api_key.create ? 1 : 0
  name            = var.secrets_to_create.hex_mcp_api_key.name
  value           = random_bytes.hex_mcp_api_key.hex
  content_type    = var.secrets_to_create.hex_mcp_api_key.content_type
  key_vault_id    = coalesce(var.key_vault_sensitive_id, var.key_vault_id)
  expiration_date = var.secrets_to_create.hex_mcp_api_key.expiration_date
}
