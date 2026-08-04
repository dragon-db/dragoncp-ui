import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { activityApi, type ActivityQuery } from "@/lib/api";

/**
 * A page of the activity trail.
 *
 * `keepPreviousData` so paging and changing a filter do not blank the list —
 * this is a screen people scan while reading, and flashing it empty on every
 * keystroke makes it unreadable.
 */
export function useActivity(query: ActivityQuery) {
  return useQuery({
    queryKey: ["activity", query],
    queryFn: () => activityApi.list(query),
    placeholderData: keepPreviousData,
    staleTime: 1000 * 15,
  });
}

export function useActivityFilters() {
  return useQuery({
    queryKey: ["activity", "filters"],
    queryFn: () => activityApi.filters(),
    staleTime: 1000 * 60 * 5,
  });
}

/** Everything recorded against one thing, oldest first. */
export function useActivityForTarget(targetType: string, targetId?: string | null) {
  return useQuery({
    queryKey: ["activity", "target", targetType, targetId],
    queryFn: () => activityApi.forTarget(targetType, targetId!),
    enabled: !!targetId,
    staleTime: 1000 * 30,
  });
}
