# Deploy Demo IR MCP

The service runs in Azure Container Apps. The frontend and REST API use Zitadel through Azure Container Apps Custom OpenID Connect authentication. The MCP endpoint, probe, and manifest remain unauthenticated.

## Prerequisites

- Docker is running.
- Azure CLI is installed and logged in with `az login`.
- You have Contributor access to the LAB resource group.
- You can create a Web Application in the intended Zitadel project.

## 1. Configure Azure values

Create the local deployment configuration:

```bash
cd services/demo-ir-mcp/deploy
cp .env.deploy.example .env.deploy
```

Set `RESOURCE_GROUP`, a globally unique `ACR_NAME`, and the Container App names in `.env.deploy`. Leave the three `ZITADEL_*` values empty for the first deployment. Never commit `.env.deploy`.

## 2. Deploy the Container App

From the repository root:

```bash
services/demo-ir-mcp/deploy/deploy.sh
```

The script builds and pushes the image, creates or updates the Container App, verifies `/probe`, and prints the public URLs. Copy the printed OIDC callback URL. It has this form:

```text
https://<container-app-fqdn>/.auth/login/zitadel/callback
```

At this point authentication is not configured yet, so continue with the remaining steps immediately.

## 3. Create the Zitadel Web Application

In the Zitadel project:

1. Create an **OIDC Web Application**.
2. Use the **Authorization Code** flow.
3. Select **Client Secret Post** as the authentication method. Azure Container Apps Custom OIDC requires this method.
4. Add the exact callback URL printed by `deploy.sh` as the redirect URI.
5. Allow the `openid`, `profile`, and `email` scopes.
6. Save the generated client ID and client secret.
7. Copy the Zitadel issuer URL. Do not include `/.well-known/openid-configuration`; the configuration script appends it.

Limit access to the application to the Zitadel users or organization members who may operate the demo.

## 4. Configure OIDC credentials

Add the Zitadel values to `deploy/.env.deploy`:

```dotenv
ZITADEL_ISSUER_URL=https://<zitadel-domain>
ZITADEL_CLIENT_ID=<client-id>
ZITADEL_CLIENT_SECRET=<client-secret>
```

The client secret is stored directly as an Azure Container App secret. It is not included in the container environment or frontend bundle.

Apply the authentication configuration:

```bash
services/demo-ir-mcp/deploy/configure-auth.sh
```

The script is idempotent and can also be used to rotate the client secret. It protects the frontend and `/api`, while excluding:

- `/mcp`
- `/probe`
- `/manifest`

## 5. Verify the deployment

Open the frontend URL. Azure should redirect the browser to Zitadel and return to the frontend after login.

The following routes remain public:

```bash
curl --fail https://<container-app-fqdn>/probe
curl --fail https://<container-app-fqdn>/manifest
```

An unauthenticated frontend or API request should redirect to Zitadel:

```bash
curl --head https://<container-app-fqdn>/
curl --head https://<container-app-fqdn>/api
```

Use the explicit login and logout endpoints when needed:

```text
https://<container-app-fqdn>/.auth/login/zitadel?post_login_redirect_uri=/
https://<container-app-fqdn>/.auth/logout?post_logout_redirect_uri=/
```

## Later deployments

Run `deploy.sh` again to publish a new image. The Container App authentication configuration and secret remain attached to the existing Container App, so `configure-auth.sh` only needs to be rerun when the Zitadel configuration or credentials change.

The SQLite database is temporary and is reset whenever the container starts or a deployment creates a new revision.
