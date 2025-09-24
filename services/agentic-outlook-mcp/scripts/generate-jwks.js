const crypto = require('node:crypto');

const { privateKey, publicKey } = crypto.generateKeyPairSync('ec', {
  namedCurve: 'P-256',
  publicKeyEncoding: {
    type: 'spki',
    format: 'pem',
  },
  privateKeyEncoding: {
    type: 'pkcs8',
    format: 'pem',
  },
});

const b64PrivateKey = Buffer.from(privateKey).toString('base64');
const b64PublicKey = Buffer.from(publicKey).toString('base64');

const hash = crypto.createHash('sha256').update(publicKey.trim()).digest();
const keyId = hash.subarray(0, 12).toString('base64url');

console.log(`\n=== P-256 Keys ===`);
console.log('\nPrivate Key:');
console.log(b64PrivateKey);
console.log('\nPublic Key:');
console.log(b64PublicKey);
console.log('\nKey ID:');
console.log(keyId);
console.log('\nAlgorithm:');
console.log('ES256');
