import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { useProwlarrSearch } from "@/stores/prowlarr-search";
import type { ProwlarrOverview, ReleaseRoute } from "@/lib/prowlarr-types";

/**
 * Prowlarr, through DragonCP. Prowlarr is on another machine; the server keeps
 * its indexer list, health and numbers for 30 seconds, so the Search tab's
 * picker and the Indexers tab share one read.
 */

export function useProwlarrOverview(enabled = true) {
  return useQuery({
    queryKey: ["prowlarr", "overview"],
    queryFn: async () => (await api.get<ProwlarrOverview>("/prowlarr/overview")).data,
    enabled,
    staleTime: 30_000,
    refetchInterval: 120_000,
    refetchIntervalInBackground: false,
  });
}

/** Ask Prowlarr for its state again now, past the server's 30-second copy. */
export function useRefreshOverview() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () =>
      (await api.get<ProwlarrOverview>("/prowlarr/overview", { params: { fresh: 1 } })).data,
    onSuccess: (data) => queryClient.setQueryData(["prowlarr", "overview"], data),
  });
}

export function useTestIndexer() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (indexerId: number) =>
      (
        await api.post<{ message: string; duration_ms: number }>(
          `/prowlarr/indexers/${indexerId}/test`
        )
      ).data,
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["prowlarr", "overview"] }),
  });
}

export function useGrabRelease() {
  const markGrabbed = useProwlarrSearch((state) => state.markGrabbed);
  return useMutation({
    mutationFn: async (vars: {
      searchId: string;
      releaseId: number;
      downloadClientId?: number | null;
    }) =>
      (
        await api.post<{ message: string }>(
          `/prowlarr/search/${vars.searchId}/releases/${vars.releaseId}/grab`,
          { download_client_id: vars.downloadClientId ?? null }
        )
      ).data,
    onSuccess: (_data, vars) => markGrabbed(vars.releaseId),
  });
}

/**
 * Where a release lands and whether Sonarr or Radarr will import it; once
 * sent, where it is in their queue. Asked again every 15 seconds after a send
 * while the sheet is open, until the release is imported.
 */
export function useReleaseRoute(searchId: string, releaseId: number, sent: boolean) {
  return useQuery({
    queryKey: ["prowlarr", "route", searchId, releaseId, sent],
    queryFn: async () =>
      (await api.get<ReleaseRoute>(`/prowlarr/search/${searchId}/releases/${releaseId}/route`))
        .data,
    staleTime: sent ? 0 : 60_000,
    retry: false,
    refetchInterval: (query) => {
      const tracking = query.state.data?.tracking ?? [];
      if (!sent || tracking.length === 0) return false;
      return tracking.every((t) => t.state === "imported" || t.state === "off") ? false : 15_000;
    },
    refetchIntervalInBackground: false,
  });
}

export async function fetchMagnet(searchId: string, releaseId: number): Promise<string> {
  const { data } = await api.get<{ magnet: string }>(
    `/prowlarr/search/${searchId}/releases/${releaseId}/magnet`
  );
  return data.magnet;
}

/**
 * Save the release's .torrent or .nzb on this device. A release whose
 * "file" turns out to be a magnet link opens that link instead, which on a
 * phone hands it to whichever torrent app is installed.
 */
export async function downloadReleaseFile(searchId: string, releaseId: number) {
  const response = await api.get<Blob>(`/prowlarr/search/${searchId}/releases/${releaseId}/file`, {
    responseType: "blob",
  });
  const type = String(response.headers["content-type"] ?? "");
  if (type.includes("application/json")) {
    const body = JSON.parse(await response.data.text()) as { magnet?: string };
    if (body.magnet) window.location.href = body.magnet;
    return;
  }
  const disposition = String(response.headers["content-disposition"] ?? "");
  const name = /filename\*=UTF-8''([^;]+)/i.exec(disposition)?.[1];
  const plain = /filename="([^"]+)"/i.exec(disposition)?.[1];
  const url = URL.createObjectURL(response.data);
  const link = document.createElement("a");
  link.href = url;
  link.download = name ? decodeURIComponent(name) : (plain ?? "release");
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
}

/**
 * Put text on the clipboard. DragonCP is usually reached over plain http at a
 * private address, where browsers withhold the clipboard API; the old
 * select-and-copy route still works there in most browsers while the tap is
 * fresh. False when neither did, so the caller can show the text instead.
 */
export async function copyText(text: string): Promise<boolean> {
  if (window.isSecureContext && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // Fall through to the old route.
    }
  }
  const area = document.createElement("textarea");
  area.value = text;
  area.setAttribute("readonly", "");
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.appendChild(area);
  area.select();
  area.setSelectionRange(0, text.length);
  let copied = false;
  try {
    copied = document.execCommand("copy");
  } catch {
    copied = false;
  }
  area.remove();
  return copied;
}

/**
 * Copy a magnet link the server has to fetch first.
 *
 * Safari only lets a page write to the clipboard during the tap itself, and
 * the link arrives after it. On a secure connection, handing the clipboard a
 * promise keeps the tap's permission while the link is fetched; elsewhere the
 * link is copied the old way once it arrives. `copied` is false when the
 * browser allowed neither, and the sheet then shows the link to select.
 */
export async function copyMagnet(
  searchId: string,
  releaseId: number
): Promise<{ magnet: string; copied: boolean }> {
  const pending = fetchMagnet(searchId, releaseId);
  if (
    window.isSecureContext &&
    typeof ClipboardItem !== "undefined" &&
    navigator.clipboard?.write
  ) {
    try {
      await navigator.clipboard.write([
        new ClipboardItem({
          "text/plain": pending.then((magnet) => new Blob([magnet], { type: "text/plain" })),
        }),
      ]);
      return { magnet: await pending, copied: true };
    } catch {
      // Fall through: some browsers refuse a promised item.
    }
  }
  const magnet = await pending;
  return { magnet, copied: await copyText(magnet) };
}
