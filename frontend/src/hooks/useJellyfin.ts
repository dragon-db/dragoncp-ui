import { keepPreviousData, useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import type { NowPlaying, PlaysPage } from "@/lib/jellyfin-types";

/**
 * What Jellyfin is playing, asked every 5 seconds while the tab is open.
 *
 * Jellyfin is on the media server, so each ask is a local one. The server
 * answers two asks less than two seconds apart with the same reading, and
 * each reading also feeds the play record when that is switched on.
 */
export function useNowPlaying(enabled = true) {
  return useQuery({
    queryKey: ["jellyfin", "now-playing"],
    queryFn: async () => (await api.get<NowPlaying>("/jellyfin/now-playing")).data,
    enabled,
    refetchInterval: 5_000,
    refetchIntervalInBackground: false,
    staleTime: 2_000,
  });
}

export interface PlaysFilter {
  limit: number;
  offset: number;
  user: string;
  /** all | converted | direct */
  converted: string;
  q: string;
}

export function usePlays(filter: PlaysFilter, enabled = true) {
  return useQuery({
    queryKey: ["jellyfin", "plays", filter],
    queryFn: async () => {
      const params: Record<string, string | number> = {
        limit: filter.limit,
        offset: filter.offset,
      };
      if (filter.user) params.user = filter.user;
      if (filter.q) params.q = filter.q;
      if (filter.converted === "converted") params.converted = 1;
      if (filter.converted === "direct") params.converted = 0;
      return (await api.get<PlaysPage>("/jellyfin/plays", { params })).data;
    },
    enabled,
    placeholderData: keepPreviousData,
    refetchInterval: 30_000,
  });
}
