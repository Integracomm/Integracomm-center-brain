import { useCallback, useEffect, useState } from "react";
import { apiGet } from "@/api/client";

// Hook mínimo de fetch (sem react-query no Lote 1 — deps enxutas).
// Recarrega quando o `path` muda; `refetch` para o botão de erro.
export function useApi<T>(path: string) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let vivo = true;
    setLoading(true);
    setError(null);
    apiGet<T>(path)
      .then((d) => vivo && setData(d))
      .catch((e) => vivo && setError(e instanceof Error ? e.message : String(e)))
      .finally(() => vivo && setLoading(false));
    return () => {
      vivo = false;
    };
  }, [path, tick]);

  const refetch = useCallback(() => setTick((t) => t + 1), []);
  return { data, error, loading, refetch };
}
