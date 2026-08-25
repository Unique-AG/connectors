variable "tools_preset" {
  description = <<-EOT
    Which tools this deployment runs, as a named surface — the pod's TOOLS_PRESET, spelled the same
    way (`config.ToolsPreset` is lowercase-only, because the chart's schema carries these values as
    a JSON Schema enum, which has no case-insensitive form).
    The tools selected decide which delegated Microsoft Graph permissions EVERY user of this
    connector consents to at sign-in, so there is deliberately no default: "every tool" has to be a
    choice (`teams`) rather than what a caller gets by not making one.
    Set this or tools_enabled, never both, never neither.
    Narrowing a live registration costs nothing. Widening one adds a permission to the authorize
    request, so every signed-in user meets AADSTS65001 on the new tool until they sign in again —
    apply HERE BEFORE the overlay when widening, and AFTER it when narrowing (README, "Apply order").
  EOT
  type        = string
  default     = null

  validation {
    # `coalesce` skips empty strings as well as nulls, so the sentinel has to be non-empty —
    # `coalesce(null, "")` is itself an error, which would replace this message with an internal
    # function failure. `contains` errors outright on a null needle, hence the guard.
    condition     = var.tools_preset == null || contains(keys(local.presets), coalesce(var.tools_preset, "<unset>"))
    error_message = "tools_preset names no surface this connector has. Valid presets: ${join(", ", sort(keys(local.presets)))}."
  }
}

variable "tools_enabled" {
  description = <<-EOT
    Which tools this deployment runs, named individually, for a surface no preset covers — the pod's
    TOOLS_ENABLED, as a list rather than a comma-separated string. `get_me` is always on and need
    not be listed; naming it explicitly is accepted, not an error.
    Order is irrelevant: the selection is filtered over the tool registry's order, so
    ["read_message", "list_chats"] and ["list_chats", "read_message"] produce one identical
    permission set — the same guarantee the pod makes.
    Set this or tools_preset, never both, never neither.
  EOT
  type        = list(string)
  default     = null

  # Five validations, one message each, transcribed from `SurfaceConfig._require_exactly_one_selection`
  # and `_every_name_known`. A single XOR condition would cover the first two, but it could only
  # carry one message — and which of the two mistakes was made is the whole of what the operator
  # needs told. They live on THIS variable rather than on tools_preset because a validation runs even
  # when its variable is left at the default, so these fire when the caller set only tools_preset and
  # when the caller set neither.
  #
  # TRAP: these read `local.tool_names` and `local.presets`, which registry.tf derives from literals.
  # They must never reach `local.wanted`, `local.selected` or `local.permissions` — a validation that
  # names a local depending on the variable it validates is a hard `Cycle:` error.
  validation {
    condition     = !(var.tools_preset != null && var.tools_enabled != null)
    error_message = "tools_preset and tools_enabled are alternatives and both are set: remove one. Keep tools_preset for that named surface, or keep tools_enabled to name the tools yourself."
  }

  validation {
    condition     = !(var.tools_preset == null && var.tools_enabled == null)
    error_message = "this registration has no tool surface: set tools_preset to one of ${join(", ", sort(keys(local.presets)))}, or tools_enabled to a list of tool names. There is deliberately no default, because the tools enabled decide which delegated Graph permissions every user of this connector consents to."
  }

  validation {
    condition     = var.tools_enabled == null || length(coalesce(var.tools_enabled, [])) > 0
    error_message = "tools_enabled is set but names no tool. Give it a list of tool names, or set tools_preset to one of: ${join(", ", sort(keys(local.presets)))}."
  }

  validation {
    # A typo must never quietly cost a tool: an unknown name filtered out in silence leaves one tool
    # fewer registered and one permission fewer on the consent screen than whoever wrote it believes
    # — and a permission not consented at sign-in cannot be obtained later. The valid list is derived
    # from local.tool_names, so it cannot go stale when a tool lands.
    condition     = var.tools_enabled == null || length(setsubtract(toset(coalesce(var.tools_enabled, [])), toset(local.tool_names))) == 0
    error_message = "tools_enabled names ${join(", ", sort(setsubtract(toset(coalesce(var.tools_enabled, [])), toset(local.tool_names))))}, which this connector has no tool for. The tools it has are: ${join(", ", local.tool_names)}."
  }

  validation {
    # The mistake somebody carrying the env var across will make. Without this it fails on the rule
    # above with a confusing "no tool for list_chats,read_message".
    condition     = alltrue([for name in coalesce(var.tools_enabled, []) : !strcontains(name, ",")])
    error_message = "tools_enabled is a list of tool names, not the pod's comma-separated TOOLS_ENABLED string. Write [\"list_chats\", \"read_message\"], not [\"list_chats,read_message\"]."
  }
}

