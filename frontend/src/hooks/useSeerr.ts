import { useEffect } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { getSocket } from "@/services/socket";
import type {
  IssuesPage,
  RequestChanges,
  RequestOptions,
  RequestsPage,
  SeerrIssue,
  SeerrPerson,
  SeerrSummary,
} from "@/lib/seerr-types";

/**
 * Seerr, through DragonCP. Seerr is on the media server; the server keeps
 * each of its answers for a few seconds and drops them the moment Seerr's
 * webhook (or a change made here) says something moved, then tells every open
 * page over the socket, which refetches.
 */

/** Refetch everything Seerr when the server says something changed. */
export function useSeerrLive(enabled = true) {
  const queryClient = useQueryClient();
  useEffect(() => {
    const socket = getSocket();
    if (!socket || !enabled) return;
    const refresh = () => queryClient.invalidateQueries({ queryKey: ["seerr"] });
    socket.on("seerr_changed", refresh);
    return () => {
      socket.off("seerr_changed", refresh);
    };
  }, [enabled, queryClient]);
}

export function useSeerrSummary(enabled = true) {
  return useQuery({
    queryKey: ["seerr", "summary"],
    queryFn: async () => (await api.get<SeerrSummary>("/seerr/summary")).data,
    enabled,
    refetchInterval: 60_000,
    staleTime: 20_000,
  });
}

export interface RequestsFilter {
  view: string;
  type: string;
  sort: string;
  user: string;
  take: number;
  skip: number;
}

export function useSeerrRequests(filter: RequestsFilter, enabled = true) {
  return useQuery({
    queryKey: ["seerr", "requests", filter],
    queryFn: async () => {
      const params: Record<string, string | number> = {
        view: filter.view,
        type: filter.type,
        sort: filter.sort,
        take: filter.take,
        skip: filter.skip,
      };
      if (filter.user) params.user = filter.user;
      return (await api.get<RequestsPage>("/seerr/requests", { params })).data;
    },
    enabled,
    placeholderData: keepPreviousData,
    // Download progress moves once a minute inside Seerr; a sync here moves
    // faster, so in-progress lists are asked a little more often.
    refetchInterval: filter.view === "progress" ? 20_000 : 60_000,
    refetchIntervalInBackground: false,
  });
}

export interface IssuesFilter {
  view: string;
  sort: string;
  user: string;
  take: number;
  skip: number;
}

export function useSeerrIssues(filter: IssuesFilter, enabled = true) {
  return useQuery({
    queryKey: ["seerr", "issues", filter],
    queryFn: async () => {
      const params: Record<string, string | number> = {
        view: filter.view,
        sort: filter.sort,
        take: filter.take,
        skip: filter.skip,
      };
      if (filter.user) params.user = filter.user;
      return (await api.get<IssuesPage>("/seerr/issues", { params })).data;
    },
    enabled,
    placeholderData: keepPreviousData,
    refetchInterval: 60_000,
    refetchIntervalInBackground: false,
  });
}

export function useSeerrIssue(issueId: number | null) {
  return useQuery({
    queryKey: ["seerr", "issue", issueId],
    queryFn: async () =>
      (
        await api.get<{ issue: SeerrIssue; can_change: boolean; why_not: string }>(
          `/seerr/issues/${issueId}`
        )
      ).data,
    enabled: issueId != null,
  });
}

export function useSeerrUsers(enabled = true) {
  return useQuery({
    queryKey: ["seerr", "users"],
    queryFn: async () => (await api.get<{ users: SeerrPerson[] }>("/seerr/users")).data.users,
    enabled,
    staleTime: 600_000,
  });
}

export function useRequestOptions(requestId: number | null, serverId: number | null) {
  return useQuery({
    queryKey: ["seerr", "options", requestId, serverId],
    queryFn: async () => {
      const params: Record<string, number> = {};
      if (serverId != null) params.server = serverId;
      return (await api.get<RequestOptions>(`/seerr/requests/${requestId}/options`, { params }))
        .data;
    },
    enabled: requestId != null,
    staleTime: 300_000,
    retry: false,
  });
}

function useSeerrMutation<T>(fn: (input: T) => Promise<unknown>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: fn,
    // Whatever happened, the list is refetched: a refusal because the request
    // had already been approved elsewhere is itself news.
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["seerr"] }),
  });
}

export function useDecideRequest() {
  return useSeerrMutation(
    async ({
      id,
      decision,
      changes,
    }: {
      id: number;
      decision: "approve" | "decline" | "retry";
      changes?: RequestChanges;
    }) => (await api.post(`/seerr/requests/${id}/${decision}`, changes ? { changes } : {})).data
  );
}

export function useReplyToIssue() {
  return useSeerrMutation(
    async ({ id, message, resolve }: { id: number; message: string; resolve: boolean }) =>
      (await api.post(`/seerr/issues/${id}/comment`, { message, resolve })).data
  );
}

export function useSetIssueState() {
  return useSeerrMutation(
    async ({ id, state }: { id: number; state: "resolve" | "reopen" }) =>
      (await api.post(`/seerr/issues/${id}/${state}`, {})).data
  );
}
