terraform {
  required_version = ">= 1.11" # else ephemeral resources are not supported
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3"
    }
  }
}
