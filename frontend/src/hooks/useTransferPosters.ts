import { useMemo } from "react";
import { useWebhookNotifications } from "@/hooks/useWebhooks";

/**
 * Poster art for a transfer, resolved through the webhook that started it.
 *
 * Transfers carry no artwork of their own — the `transfers` table has no poster
 * column. Radarr/Sonarr notifications do, and each one records the
 * `transfer_id` it was synced under, so the two join exactly. Transfers started
 * by hand from the media browser have no webhook and no artwork anywhere in the
 * system; they fall back to the poster placeholder.
 *
 * The notifications query is shared with the webhooks rail and page, so this
 * costs no extra request. Its window (the 50 most recent notifications) is the
 * one limit: a transfer older than that window resolves to the placeholder.
 * Storing `poster_url` on the transfer itself would remove both caveats — see
 * the backend follow-up.
 */
export function useTransferPosters(): Map<string, string> {
  const { data } = useWebhookNotifications();

  return useMemo(() => {
    const posters = new Map<string, string>();
    for (const notification of data?.notifications ?? []) {
      const { transfer_id: transferId, poster_url: posterUrl } = notification;
      // A season pack links several notifications to one transfer; they share
      // the same series poster, so the first one wins.
      if (transferId && posterUrl && !posters.has(transferId)) {
        posters.set(transferId, posterUrl);
      }
    }
    return posters;
  }, [data]);
}
