<!-- confluence-page-id: tobefilled -->
<!-- confluence-space-key: PUBDOC -->

## Overview

What happens when part of a Backstop MCP deployment fails, what users notice, and what the operator
does to recover. It also covers rotating the encryption key, which behaves like a controlled
failure.

The server holds no CRM data. Every record lives in Backstop, which the server only reads and writes
on a user's behalf, so no failure here loses CRM data. What can be lost is the connection state that
lets users call tools without logging in again.

## What Holds State

| Component | Holds | If lost |
|---|---|---|
| **PostgreSQL** | OAuth clients, hashed MCP tokens, pending logins, login attempts, and each user's encrypted Backstop credential | Users log in again. See [PostgreSQL data lost](#PostgreSQL-Data-Lost) |
| **`BACKSTOP_MCP_ENCRYPTION_KEY`** | The only key that decrypts the stored credentials | Stored credentials become unreadable. Users log in again. See [Encryption key lost](#Encryption-Key-Lost) |
| **Pod memory** | MCP sessions, catalog caches, report builds in progress, the per-user request gate | Rebuilt on their own. See [Pod restarts or dies](#Pod-Restarts-or-Dies) |
| **Backstop** | All CRM data | Not this server's to recover. See [Backstop unavailable](#Backstop-Unavailable) |

### What to back up

| Item | How | Why |
|---|---|---|
| The PostgreSQL database | Your platform's backups: managed snapshots, `pg_dump`, or WAL archiving | Without it every user logs in again. Recovery is otherwise complete |
| The encryption key | Your secret store, separately from the database backups | A database backup is unreadable without the key that was active when it was taken. Keep each key as long as you keep backups made with it |

Nothing else needs a backup. The chart, the image, and the configuration are in version control and
the registry.

### Who is needed

| Role | When |
|---|---|
| Kubernetes operator | Every scenario: restarts, secrets, Helm upgrades |
| Database administrator | Restoring or reprovisioning PostgreSQL; running SQL during a key rotation |
| Users | After any scenario that loses their connection: they log in again from their MCP client. The operator cannot do it for them |
| Backstop administrators | Only if API tokens may have leaked: they revoke them |

## Pod Restarts or Dies

A crash, an eviction, a node failure, or a normal rollout.

**What users notice**

- A tool call that was running fails. If it was a create, the record may already exist in Backstop:
  creates are not idempotent, so check before repeating it.
- MCP sessions live in the pod's memory. The next request carries a session id the new pod does not
  know, which answers `404 Session not found`, and a client that follows the MCP specification
  starts a new session by itself. A client that does not shows an error until the user reconnects.
- A question waiting for the user to pick between matches is dropped. Ask again.
- A `run_report` build in progress is lost. The next call starts it again.
- Nobody has to log in again. Tokens and credentials are in PostgreSQL.

**What the operator does.** Nothing. Kubernetes replaces the pod. Catalog caches refill on first
use, so the first calls after a restart are a little slower.

A login form that was open during the restart still works: the pending login is in PostgreSQL, and
the CSRF check is a cookie, not pod memory.

## PostgreSQL Unavailable

The database is down or unreachable, but its data is intact.

**What users notice.** Every `/mcp` request fails, because each one looks up its token in the
database. New logins fail too.

**What happens automatically**

- `/ready` returns `503` and Kubernetes takes the pod out of service. `/health` keeps answering, so
  the pod is not restarted in a loop.
- A pod that starts while the database is down starts anyway and waits, not ready.
- The cleanup sweep logs `auth.cleanup.failed` and tries again at its next interval.
- A Helm install or upgrade fails, because its migration hook cannot connect. Wait for the database
  before upgrading.

**What the operator does.** Restore database connectivity. Pods become ready again on their own, and
users carry on without logging in again.

If the database comes back at a new address, update the connection secret (`database-url` in the
[self-managed example](./README.md#3.-Create-the-Kubernetes-secret)) and restart the pods, which read
it only at startup:

```bash
kubectl -n backstop-mcp rollout restart deploy/backstop-mcp
```

## PostgreSQL Data Lost

The database is gone, or has to be restored from a backup.

### Restoring from a backup

1. Restore the database. Keep the **same encryption key** that was active when the backup was taken.
2. Update the connection secret if the address changed, and restart the pods.
3. If the backup is from an older chart version, run `helm upgrade` (see
   [Running migrations](#Running-Migrations)) so its migration hook brings the schema up to date. A
   rollout restart does not run migrations.

What users notice depends on how old the backup is:

| User | Result |
|---|---|
| Last refreshed tokens before the backup and has not refreshed since | Carries on |
| Refreshed tokens or logged in after the backup | The client's tokens are unknown. Its refresh fails, and it opens the login form |
| Connected a new MCP client after the backup | The client's registration is gone too. Many clients register again by themselves; one that does not has to be removed and re-added |

Refresh tokens rotate on every use, so with an active user base most users log in again unless the
backup is minutes old.

### Starting from an empty database

1. Provision an empty database and update the connection secret.
2. Run `helm upgrade` (see [Running migrations](#Running-Migrations)). Its pre-upgrade hook
   runs `alembic upgrade head` and creates the tables. A rollout restart alone leaves the database
   empty, and every request fails.
3. Tell users to log in again. Each client's next call gets `401`, its refresh fails, and it opens
   the login form. A client that does not register again by itself has to be removed and re-added.

The encryption key does not matter here: there is nothing old to decrypt.

## Encryption Key Lost

The secret holding `BACKSTOP_MCP_ENCRYPTION_KEY` was deleted or overwritten, and no copy exists.

- **The secret is gone:** Kubernetes cannot start the container, because the `secretKeyRef` points
  at nothing.
- **The value is empty or not a Fernet key:** the server exits at startup with an error naming
  `BACKSTOP_MCP_ENCRYPTION_KEY`.
- **A different valid key was put in its place:** the pod starts, but no stored credential decrypts,
  and every tool call fails. Clients are not prompted to log in again (see
  [What happens if you only swap the key](#What-happens-if-you-only-swap-the-key)).

If a copy of the key exists, restore the secret and restart the pods. Users are not affected.

Without a copy, the stored credentials cannot be recovered. Follow [Rotating the encryption key](#Rotating-the-Encryption-Key)
with a new key: it disconnects everyone in a way that makes their clients ask them to log in again.

## Rotating the Encryption Key

The server accepts one key at a time. There is no mode that reads with an old key and writes with a
new one, so a rotation disconnects every user, and each one logs in again. Plan it as a maintenance
window of a few minutes.

### What happens if you only swap the key

Changing the secret and restarting is not enough. The pods start, but every stored credential fails
to decrypt. Users' MCP tokens are still valid, so their clients see no reason to log in again: every
tool call just fails. Each user then has to remove and re-add the server to reach the login form.

### Procedure

The extra step is revoking every MCP token. Then each client's next call gets `401` and its refresh
is refused, and the client opens the login form by itself.

On Unique SaaS, pause Argo CD auto-sync for the application first; otherwise it reverts the
`kubectl scale` commands below.

1. Generate a new key:

   ```bash
   python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   # or, without the Python cryptography package:
   openssl rand -base64 32 | tr '+/' '-_'
   ```

2. Note the current replica count, then stop the server, so no pod uses either key while the
   database changes:

   ```bash
   kubectl -n backstop-mcp get deploy/backstop-mcp -o jsonpath='{.spec.replicas}'
   kubectl -n backstop-mcp scale deploy/backstop-mcp --replicas=0
   ```

3. Put the new key in the secret (`encryption-key` in the
   [self-managed example](./README.md#3.-Create-the-Kubernetes-secret)). Keep the old key if any
   database backup still depends on it.

4. Revoke every MCP token, and delete the credentials the new key cannot read:

   ```sql
   UPDATE mcp_auth_oauth_tokens SET revoked_at = now() WHERE revoked_at IS NULL;
   DELETE FROM backstop_credentials;
   ```

   Deleting the credentials is optional for the server. Each login replaces its user's row anyway.
   It does mean the live database no longer holds tokens the old key can decrypt. Users whose row
   was deleted get a new internal user id at their next login; the old id remains only on revoked
   token rows.

5. Start the server again with the replica count from step 2, and resume Argo CD auto-sync on
   Unique SaaS:

   ```bash
   kubectl -n backstop-mcp scale deploy/backstop-mcp --replicas=<previous count>
   ```

6. Tell users their client will ask them to log in to Backstop again, with the same username and API
   token.

OAuth client registrations are kept, so no client has to be removed and re-added.

### If the key may have leaked

The key alone is useless, and so is the database alone. Together they reveal every stored Backstop
API token. If both may have been exposed, rotating the key protects only future logins. The exposed
tokens still work against Backstop until they are revoked there:

1. Ask Backstop administrators to revoke every connected user's API token. Usernames are in
   `backstop_credentials.backstop_username`; read them before step 4 above deletes the rows.
2. Users create new tokens and log in with them.
3. Rotate the key as above.

Database backups made before the rotation hold the old tokens encrypted under the old key. Once the
tokens are revoked in Backstop, those backups are harmless.

## Backstop Unavailable

Backstop is down, slow, or unreachable from the cluster.

**What users notice**

- Tool calls fail with Backstop's error, or time out after `BACKSTOP_DEFAULT_TIMEOUT_SECONDS`
  (120 s). Unique's chat client cancels a tool call at 60 s, so its users see that first.
- The login form says *"Backstop is unreachable right now"*. These attempts do not count toward the
  login throttle.
- Nobody is disconnected. A `401` from Backstop disconnects a user only after repeated checks all
  answer `401` or `403`; checks that time out or fail with `5xx` keep the session. See
  [Authentication: When Backstop rejects the credential](./authentication.md#When-Backstop-rejects-the-credential).

**What the operator does.** Nothing in the server. Check egress from the pod to `BACKSTOP_BASE_URL`
(network policy, DNS, proxy), and Backstop's own status. The server recovers by itself once Backstop
answers.

A `429` with a day, hour, or minute quota is Backstop limiting that user, not an outage. The server
does not retry those. `backstop_rate_limited_total` shows which kind it was.

## Migration Hook Fails

The `backstop-mcp-migration` job that runs `alembic upgrade head` before an install or upgrade
fails, for example because the database is unreachable or its user cannot create tables.

**What users notice.** On an upgrade, nothing: the hook runs before the rollout, so the old pods
keep serving. On a first install, there is no server yet.

**What the operator does.**

1. Read the job's log. The failed job is kept until the next hook run replaces it:

   ```bash
   kubectl -n backstop-mcp logs job/backstop-mcp-migration
   ```

2. Fix the cause, then run `helm upgrade` again (see [Running migrations](#Running-Migrations)).
   Helm marks the release `failed` until an upgrade succeeds. After a failed first install, use
   `helm upgrade --install` with your `values.yaml`, or `helm uninstall` and install again.

## Cluster or Region Lost

The pod, the namespace, or the whole cluster is gone.

1. Install the chart in the new location with the same values, the same encryption key, and the
   same `PUBLIC_BASE_URL`.
2. Point it at the existing database, or at one restored from backup (see
   [PostgreSQL data lost](#PostgreSQL-Data-Lost)).
3. Move the hostname to the new ingress.

With the same database, key, and hostname, users are not affected beyond a new MCP session. A new
hostname changes the OAuth issuer, so every user has to remove the server from their MCP client and
add the new URL.

## Running Migrations

Steps on this page that say "run `helm upgrade`" mean this command. Any `helm upgrade`, even to the
chart version already installed, runs the pre-upgrade migration hook (`alembic upgrade head`):

```bash
helm upgrade backstop-mcp oci://ghcr.io/unique-ag/connectors/helm/backstop-mcp \
  --version <installed chart version> \
  --namespace backstop-mcp \
  --reuse-values
```

On Unique SaaS the chart is deployed by Argo CD, which runs the hook on every sync; trigger a sync
instead.

## Related

- [Operator Guide](./README.md)
- [Overview](../README.md)
- [Authentication](./authentication.md)
- [Configuration](./configuration.md)
- [Operator Guide: Operating the Service](./README.md#Operating-the-Service)
