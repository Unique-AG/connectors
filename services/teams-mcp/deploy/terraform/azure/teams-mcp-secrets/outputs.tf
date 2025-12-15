output "hmac_secret_name" {
  description = "The name of the HMAC secret in Key Vault. Null if auto-generation is disabled."
  value       = var.auto_generate_secrets ? azurerm_key_vault_secret.hmac_secret[0].name : null
}

output "webhook_secret_name" {
  description = "The name of the webhook secret in Key Vault. Null if auto-generation is disabled."
  value       = var.auto_generate_secrets ? azurerm_key_vault_secret.webhook_secret[0].name : null
}

output "encryption_key_name" {
  description = "The name of the encryption key in Key Vault. Null if auto-generation is disabled."
  value       = var.auto_generate_secrets ? azurerm_key_vault_secret.encryption_key[0].name : null
}

output "manual_secrets" {
  description = "List of manual secret names that need to be populated."
  value       = [for k, v in var.secrets_placeholders : "manual-${k}" if v.create]
}
