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
