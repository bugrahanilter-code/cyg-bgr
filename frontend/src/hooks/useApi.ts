/**
 * Small wrappers around React Query so pages never repeat polling settings.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { UseMutationOptions, UseQueryOptions } from "@tanstack/react-query";

export const REFRESH_FAST = 3_000;
export const REFRESH_NORMAL = 8_000;
export const REFRESH_SLOW = 30_000;

export function usePolledQuery<T>(
  key: unknown[],
  queryFn: () => Promise<T>,
  intervalMs: number = REFRESH_NORMAL,
  options?: Partial<UseQueryOptions<T, Error, T, readonly unknown[]>>,
) {
  return useQuery<T, Error, T, readonly unknown[]>({
    queryKey: key,
    queryFn,
    refetchInterval: intervalMs,
    refetchOnWindowFocus: true,
    staleTime: Math.max(1000, intervalMs / 2),
    retry: 1,
    ...options,
  });
}

export function useOnceQuery<T>(
  key: unknown[],
  queryFn: () => Promise<T>,
  options?: Partial<UseQueryOptions<T, Error, T, readonly unknown[]>>,
) {
  return useQuery<T, Error, T, readonly unknown[]>({
    queryKey: key,
    queryFn,
    refetchOnWindowFocus: false,
    retry: 1,
    ...options,
  });
}

export function useApiMutation<TData, TVariables>(
  mutationFn: (variables: TVariables) => Promise<TData>,
  invalidateKeys: unknown[][] = [],
  options?: UseMutationOptions<TData, Error, TVariables>,
) {
  const queryClient = useQueryClient();
  type SuccessHandler = NonNullable<UseMutationOptions<TData, Error, TVariables>["onSuccess"]>;
  return useMutation<TData, Error, TVariables>({
    mutationFn,
    ...options,
    // The argument list of onSuccess changed between TanStack Query releases,
    // so it is forwarded verbatim instead of being destructured.
    onSuccess: (...args: Parameters<SuccessHandler>) => {
      invalidateKeys.forEach((key) => {
        void queryClient.invalidateQueries({ queryKey: key });
      });
      return options?.onSuccess?.(...args);
    },
  });
}
