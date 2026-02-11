output "manual_secrets" {
  description = "List of manual secrets with name and resource ID."
  value = [
    for k, v in azurerm_key_vault_secret.manual_secret : {
      name = v.name
      id   = v.id
    }
  ]
}

output "sensitive_secrets" {
  description = "List of sensitive (auto-generated) secrets with name and resource ID."
  value = concat(
    [for s in azurerm_key_vault_secret.hex_hmac_secret : {
      name = s.name
      id   = s.id
    }],
    [for s in azurerm_key_vault_secret.hex_webhook_secret : {
      name = s.name
      id   = s.id
    }],
    [for s in azurerm_key_vault_secret.hex_encryption_key : {
      name = s.name
      id   = s.id
    }]
  )
}
