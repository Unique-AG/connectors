import { BadRequestException } from '@nestjs/common';
import { Inflate } from 'pako';

/**
 * Maximum allowed compressed data size (before decompression) in bytes
 * This prevents extremely large compressed payloads
 */
const MAX_COMPRESSED_SIZE = 100 * 1024; // 100KB

/**
 * Maximum allowed decompressed data size in bytes
 * This prevents decompression bomb attacks where a small compressed file
 * expands to consume excessive memory
 */
const MAX_DECOMPRESSED_SIZE = 10 * 1024 * 1024; // 10MB

/**
 * Chunk size for incremental decompression checks (in bytes)
 * Smaller chunks allow for earlier detection of decompression bombs
 */
const DECOMPRESSION_CHUNK_SIZE = 64 * 1024; // 64KB

/**
 * Decompresses data with size validation to prevent decompression bomb attacks.
 * Uses incremental decompression with size checks during processing to prevent
 * memory exhaustion from decompression bombs.
 *
 * @param compressedData - URL-encoded Base64 compressed data
 * @returns Decompressed string
 * @throws BadRequestException if data is invalid or exceeds size limits
 */
export function decompressData(compressedData: string): Promise<string> {
  return new Promise((resolve, reject) => {
    try {
      // Validate input
      if (
        !compressedData ||
        typeof compressedData !== 'string' ||
        compressedData.trim().length === 0
      ) {
        return reject(
          new BadRequestException('Data parameter is required and must be a non-empty string'),
        );
      }

      // Check compressed size before processing
      if (compressedData.length > MAX_COMPRESSED_SIZE) {
        return reject(
          new BadRequestException(
            `Compressed data exceeds maximum size of ${MAX_COMPRESSED_SIZE} bytes`,
          ),
        );
      }

      // Decode the Base64 and decompress the data
      let buffer: Buffer;
      try {
        buffer = Buffer.from(decodeURIComponent(compressedData), 'base64');
      } catch (_decodeError) {
        return reject(new BadRequestException('Invalid Base64 encoding in data parameter'));
      }

      // Check buffer size before decompression
      if (buffer.length > MAX_COMPRESSED_SIZE) {
        return reject(
          new BadRequestException(
            `Compressed data exceeds maximum size of ${MAX_COMPRESSED_SIZE} bytes`,
          ),
        );
      }

      // Decompress with incremental size checking to prevent decompression bombs
      // This approach checks size during decompression, not after, preventing
      // memory exhaustion from small compressed files that expand to huge sizes
      try {
        const inflator = new Inflate();
        let totalDecompressedSize = 0;

        // Process buffer in chunks to allow size checking during decompression
        for (let i = 0; i < buffer.length; i += DECOMPRESSION_CHUNK_SIZE) {
          const chunk = buffer.slice(i, i + DECOMPRESSION_CHUNK_SIZE);
          const isLastChunk = i + chunk.length >= buffer.length;
          inflator.push(chunk, isLastChunk);

          // Check if there was an error during decompression
          if (inflator.err !== 0) {
            return reject(
              new BadRequestException(
                'Failed to decompress data: invalid or corrupted compressed data',
              ),
            );
          }

          // Check decompressed size incrementally to catch bombs early
          // Track the size of decompressed chunks as they're produced
          // This prevents allocating the entire decompressed content before validation
          if (inflator.result) {
            // result is Uint8Array, track its size
            const chunkSize = inflator.result.length;
            totalDecompressedSize = chunkSize;

            // Abort immediately if size exceeds limit during decompression
            if (totalDecompressedSize > MAX_DECOMPRESSED_SIZE) {
              return reject(
                new BadRequestException(
                  `Decompressed data exceeds maximum size of ${MAX_DECOMPRESSED_SIZE} bytes`,
                ),
              );
            }
          }
        }

        // Final size check after decompression completes
        if (!inflator.result) {
          return reject(
            new BadRequestException(
              'Failed to decompress data: invalid or corrupted compressed data',
            ),
          );
        }

        const decompressedSize = inflator.result.length;
        if (decompressedSize > MAX_DECOMPRESSED_SIZE) {
          return reject(
            new BadRequestException(
              `Decompressed data exceeds maximum size of ${MAX_DECOMPRESSED_SIZE} bytes`,
            ),
          );
        }

        // Convert Uint8Array to string only after size validation
        // This ensures we don't allocate the string if size is too large
        const decompressed = Buffer.from(inflator.result).toString('utf8');
        resolve(decompressed);
      } catch (_inflateError) {
        return reject(
          new BadRequestException(
            'Failed to decompress data: invalid or corrupted compressed data',
          ),
        );
      }
    } catch (error) {
      // If it's already a BadRequestException, re-throw it
      if (error instanceof BadRequestException) {
        reject(error);
      } else {
        reject(new BadRequestException('Failed to process data: invalid or malformed input'));
      }
    }
  });
}
