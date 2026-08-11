terraform {
  required_version = "~> 1.10"
  required_providers {
    azurerm = {
      source = "hashicorp/azurerm"
      # Allow v4 or v5 (not v6+): this module only uses azurerm_key_vault_secret,
      # whose schema is stable across both majors. A hard `~> 5` made the module
      # unconsumable by stacks still on v4, so keep it compatible with both until
      # the estate migrates.
      version = ">= 4, < 6"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4"
    }
  }
}
