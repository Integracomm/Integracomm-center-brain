// Cliente HTTP do SPA — mesma origem do FastAPI: o cookie de sessão
// (`iasession`, httponly) segue automaticamente em toda chamada.
// 401 = sessão expirada/ausente -> volta ao /login do backend (HTML).
export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function apiGet<T>(path: string): Promise<T> {
  const r = await fetch(path, { headers: { Accept: "application/json" } });
  if (r.status === 401) {
    window.location.href = "/login";
    throw new ApiError(401, "não autenticado");
  }
  if (!r.ok) {
    let msg = `HTTP ${r.status}`;
    try {
      const j = await r.json();
      msg = j.error || j.detail || msg;
    } catch {
      /* corpo não-JSON — mantém o status */
    }
    throw new ApiError(r.status, msg);
  }
  return r.json() as Promise<T>;
}

export async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (r.status === 401) {
    window.location.href = "/login";
    throw new ApiError(401, "não autenticado");
  }
  if (!r.ok) {
    let msg = `HTTP ${r.status}`;
    try {
      const j = await r.json();
      msg = j.error || j.detail || msg;
    } catch {
      /* idem */
    }
    throw new ApiError(r.status, msg);
  }
  return r.json() as Promise<T>;
}
