import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const icon = readFileSync(join(__dirname, '..', 'public', 'icons', 'favicon-192x192.png'));

export const serverIcons = [
  {
    src: `data:image/png;base64,${icon.toString('base64')}`,
    mimeType: 'image/png',
    sizes: ['192x192'],
  },
];
