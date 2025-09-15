import type { CodegenConfig } from '@graphql-codegen/cli';

const config: CodegenConfig = {
  overwrite: true,
  schema: ['../../../services/factset-mcp/src/@generated/schema.graphql'],
  documents: './src/unique-api/graphql/*.graphql',
  generates: {
    './src/unique-api/@generated/graphql.ts': {
      plugins: ['typescript', 'typescript-operations', 'typed-document-node'],
    },
  },
};
export default config;
