import { createHash } from 'node:crypto';
import { Inject, Injectable, Logger, OnModuleInit } from '@nestjs/common';
import { exportJWK, importSPKI, type JWK as JoseJWK } from 'jose';
import {
  MCP_OAUTH_MODULE_OPTIONS_RESOLVED_TOKEN,
  type McpOAuthModuleOptions,
} from '../mcp-oauth.module-definition';

export interface ECDSAKeys {
  privateKey: string;
  publicKey: string;
  keyId: string;
  algorithm: 'ES256' | 'ES384' | 'ES512';
}

export interface JWK extends JoseJWK {
  use: string;
  kid: string;
  alg: string;
}

export interface JWKSet {
  keys: JWK[];
}

@Injectable()
export class JWKSService implements OnModuleInit {
  private readonly logger = new Logger(this.constructor.name);
  private cachedKeys: ECDSAKeys | null = null;
  private jwkSet: JWKSet | null = null;
  private lastKeyLoadTime: Date | null = null;
  private readonly KEY_CACHE_DURATION_MS = 3600000; // 1 hour

  public constructor(
    @Inject(MCP_OAUTH_MODULE_OPTIONS_RESOLVED_TOKEN)
    private readonly options: McpOAuthModuleOptions,
  ) {}

  public async onModuleInit() {
    if (this.options.jwtSigningKeyProvider) {
      await this.loadKeys();
      this.validateLoadedKeys();
    }
  }

  private async loadKeys(): Promise<void> {
    if (!this.options.jwtSigningKeyProvider)
      throw new Error('JWT signing key provider not configured');

    try {
      const startTime = Date.now();
      this.cachedKeys = await this.options.jwtSigningKeyProvider();

      await this.validateKeyPair(this.cachedKeys);

      this.jwkSet = await this.generateJWKSet(this.cachedKeys);
      this.lastKeyLoadTime = new Date();

      const loadTime = Date.now() - startTime;
      this.logger.log({
        msg: 'ECDSA keys loaded and validated successfully',
        keyId: this.cachedKeys.keyId,
        algorithm: this.cachedKeys.algorithm,
        loadTimeMs: loadTime,
      });
    } catch (error) {
      this.logger.error({
        msg: 'Failed to load ECDSA keys',
        error: error instanceof Error ? error.message : 'Unknown error',
      });
      throw new Error(
        `Failed to initialize JWT signing keys: ${error instanceof Error ? error.message : 'Unknown error'}`,
      );
    }
  }

  private validateLoadedKeys(): void {
    if (!this.cachedKeys) throw new Error('No keys loaded for validation');

    if (!this.cachedKeys.keyId || this.cachedKeys.keyId.length < 1)
      throw new Error('Invalid key ID: must be a non-empty string');
    this.validateKeyId(this.cachedKeys.keyId);

    const supportedAlgorithms = ['ES256', 'ES384', 'ES512'];
    if (!supportedAlgorithms.includes(this.cachedKeys.algorithm))
      throw new Error(
        `Unsupported algorithm: ${this.cachedKeys.algorithm}. Must be one of: ${supportedAlgorithms.join(', ')}`,
      );

    this.logger.debug({
      msg: 'Key validation passed',
      keyId: this.cachedKeys.keyId,
      algorithm: this.cachedKeys.algorithm,
    });
  }

  private async validateKeyPair(keys: ECDSAKeys): Promise<void> {
    if (!keys.privateKey || !keys.publicKey)
      throw new Error('Both private and public keys must be provided');
    if (!keys.privateKey.includes('BEGIN') || !keys.privateKey.includes('END'))
      throw new Error('Private key does not appear to be in PEM format');
    if (!keys.publicKey.includes('BEGIN PUBLIC KEY') || !keys.publicKey.includes('END PUBLIC KEY'))
      throw new Error('Public key does not appear to be in PEM format');

    try {
      await importSPKI(keys.publicKey, keys.algorithm);

      // Jose will throw if the key is not valid for the algorithm
      // This validates both the key format and that it matches the algorithm
    } catch (error) {
      throw new Error(
        `Invalid public key for ${keys.algorithm}: ${error instanceof Error ? error.message : 'Unknown error'}`,
      );
    }
  }

  public async getSigningKeys(forceRefresh = false): Promise<ECDSAKeys> {
    if (forceRefresh || this.shouldRefreshKeys()) {
      await this.loadKeys();
      this.validateLoadedKeys();
    }

    if (!this.cachedKeys) {
      await this.loadKeys();
      this.validateLoadedKeys();
    }

    if (!this.cachedKeys) throw new Error('No signing keys available');

    return this.cachedKeys;
  }

  public async getJWKSet(forceRefresh = false): Promise<JWKSet> {
    if (forceRefresh || this.shouldRefreshKeys()) {
      await this.loadKeys();
      this.validateLoadedKeys();
    }

    if (!this.jwkSet) {
      await this.loadKeys();
      this.validateLoadedKeys();
    }

    if (!this.jwkSet) throw new Error('No JWK set available');

    return this.jwkSet;
  }

  private shouldRefreshKeys(): boolean {
    if (!this.lastKeyLoadTime) return true;

    const timeSinceLoad = Date.now() - this.lastKeyLoadTime.getTime();
    return timeSinceLoad > this.KEY_CACHE_DURATION_MS;
  }

  public async reloadKeys(): Promise<void> {
    this.logger.log({ msg: 'Forcing key reload' });
    await this.loadKeys();
    this.validateLoadedKeys();
  }

  private async generateJWKSet(keys: ECDSAKeys): Promise<JWKSet> {
    try {
      const jwk = await this.pemToJWK(keys.publicKey, keys.keyId, keys.algorithm);

      return {
        keys: [jwk],
      };
    } catch (error) {
      this.logger.error({
        msg: 'Failed to generate JWK set',
        error: error instanceof Error ? error.message : 'Unknown error',
      });
      throw new Error('Failed to generate JWK set');
    }
  }

  /**
   * Convert PEM-encoded ECDSA public key to JWK format using jose
   */
  private async pemToJWK(
    publicKeyPem: string,
    kid: string,
    algorithm: 'ES256' | 'ES384' | 'ES512',
  ): Promise<JWK> {
    try {
      const publicKey = await importSPKI(publicKeyPem, algorithm);
      const jwk = await exportJWK(publicKey);

      return {
        ...jwk,
        use: 'sig',
        kid,
        alg: algorithm,
      };
    } catch (error) {
      this.logger.error({
        msg: 'Failed to convert PEM to JWK',
        error: error instanceof Error ? error.message : 'Unknown error',
        algorithm,
      });
      throw new Error(
        `Failed to convert PEM to JWK: ${error instanceof Error ? error.message : 'Unknown error'}`,
      );
    }
  }

  /**
   * Generate a unique key ID from public key fingerprint
   * Uses SHA-256 hash of the public key for deterministic ID generation
   */
  public generateKeyId(publicKey: string): string {
    const hash = createHash('sha256').update(publicKey.trim()).digest();
    // Use first 12 bytes (96 bits) for better uniqueness while keeping ID reasonable length
    return hash.subarray(0, 12).toString('base64url');
  }

  public isJWTEnabled(): boolean {
    return !!this.options.jwtSigningKeyProvider;
  }

  private validateKeyId(keyId: string): void {
    // Key ID should be URL-safe and not too long
    if (!/^[A-Za-z0-9_-]+$/.test(keyId))
      throw new Error('Key ID must contain only URL-safe characters (A-Z, a-z, 0-9, -, _)');
    if (keyId.length > 128) throw new Error('Key ID must not exceed 128 characters');
  }
}
