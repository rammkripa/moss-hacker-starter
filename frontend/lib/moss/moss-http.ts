// Moss REST wrapper for /api/mission/ingest writes.
//
// Verified against https://docs.moss.dev/docs/api-reference/v1/document-operations/addDocs
// All mutations route through POST /v1/manage with action="addDocs".
//
// Moss serializes builds per-index — concurrent addDocs calls on the same
// index return HTTP 409 "A build is already in progress". This wrapper
// queues calls per-index and retries 409s with linear backoff.

export type MossDocumentInput = {
  id: string;
  text: string;
  metadata?: Record<string, string>;
};

type MossAddDocsResponse = {
  jobId?: string;
  job_id?: string;
};

// Per-index serialization: every call chains onto the previous Promise so
// only one HTTP request per index is in flight at a time.
const _queues = new Map<string, Promise<unknown>>();

export async function mossAddDocs(
  indexName: string,
  docs: MossDocumentInput[]
): Promise<MossAddDocsResponse> {
  const prev = _queues.get(indexName) ?? Promise.resolve();
  const next = prev
    .catch(() => undefined) // do not let a prior failure poison this slot
    .then(() => _addDocsOnce(indexName, docs));
  _queues.set(indexName, next);
  return next;
}

async function _addDocsOnce(
  indexName: string,
  docs: MossDocumentInput[]
): Promise<MossAddDocsResponse> {
  const projectId = process.env.MOSS_PROJECT_ID;
  const projectKey = process.env.MOSS_PROJECT_KEY;
  if (!projectId || !projectKey) {
    throw new Error('MOSS_PROJECT_ID and MOSS_PROJECT_KEY must be set');
  }
  const base = process.env.MOSS_API_BASE_URL ?? 'https://service.usemoss.dev/v1';

  const body = JSON.stringify({
    action: 'addDocs',
    projectId,
    indexName,
    docs,
    options: { upsert: true },
  });

  // Up to 4 attempts with linear backoff. Retries on:
  //   - HTTP 409 (build already in progress)
  //   - Connection errors / timeouts (transient network blips)
  //   - HTTP 5xx (server error)
  const delays = [600, 1500, 2500, 4000];
  let lastError = '(no body)';

  for (let attempt = 0; attempt < delays.length; attempt++) {
    let res: Response;
    try {
      res = await fetch(`${base}/manage`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'x-service-version': 'v1',
          'x-project-key': projectKey,
        },
        body,
      });
    } catch (err) {
      // Network error (DNS, connection refused, timeout). Retry.
      lastError = err instanceof Error ? err.message : String(err);
      if (attempt < delays.length - 1) {
        await new Promise((r) => setTimeout(r, delays[attempt]));
        continue;
      }
      throw new Error(`Moss addDocs network error after retries: ${lastError}`);
    }

    if (res.ok) {
      return (await res.json()) as MossAddDocsResponse;
    }

    lastError = await res.text().catch(() => '(no body)');

    // Retry on 409 (build serialization) or 5xx (transient server issue)
    const retryable = res.status === 409 || res.status >= 500;
    if (retryable && attempt < delays.length - 1) {
      await new Promise((r) => setTimeout(r, delays[attempt]));
      continue;
    }

    throw new Error(`Moss addDocs failed: HTTP ${res.status} — ${lastError}`);
  }

  throw new Error(`Moss addDocs failed after retries: ${lastError}`);
}
