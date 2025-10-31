> [!WARNING]
> This module is **EXPERIMENTAL**. Unique reserves the right to move, breakingly refactor, or deprecate the module at any stage without notice.

This module might also eventually evolve into (Unique-AG/terraform-modules)[https://github.com/Unique-AG/terraform-modules].

## USP
This module is living documentation and provides the least possible application registration / service principals.
Clients and users are not required to use this module per se. Any means to create the application works just as well and this versioned module can be referenced as documentation for such cases.

## Requirements

- Module just creates the principal, the workload must be deployed separately.

## Setup steps
It is not yet 100% clear how Azure resolves the permissions and assignments.

After applying the module, one must check in Entra Application Registrations that the permissions are `Configured permissions` and that they are `Granted`.

If they are not, make them by Click and please open an issue.

---

No further docs are provided for `EXPERIMENTAL` features.