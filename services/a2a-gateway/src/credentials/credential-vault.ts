import { AesGcmEncryptionService } from '@unique-ag/aes-gcm-encryption';
import { Injectable } from '@nestjs/common';

@Injectable()
export class CredentialVault {
  public constructor(private readonly encryption: AesGcmEncryptionService) {}

  public seal(value: string): Buffer {
    return Buffer.from(this.encryption.encryptToString(value), 'utf8');
  }

  public open(ciphertext: Buffer): string {
    return this.encryption.decryptFromString(ciphertext.toString('utf8')).toString('utf8');
  }
}
