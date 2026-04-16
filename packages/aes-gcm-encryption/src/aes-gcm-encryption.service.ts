import { createCipheriv, createDecipheriv, randomBytes } from 'node:crypto';
import { Inject, Injectable } from '@nestjs/common';
import * as z from 'zod';
import {
  AES_GCM_ENCRYPTION_MODULE_OPTIONS_RESOLVED_TOKEN,
  type ResolvedEncryptionOptions,
} from './aes-gcm-encryption.module-definition';

const CipherPayloadSchema = z.object({
  iv: z.base64(),
  tag: z.base64(),
  data: z.base64(),
});

type CipherPayload = z.infer<typeof CipherPayloadSchema>;

@Injectable()
export class AesGcmEncryptionService {
  private readonly algorithm = 'aes-256-gcm';

  public constructor(
    @Inject(AES_GCM_ENCRYPTION_MODULE_OPTIONS_RESOLVED_TOKEN)
    private readonly options: ResolvedEncryptionOptions,
  ) {}

  public encrypt(plain: Buffer | string): CipherPayload {
    const iv = randomBytes(this.options.ivLength ?? 12);
    const cipher = createCipheriv(this.algorithm, this.options.key, iv);

    const ciphertext = Buffer.concat([
      cipher.update(plain instanceof Buffer ? plain : Buffer.from(plain)),
      cipher.final(),
    ]);

    return {
      iv: iv.toString('base64'),
      tag: cipher.getAuthTag().toString('base64'),
      data: ciphertext.toString('base64'),
    };
  }

  public encryptToString(plain: Buffer | string): string {
    const payload = this.encrypt(plain);
    return `${payload.iv}.${payload.tag}.${payload.data}`;
  }

  public decrypt(payload: CipherPayload): Buffer {
    const { iv, tag, data } = CipherPayloadSchema.parse(payload);
    const decipher = createDecipheriv(this.algorithm, this.options.key, Buffer.from(iv, 'base64'));
    decipher.setAuthTag(Buffer.from(tag, 'base64'));

    const plain = Buffer.concat([decipher.update(Buffer.from(data, 'base64')), decipher.final()]);
    return plain;
  }

  public decryptFromString(cipherString: string): Buffer {
    const [iv, tag, data] = cipherString.split('.');
    if (!iv || !tag || !data) {
      throw new Error('Invalid cipher string');
    }
    return this.decrypt({ iv, tag, data });
  }
}
