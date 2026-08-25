terraform {
  # TRAP: `~> 1.10` is load-bearing here, not housekeeping. The tool-selection validations in
  # variables.tf reference `local.tool_names` and `local.presets`; before Terraform 1.9.0 a
  # validation could only reference its own variable. Relaxing this constraint turns five specific,
  # actionable error messages into "The condition for variable ... can only refer to the variable
  # itself" and the module stops loading at all.
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
