/**
 * Thin fetch wrapper.
 *
 * Every network call in the application goes through this module: there is
 * exactly one place that knows the base URL, the error format and the
 * timeouts.
 */

const BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "/api";
const DEFAULT_TIMEOUT_MS = 60_000;

export class ApiError extends Error {
  readonly status: number;
  readonly details: unknown;

  constructor(message: string, status: number, details?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.details = details;
  }
}

interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "DELETE";
  body?: unknown;
  params?: Record<string, string | number | boolean | undefined | null>;
  timeoutMs?: number;
}

function buildUrl(path: string, params?: RequestOptions["params"]): string {
  const url = BASE_URL.replace(/\/$/, "") + path;
  if (!params) {
    return url;
  }
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      search.append(key, String(value));
    }
  });
  const query = search.toString();
  return query ? url + "?" + query : url;
}

async function extractError(response: Response): Promise<never> {
  let message = response.statusText || "Request failed";
  let details: unknown;
  try {
    const payload = await response.json();
    details = payload;
    if (typeof payload?.detail === "string") {
      message = payload.detail;
    } else if (typeof payload?.message === "string") {
      message = payload.message;
    } else if (Array.isArray(payload?.detail) && payload.detail.length > 0) {
      message = payload.detail
        .map((item: { loc?: string[]; msg?: string }) =>
          [item.loc?.slice(-1)[0], item.msg].filter(Boolean).join(": "),
        )
        .join("; ");
    }
  } catch {
    // response had no JSON body
  }
  throw new ApiError(message, response.status, details);
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const controller = new AbortController();
  const timeout = window.setTimeout(
    () => controller.abort(),
    options.timeoutMs ?? DEFAULT_TIMEOUT_MS,
  );

  try {
    const response = await fetch(buildUrl(path, options.params), {
      method: options.method ?? "GET",
      headers: options.body ? { "Content-Type": "application/json" } : undefined,
      body: options.body ? JSON.stringify(options.body) : undefined,
      signal: controller.signal,
    });

    if (!response.ok) {
      await extractError(response);
    }
    if (response.status === 204) {
      return undefined as T;
    }
    return (await response.json()) as T;
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new ApiError("The request timed out. Is the backend running?", 408);
    }
    throw new ApiError(
      error instanceof Error ? error.message : "Network error",
      0,
      error,
    );
  } finally {
    window.clearTimeout(timeout);
  }
}

export const api = {
  get: <T>(path: string, params?: RequestOptions["params"], timeoutMs?: number) =>
    request<T>(path, { params, timeoutMs }),
  post: <T>(path: string, body?: unknown, timeoutMs?: number) =>
    request<T>(path, { method: "POST", body, timeoutMs }),
  put: <T>(path: string, body?: unknown) => request<T>(path, { method: "PUT", body }),
  delete: <T>(path: string) => request<T>(path, { method: "DELETE" }),
};