variable "display_name" {
  description = <<-EOT
    The display name for the Entra application registration.
    Required, unlike the sibling modules that default it: tool-level selection makes two
    registrations in one tenant normal (one per tool surface), and a name that says which surface it
    carries is the only thing an administrator reading a consent screen has to go on. Entra itself
    permits duplicate display names; `prevent_duplicate_names` in main.tf asks the provider to refuse
    one at create anyway, so a defaulted name would turn the second surface into a failed apply.
  EOT
  type        = string

  validation {
    condition     = length(trimspace(var.display_name)) > 0
    error_message = "display_name must not be empty."
  }
}

variable "notes" {
  description = "Notes for the Entra application. Inherited by the service principal unless service_principal_configuration.notes overrides it. The only place an operator can write down which cluster consumes this registration where somebody hunting it in the portal will read it."
  type        = string
  default     = null
}

variable "sign_in_audience" {
  description = <<-EOT
    The Microsoft identity platform audiences supported by this application.
    Defaults to 'AzureADMyOrg', unlike the sibling modules: this app is an OAuth *resource server*
    with an `api://<client_id>` identifier and Unique-owned redirect hosts, and `config.py` rejects
    the multi-tenant authority aliases while AzureProvider validates every token against one issuer
    derived from a single tenant id. A multi-org default would only widen who may consent, for no
    capability gained.
    'AzureADMultipleOrgs' remains available for the customer-tenant flow, where the customer's own
    administrator consents through admin_consent_url rather than through this module's own grant.
  EOT
  type        = string
  default     = "AzureADMyOrg"

  validation {
    condition     = contains(["AzureADMyOrg", "AzureADMultipleOrgs"], var.sign_in_audience)
    error_message = "The sign_in_audience must be one of: 'AzureADMyOrg', or 'AzureADMultipleOrgs'."
  }
}

variable "api_scope_id" {
  description = <<-EOT
    The UUID of the exposed `access_as_user` API scope. Leave null and the module derives it with
    `uuidv5`, a pure function of a constant — no `random` provider, no state entry, and a rebuilt
    state cannot mint a new one.
    Set it ONLY to adopt an app registration that already exists: `oauth2_permission_scope.id` forces
    replacement when it changes, and replacing the scope invalidates every token already issued
    against it, so an existing registration must be imported with its existing UUID pinned here.
  EOT
  type        = string
  default     = null

  validation {
    condition     = var.api_scope_id == null || can(regex("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", coalesce(var.api_scope_id, "<unset>")))
    error_message = "api_scope_id must be a UUID."
  }
}

variable "secret_name_prefix" {
  description = <<-EOT
    Prefix of the composed Key Vault secret name, `<prefix>-<confidential_clients key>-client-secret`.
    REQUIRED, with no default, and named for the secret rather than for the variable it used to sit
    beside. The sibling modules default their prefix to their own service name, and every existing
    caller takes that default — so two registrations of one service collide the moment their
    environment keys overlap, and tool-level selection makes two registrations of THIS service
    normal (one per tool surface). Two `azurerm_key_vault_secret` resources with the same name in
    the same vault do not conflict at plan time: each apply flips the stored value, and the two
    deployments then alternately break each other's sign-ins with a clean plan every time.
    Put the axis that distinguishes this registration into the prefix (e.g. "office-365-mcp-preview").
  EOT
  type        = string

  validation {
    # Key Vault's own charset for a secret name, lowercased so two spellings cannot mean two secrets,
    # AND pinned to this service's own name. The pin is what makes a CROSS-service collision
    # impossible rather than merely undefaulted: `secret_name_prefix = "teams-mcp"` composes exactly
    # the name teams-mcp's own module writes into this same shared vault, which plans clean and then
    # overwrites a live secret belonging to another service. Requiring the value stops that being
    # inherited by accident; requiring it to start with "office-365-mcp" stops it being written on
    # purpose. The distinguishing axis goes in the suffix.
    condition     = can(regex("^office-365-mcp(-[a-z0-9]([a-z0-9-]*[a-z0-9])?)?$", var.secret_name_prefix))
    error_message = "secret_name_prefix must be \"office-365-mcp\" or \"office-365-mcp-<suffix>\", lowercase alphanumerics and hyphens. It is pinned to this service's name so a prefix cannot name another service's secrets in a shared Key Vault."
  }

  validation {
    # Fails at plan rather than deep inside azurerm at apply. 127 is Key Vault's limit.
    condition = alltrue([
      for key in keys(var.confidential_clients) :
      length("${var.secret_name_prefix}-${key}-client-secret") <= 127
    ])
    error_message = "The composed secret name '<secret_name_prefix>-<key>-client-secret' exceeds Key Vault's 127-character limit for at least one confidential_clients key."
  }
}

