import { env } from 'node:process';

env.GRAPH_CLIENT_ID = 'test-client-id';
env.GRAPH_CLIENT_SECRET = 'test-client-secret';
env.GRAPH_TENANT_ID = 'test-tenant-id';
env.UNIQUE_INGESTION_URL_GRAPHQL = 'https://api.test.example.com/graphql';
env.UNIQUE_INGESTION_URL = 'https://api.test.example.com';
env.UNIQUE_SCOPE_ID = 'test-scope-id';
env.ZITADEL_OAUTH_TOKEN_URL = 'https://auth.test.example.com/oauth/token';
env.ZITADEL_PROJECT_ID = 'test-project-id';
env.ZITADEL_CLIENT_ID = 'test-zitadel-client-id';
env.ZITADEL_CLIENT_SECRET = 'test-zitadel-client-secret';
