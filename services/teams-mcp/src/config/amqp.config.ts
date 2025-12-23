import {
  type ConfigType,
  type NamespacedConfigType,
  registerConfig,
} from '@proventuslabs/nestjs-zod';
import { z } from 'zod/v4';
import { Redacted } from '~/utils/redacted';
import { redacted, stringToURL } from '~/utils/zod';

const urlConfigSchema = z.object({
  url: redacted(
    stringToURL().refine(
      (u) => u.protocol === 'amqp:',
      'The supplied URL must be using `amqp:` protocol',
    ),
  ).describe('The AMQP connection url.'),
});

const syntaxBindingConfigSchema = z
  .object({
    username: z.string().min(1).describe('The AMQP username.'),
    password: redacted(z.string().min(1)).describe('The AMQP password.'),
    host: z.string().min(1).describe('The AMQP host.'),
    port: z.coerce.number().int().positive().default(5672).describe('The AMQP port.'),
    vhost: z.string().optional().describe('The AMQP virtual host.'),
  })
  .transform((config) => {
    const vhost = config.vhost ? `/${encodeURIComponent(config.vhost)}` : '';
    const url = new URL(
      `amqp://${encodeURIComponent(config.username)}:${encodeURIComponent(config.password.value)}@${config.host}:${config.port}${vhost}`,
    );
    return { url: new Redacted(url) };
  });

const ConfigSchema = urlConfigSchema.or(syntaxBindingConfigSchema);

export const amqpConfig = registerConfig('amqp', ConfigSchema);

export type AMQPConfigNamespaced = NamespacedConfigType<typeof amqpConfig>;
export type AMQPConfig = ConfigType<typeof amqpConfig>;