variable "confidential_clients" {
  description = <<-EOT
    One entry per environment that signs in through this registration. Required and non-empty: the
    On-Behalf-Of exchange cannot be done without a client secret, so a registration with no
    confidential client is not a deployable state of this service.
    `public_base_url` rides the SAME entry as the secret on purpose. teams-mcp's flat `redirect_uris`
    list has no relation to its `confidential_clients` keys, and the real spellings differ
    (`unique-uat01` against `teams.mcp.uat1.unique.app`), so adding an environment and forgetting its
    URI applies cleanly and then fails every sign-in in that environment alone. Here one key means
    one environment, one secret, one redirect URI and one set of overlay values.
    The client secret is stored in the Key Vault named by client_secret.key_vault_id. Per our
    [Design Principles](https://github.com/Unique-AG/terraform-modules/blob/main/DESIGN.md) the
    caller owns the permissions on that vault; this module outputs the secret ids for the caller to
    grant granular read on. Tie one secret to exactly one workload identity.
    Rotating `rotation_counter` costs more here than a pod restart: the client secret is also the
    PBKDF2 key material for this service's OAuth state rows in Postgres (`auth.py`,
    `_ENCRYPTION_SALT`), so every signed-in user signs in again. Zero-downtime rotation is not
    supported. `end_date` is mandatory on purpose, to keep expiry somebody's problem before it is
    everybody's.
  EOT
  type = map(object({
    public_base_url = string
    client_secret = object({
      key_vault_id     = string
      rotation_counter = optional(number, 0)
      end_date         = string
    })
  }))

  validation {
    condition     = length(var.confidential_clients) > 0
    error_message = "confidential_clients must name at least one environment: a registration with no client secret cannot do the On-Behalf-Of exchange, and one with no callback URI refuses every sign-in while applying cleanly."
  }

  validation {
    condition = alltrue([
      for k, v in var.confidential_clients :
      can(regex("^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}Z$", v.client_secret.end_date))
    ])
    error_message = "The end_date must be in RFC3339 format (e.g. 2018-01-01T01:02:03Z)."
  }

  validation {
    # Origin only, optional trailing slash (the module trims it): https because `config.py` refuses a
    # non-https PUBLIC_BASE_URL in production, and origin-only because the module appends
    # `/auth/callback` itself — a path here would silently register a callback the provider never
    # calls back on.
    condition = alltrue([
      for k, v in var.confidential_clients :
      can(regex("^https://[^/?#]+/?$", v.public_base_url))
    ])
    error_message = "Each public_base_url must be an https origin with no path, query or fragment (e.g. https://office-365.mcp.qa.unique.app); the module appends /auth/callback itself."
  }

  validation {
    # One key means ONE environment, which is the whole justification for `public_base_url` riding
    # this entry. Two keys sharing a base URL applies cleanly and produces two secrets against one
    # callback URI — so two environments' pods both accept sign-ins at the same host while holding
    # different secrets, and which one works depends on which applied last. The trailing slash is
    # trimmed before comparing, because `https://h` and `https://h/` are one environment written two
    # ways and both compose the identical redirect URI.
    condition = length(distinct([
      for v in var.confidential_clients : trimsuffix(v.public_base_url, "/")
    ])) == length(var.confidential_clients)
    error_message = "Each confidential_clients entry must have a distinct public_base_url: two keys sharing one base URL register a single callback URI for two secrets, and the sign-ins that work then depend on which apply ran last."
  }

  validation {
    # A vault name or a vaultUrl here otherwise dies deep inside azurerm with an eight-segment
    # resource-ID parse dump that names nothing about this module.
    condition = alltrue([
      for k, v in var.confidential_clients :
      can(regex("^/subscriptions/[^/]+/resourceGroups/[^/]+/providers/Microsoft\\.KeyVault/vaults/[^/]+$", v.client_secret.key_vault_id))
    ])
    error_message = "Each client_secret.key_vault_id must be a Key Vault resource ID (/subscriptions/.../resourceGroups/.../providers/Microsoft.KeyVault/vaults/...), not a vault name or vault URL."
  }
}

variable "extra_redirect_uris" {
  description = "Escape hatch for a redirect URI no confidential_clients entry implies — a local developer loopback, a one-off. Not the normal path: every deployment's callback is derived from its own public_base_url."
  type        = list(string)
  default     = []
}

variable "admin_consent_redirect_uri" {
  description = "Branded landing page, registered as an additional redirect URI and used as the redirect_uri of admin_consent_url. It exists so a completed admin consent lands somewhere that reads like success — the only other registered Web URI is FastMCP's OAuth callback, which would render a successful consent as an error page."
  type        = string
  default     = "https://www.unique.ai/setup/consent-completed/entra-id"
}

variable "service_principal_configuration" {
  description = <<-EOT
    `{}` (the default) creates the service principal and grants the resolved delegated permissions
    tenant-wide, on behalf of all users. Set it to null to skip both — for a customer tenant that
    manages its own consent, which then has to be granted through admin_consent_url or the portal.
    Skipping it is a real state, not a mistake, but it is only safe when somebody else grants the
    consent: three of the eight permissions this connector can ask for need an administrator, so
    every preset except `teams-chat` sends every user to "Need admin approval" until they do. The
    module warns (a `check` block) rather than refusing, because which of the two is happening is
    not knowable from here.
  EOT
  type = object({
    notes = optional(string)
  })
  default = {}
}
