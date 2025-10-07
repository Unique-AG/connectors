> [!WARNING]
> This module is **EXPERIMENTAL**. Unique reserves the right to move, breakingly refactor, or deprecate the module at any stage without notice.

This module might also eventually evolve into (Unique-AG/terraform-modules)[https://github.com/Unique-AG/terraform-modules].

## USP
This module is living documentation and provides the least possible application registration / service principals.
Clients and users are not required to use this module per se. Any means to create the application works just as well and this versioned module can be referenced as documentation for such cases.

## Requirements

- Module just creates the principal, the workload must be deployed separately.
- Once installed, a Application or Global Administrator must grant the permissions via the Azure Portal as this step can't be automated and the permissions aren't `Delegated` but `Application`

---

No further docs are provided for `EXPERIMENTAL` features.