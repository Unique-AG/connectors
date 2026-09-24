import { AesGcmEncryptionModule, AesGcmEncryptionService } from '@unique-ag/aes-gcm-encryption';
import { Test } from '@nestjs/testing';
import { describe, expect, it } from 'vitest';
import { CredentialVault } from './credential-vault.js';

describe('CredentialVault', () => {
  it('stores an authenticated ciphertext instead of plaintext', async () => {
    const module = await Test.createTestingModule({
      imports: [AesGcmEncryptionModule.register({ key: Buffer.alloc(32, 7) })],
      providers: [CredentialVault],
    }).compile();
    const vault = module.get(CredentialVault);

    const ciphertext = vault.seal('secret-token');

    expect(ciphertext.toString()).not.toContain('secret-token');
    expect(vault.open(ciphertext)).toBe('secret-token');
    expect(module.get(AesGcmEncryptionService)).toBeDefined();
  });
});
