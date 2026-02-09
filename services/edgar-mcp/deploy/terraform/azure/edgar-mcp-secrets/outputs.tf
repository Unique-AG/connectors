output "manual_secrets" {
  description = "List of manual secrets with name and resource ID."
  value = [
    for _, v in azurerm_key_vault_secret.manual_secret : {
      name = v.name
      id   = v.id
    }
  ]
}
