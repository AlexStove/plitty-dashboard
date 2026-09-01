export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export interface ApiOptions extends RequestInit {
  timeoutMs?: number;
}

export async function api<T = unknown>(path: string, opts: ApiOptions = {}): Promise<T> {
  const { timeoutMs = 30_000, ...init } = opts;
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(path, { ...init, signal: ctrl.signal });
    if (!res.ok) {
      let message = `HTTP ${res.status}`;
      try {
        const payload = (await res.json()) as { message?: string; error?: string };
        message = payload.message || payload.error || message;
      } catch {
        // Keep the HTTP status fallback for non-JSON responses.
      }
      throw new ApiError(res.status, message);
    }
    return (await res.json()) as T;
  } finally {
    clearTimeout(timer);
  }
}

export const jsonPost = <T = unknown>(path: string, body: unknown, timeoutMs?: number) =>
  api<T>(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    timeoutMs,
  });

export const isValidSpotifyUrl = (u: string) =>
  /^https?:\/\/(open\.)?spotify\.com\/(track|artist|album|playlist)\/[A-Za-z0-9]+/.test(u.trim());
