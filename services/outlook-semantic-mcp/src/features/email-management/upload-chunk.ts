export async function uploadChunk(
  uploadUrl: string,
  chunk: Buffer,
  offset: number,
  total: number,
): Promise<void> {
  const end = offset + chunk.length - 1;
  const response = await fetch(uploadUrl, {
    method: 'PUT',
    headers: {
      'Content-Length': String(chunk.length),
      'Content-Range': `bytes ${offset}-${end}/${total}`,
      'Content-Type': 'application/octet-stream',
    },
    body: chunk as BodyInit,
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Upload session chunk failed (${response.status}): ${text}`);
  }
}
