terraform {
  required_version = "~> 1.10"
  required_providers {
    azuread = {
      source  = "hashicorp/azuread"
      version = "~> 3"
    }
    azurerm = {
      source = "hashicorp/azurerm"
      # Allow v4 or v5 (not v6+): this module only uses azurerm_key_vault_secret,
      # whose schema is stable across both majors. A hard `~> 5` made the module
      # unconsumable by stacks still on v4 — the infrastructure identity stack pins
      # azurerm ~> 4.15 — so keep it compatible with both until the estate migrates.
      version = ">= 4, < 6"
    }
    time = {
      source  = "hashicorp/time"
      version = "~> 0.12"
    }
  }
}
