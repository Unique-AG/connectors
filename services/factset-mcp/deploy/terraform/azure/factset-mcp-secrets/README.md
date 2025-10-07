> [!WARNING]
> This module is **EXPERIMENTAL**. Unique reserves the right to move, breakingly refactor, or deprecate the module at any stage without notice.

This module might also eventually evolve into (Unique-AG/terraform-modules)[https://github.com/Unique-AG/terraform-modules].

## Requirements

Outside the module you must create:

- `resource.azurerm_key_vault` for input
- `resource.azurerm_user_assigned_identity` as Workload Identity
- `resource.azurerm_role_assignment` for the identity to read the KV
- `resource.azurerm_federated_identity_credential` for Service Account / Workload to read the secret
- `output.azurerm_user_assigned_identity.clientId` to know the clientId for the Service Account / Workload
- means for humans to set the manual secrets (PIM…)

---

No further docs are provided for `EXPERIMENTAL` features.