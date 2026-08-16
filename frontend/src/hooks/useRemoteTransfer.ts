import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";

/**
 * The transfer server on the remote host.
 *
 * Every status read opens an SSH connection and asks the transfer server
 * itself, which costs a few seconds on a long link — so this deliberately does
 * NOT poll. It loads once and refreshes when asked. A status card quietly
 * spending four seconds of round trips every few seconds, for a value that
 * changes when somebody presses a button, is not worth it.
 */

export type RemoteTransferHealthState =
  "ready" | "blocked" | "auth_failed" | "unreachable" | "error";

export interface RemoteTransferStatus {
  configured: boolean;
  configuration_problem: string;
  host_set: boolean;
  port: number;
  access_mode: string;
  has_allowed_address: boolean;
  start_at_boot: boolean;
  enabled_for_transfers: boolean;
  libraries: string[];
  password_stored: boolean;
  /**
   * Why the stored password could not be read, when that is the situation.
   *
   * Separate from `password_file_secure` because they call for different
   * remedies. A file others can read is fixed by rotating it; a file this
   * server cannot read is a permissions problem on the file itself, and
   * rotating would not touch it.
   */
  password_problem: string | null;
  password_file_secure: boolean;
  installed: boolean | null;
  service_state: string | null;
  service_enabled: string | null;
  lifecycle_matches: boolean | null;
  up_to_date: boolean | null;
  address_matches: boolean | null;
  detected_address_differs: boolean | null;
  reachable_over_ssh: boolean | null;
  problem: string | null;
  summary: string;
  health: {
    state: RemoteTransferHealthState;
    detail: string;
    ok: boolean;
    running: boolean;
  };
}

interface StatusResponse {
  status: string;
  server: RemoteTransferStatus;
}

interface ActionResponse {
  status: string;
  message: string;
}

export interface DetectedAddress {
  status: string;
  address: string;
  matches_configured: boolean;
  configured: boolean;
}

const KEY = ["remote-transfer", "status"];

export function useRemoteTransferStatus(enabled = true) {
  return useQuery({
    queryKey: KEY,
    queryFn: async () => {
      const response = await api.get<StatusResponse>("/remote-transfer/status");
      return response.data.server;
    },
    enabled,
    refetchOnWindowFocus: false,
    refetchInterval: false,
    staleTime: 15_000,
    retry: false,
  });
}

/**
 * One hook for every button.
 *
 * They all do the same thing — POST, then re-read the status — and giving each
 * its own hook only creates places for one of them to forget the re-read and
 * leave the card showing what was true before the button was pressed.
 */
export function useRemoteTransferAction() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (
      action: "install" | "start" | "stop" | "restart" | "uninstall" | "rotate-password"
    ) => {
      const response = await api.post<ActionResponse>(`/remote-transfer/${action}`);
      return response.data;
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: KEY });
      queryClient.invalidateQueries({ queryKey: ["config"] });
    },
  });
}

/**
 * Ask the remote host what address this server appears to connect from.
 *
 * The answer is shown to the admin who asked and is not stored anywhere by
 * this call — putting it into the environment file is a deliberate, separate
 * act on the server.
 */
export function useDetectAddress() {
  return useMutation({
    mutationFn: async () => {
      const response = await api.get<DetectedAddress>("/remote-transfer/detect-address");
      return response.data;
    },
  });
}
