terraform {
  # 1.9.0 is the first version where a variable validation may reference anything but its own
  # variable; the tool-selection validations read `local.tool_names` and `local.presets`.
  required_version = "~> 1.10"

  required_providers {
    azuread = {
      source  = "hashicorp/azuread"
      version = "~> 3"
    }
    azurerm = {
      source  = "hashicorp/azurerm"
      version = ">= 4, < 6"
    }
    time = {
      source  = "hashicorp/time"
      version = "~> 0.12"
    }
  }
}
