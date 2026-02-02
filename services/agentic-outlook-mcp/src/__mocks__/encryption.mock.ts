import { IEncryptionService } from '@unique-ag/mcp-oauth';

export class MockEncryptionService implements IEncryptionService {
  public encryptToString(plain: Buffer | string): string {
    const data = typeof plain === 'string' ? plain : plain.toString();
    return Buffer.from(data).toString('base64');
  }

  public decryptFromString(cipherString: string): Buffer {
    return Buffer.from(cipherString, 'base64');
  }

  public encrypt(plain: Buffer | string): string {
    return this.encryptToString(plain);
  }

  public decrypt(payload: unknown): Buffer {
    if (typeof payload === 'string') {
      return this.decryptFromString(payload);
    }
    throw new Error('Invalid payload type for decrypt');
  }
}
