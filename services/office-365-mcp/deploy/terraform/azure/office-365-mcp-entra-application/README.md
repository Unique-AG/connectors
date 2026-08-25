> [!WARNING]
> This module is **ALPHA**. Unique reserves the right to move, breakingly refactor, or deprecate the module at any stage without notice.

The Entra application registration users sign in to `office-365-mcp` through. Self-enclosed: it
depends on no other module, and the caller supplies Azure ids, names, and a tool selection.

## The tool selection is the permission selection

The caller never writes a Graph scope. It sets **exactly one** of `tools_preset` or `tools_enabled`,
spelled the way the pod's `TOOLS_PRESET` / `TOOLS_ENABLED` are spelled, and the module derives the
delegated Graph permission set from it — the same way `src/office_365_mcp/tools/__init__.py:resolve()`
does: the `get_me` floor joins every selection, the selection is filtered over the tool registry's
order rather than the caller's, and duplicates fold back to first occurrence.

There is deliberately no default. A default of "every tool" would make the widest consent screen
what an operator gets by not choosing, which is the whole of what the knob exists to stop; `teams`
keeps "everything" a one-word but chosen value.

`registry.tf` is the module's own copy of that registry, and
`services/office-365-mcp/tests/test_terraform_surface.py` fails the moment it and the Python
disagree — including the presets, the closed set of permissions this connector may ask for, and
which of them need an Entra administrator. `tests/surface.tftest.hcl` checks the derivation itself,
credential-free, under `terraform test`.

## Apply order: this is two acts, not one

The registration is written here; the pod's selection is written by an Argo overlay in another
repository. The tenant-wide grant this module writes is replaced wholesale on every apply, so the
safe order **reverses with the direction of the change**:

| Change | Order |
| --- | --- |
| Widening the surface | `terraform apply` here **first**, then bump the overlay |
| Narrowing the surface | bump the overlay **first**, then `terraform apply` here |

Backwards, in either direction, is a sign-in outage: a permission the registration does not carry
fails at the *authorize* hop for every user — an unknown scope outright, an unconsented
admin-consent permission at "Need admin approval" — with nothing in the pod's logs. Nothing inside
the server can compare its own ask with this registration.

`deployment_env` publishes `TOOLS_ENABLED` (the resolved expansion) and never `TOOLS_PRESET`, on
purpose: `teams` is derived from the tool registry in the pod too, so an overlay pinned to a preset
name widens itself on a chart bump — past a registration nobody re-applied — on an Argo sync alone.
Pinning the expansion makes the safe order the default rather than a convention.

## One registration is one tool surface

An app registration carries one `required_resource_access` and one delegated permission grant, so
`confidential_clients` means "the environments that agree on one tool surface". Two surfaces are two
module blocks, each with its own `display_name` and its own `secret_name_prefix`.

Three things keep those two blocks from overwriting one another, and it is worth being exact about
which failure each one closes:

- **`secret_name_prefix` is required, with no default.** The sibling modules default their prefix to
  their own service name and every caller takes that default, so two registrations of one service
  collide the moment their environment keys overlap. Requiring the value means a collision cannot be
  inherited by accident.
- **It must start with `office-365-mcp`.** Requiring the value alone would still accept
  `secret_name_prefix = "teams-mcp"`, which composes exactly the name teams-mcp's own module writes
  into the same shared vault — a clean plan that overwrites another service's live secret. The pin
  makes a cross-service collision impossible rather than merely deliberate; the distinguishing axis
  goes in the suffix.
- **`prevent_duplicate_names = true`** asks the provider to refuse a second registration with the
  same `display_name` at create. Entra itself permits duplicates. This only guards create, so a
  rename onto an existing name is still not caught.

What none of them prevents is two module blocks with different prefixes and different names deployed
to the same host: that is what the distinct-`public_base_url` validation is for.

## After the first apply

1. Check in Entra → App registrations that the permissions show as `Configured permissions` and that
   they are `Granted`. If they are not, grant them (button, or the `admin_consent_url` output) and
   please open an issue — it is not yet fully clear how Azure resolves this.
2. The application is created with its `identifierUris` empty and the URI is added by a second
   resource, because `api://<its own client_id>` cannot be written on the resource that mints the
   client id. If Graph ever rejects that create, a second apply completes it — it is not a redesign.
3. `curl $PUBLIC_BASE_URL/manifest` on the deployed pod and diff its permission line against
   `terraform output tool_surface`. CI proves the two *tables* agree within one commit of
   `connectors`; this is the only check that the overlay and the selection here were set to the same
   selection.
4. If sign-in shows an unexpected consent prompt for `api://<client_id>/access_as_user`, the likely
   fix is one `azuread_application_pre_authorized` resource for the app's own client id. It is not
   shipped because it is plausibly rejected by Graph when client and resource are the same
   application, and that could not be settled without a tenant.

Two things this module deliberately does not do: generate any secret other than the client secret
(this service has exactly one — `ENTRA_CLIENT_SECRET`, which is also the key material for its OAuth
rows in Postgres, so rotating it costs every signed-in user one re-login; the database URL comes from
CloudNativePG in-cluster), and accept a permission name anywhere in its interface.
