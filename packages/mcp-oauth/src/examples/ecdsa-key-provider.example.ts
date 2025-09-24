/**
 * Example implementation of ECDSA key provider for JWT signing
 *
 * This example shows how to provide ECDSA keys for JWT signing in the MCP OAuth module.
 * In production, you would typically load these from a secure key management service
 * like AWS KMS, Azure Key Vault, or HashiCorp Vault.
 */

import { generateKeyPairSync } from 'node:crypto';
import { readFile } from 'node:fs/promises';

/**
 * Example 1: Load ECDSA keys from files
 *
 * This is suitable for development or when keys are managed via file system
 * (e.g., Kubernetes secrets mounted as files)
 */
export async function loadECDSAKeysFromFiles() {
  const privateKey = await readFile('/path/to/private-key.pem', 'utf-8');
  const publicKey = await readFile('/path/to/public-key.pem', 'utf-8');

  return {
    privateKey,
    publicKey,
    keyId: 'prod-key-2024',
    algorithm: 'ES256' as const,
  };
}

/**
 * Example 2: Generate ECDSA keys dynamically (for development only!)
 *
 * WARNING: This should only be used for development/testing.
 * In production, use persistent keys from a secure source.
 */
export async function generateECDSAKeys() {
  const { privateKey, publicKey } = generateKeyPairSync('ec', {
    namedCurve: 'P-256', // For ES256
    publicKeyEncoding: {
      type: 'spki',
      format: 'pem',
    },
    privateKeyEncoding: {
      type: 'pkcs8',
      format: 'pem',
    },
  });

  return {
    privateKey,
    publicKey,
    keyId: `dev-key-${Date.now()}`,
    algorithm: 'ES256' as const,
  };
}

/**
 * Example 3: Load ECDSA keys from environment variables
 *
 * Useful for containerized deployments where secrets are injected as environment variables
 */
export async function loadECDSAKeysFromEnv() {
  const privateKey = process.env.JWT_PRIVATE_KEY;
  const publicKey = process.env.JWT_PUBLIC_KEY;

  if (!privateKey || !publicKey) {
    throw new Error('JWT signing keys not configured in environment');
  }

  // Handle escaped newlines in environment variables
  const formattedPrivateKey = privateKey.replace(/\\n/g, '\n');
  const formattedPublicKey = publicKey.replace(/\\n/g, '\n');

  return {
    privateKey: formattedPrivateKey,
    publicKey: formattedPublicKey,
    keyId: process.env.JWT_KEY_ID || 'default',
    algorithm: (process.env.JWT_ALGORITHM as 'ES256' | 'ES384' | 'ES512') || 'ES256',
  };
}

/**
 * Example 4: Integration with AWS KMS (using AWS SDK)
 *
 * This example shows how to integrate with AWS KMS for key management
 * Note: Requires @aws-sdk/client-kms package
 */
export async function loadECDSAKeysFromAWSKMS() {
  // Pseudo-code - requires AWS SDK
  /*
  const kmsClient = new KMSClient({ region: 'us-east-1' });
  
  const keyId = 'arn:aws:kms:us-east-1:123456789012:key/12345678-1234-1234-1234-123456789012';
  
  // Get public key
  const publicKeyCommand = new GetPublicKeyCommand({ KeyId: keyId });
  const publicKeyResponse = await kmsClient.send(publicKeyCommand);
  const publicKey = Buffer.from(publicKeyResponse.PublicKey).toString('base64');
  
  // For signing, you would use KMS Sign operation instead of local signing
  // This would require a custom JWT signing implementation
  
  return {
    privateKey: keyId, // Reference to KMS key
    publicKey: convertToPublicKeyPEM(publicKey),
    keyId: 'aws-kms-key',
    algorithm: 'ES256' as const,
  };
  */

  throw new Error('AWS KMS integration example - implement based on your needs');
}

/**
 * Example usage in MCP OAuth module configuration
 */
export const exampleModuleConfig = {
  // ... other config ...

  accessTokenFormat: 'jwt' as const,

  jwtSigningKeyProvider: async () => {
    // Choose one of the implementations based on your environment:

    // For development:
    // return await generateECDSAKeys();

    // For production with file-based keys:
    // return await loadECDSAKeysFromFiles();

    // For production with environment variables:
    return await loadECDSAKeysFromEnv();

    // For production with AWS KMS:
    // return await loadECDSAKeysFromAWSKMS();
  },

  // ... other config ...
};

/**
 * Example: Generating ECDSA keys for different algorithms
 *
 * Run this script to generate key pairs for different ECDSA algorithms
 */
export function generateKeysForAlgorithm(algorithm: 'ES256' | 'ES384' | 'ES512') {
  const curveMap = {
    ES256: 'P-256',
    ES384: 'P-384',
    ES512: 'P-521',
  };

  const { privateKey, publicKey } = generateKeyPairSync('ec', {
    namedCurve: curveMap[algorithm],
    publicKeyEncoding: {
      type: 'spki',
      format: 'pem',
    },
    privateKeyEncoding: {
      type: 'pkcs8',
      format: 'pem',
    },
  });

  console.log(`\n=== ${algorithm} Keys ===`);
  console.log('\nPrivate Key:');
  console.log(privateKey);
  console.log('\nPublic Key:');
  console.log(publicKey);

  return { privateKey, publicKey };
}
