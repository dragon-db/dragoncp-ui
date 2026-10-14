import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";

/**
 * Connectors — the outside services this app talks to.
 *
 * Nothing here ever receives a credential. The server stores them in their own
 * table with no read path to a response body, and what comes back instead is
 * `secrets_set`: whether a value exists. A field can therefore say "configured"
 * without ever having been shown what it holds.
 */

/** One input on a connector's settings form, described by the server. */
export interface ConnectorField {
  name: string;
  label: string;
  description: string;
  /** text | password | url | boolean | number */
  kind: string;
  /** Stored out of reach; the client is never sent its value. */
  secret: boolean;
  required: boolean;
  placeholder: string;
}

/** A place announcements can be sent — a named Discord webhook. */
export interface ConnectorTarget {
  target_id: string;
  connector_id: string;
  label: string;
  is_default: boolean;
  enabled: boolean;
  last_send_at: string | null;
  last_send_ok: boolean | null;
  last_send_error: string | null;
  created_at: string;
}

export interface Connector {
  id: string;
  display_name: string;
  description: string;
  capabilities: string[];
  config_fields: ConnectorField[];
  /** What the settings form is called. "Connection" for most; Discord's holds
   *  only presentation, so it calls itself "Appearance". */
  settings_label: string;
  settings_description: string;
  /** False when the connector has no endpoint to reach at this level, so the
   *  UI must not offer a test that cannot fail. */
  supports_check: boolean;
  enabled: boolean;
  configured: boolean;
  config: Record<string, string>;
  /** Which secret-backed fields have a value stored. Never the values. */
  secrets_set: Record<string, boolean>;
  last_check_at: string | null;
  last_check_ok: boolean | null;
  last_check_message: string | null;
  /** False until the connector has been saved even once. */
  exists: boolean;
  target_noun?: string;
  targets?: ConnectorTarget[];
}

/** Where one announcement goes, per connector. */
export interface EventRoute {
  target_id: string | null;
  enabled: boolean;
  /** True when no destination was chosen, so the default is used. */
  using_default: boolean;
}

export interface CatalogueEvent {
  key: string;
  label: string;
  description: string;
  default_severity: string;
  routes: Record<string, EventRoute>;
}

export interface Delivery {
  id: number;
  connector_id: string;
  target_label: string | null;
  event_key: string | null;
  title: string | null;
  ok: boolean;
  skipped_reason: string | null;
  status_code: number | null;
  error: string | null;
  duration_ms: number;
  created_at: string;
}

export interface CheckResult {
  ok: boolean;
  message: string;
  detail: Record<string, unknown>;
}

/** What the server sends back for a secret it will not disclose. */
export const REDACTED = "<redacted>";

export function useConnectors() {
  return useQuery({
    queryKey: ["connectors"],
    queryFn: async () => {
      const response = await api.get<{ status: string; connectors: Connector[] }>("/connectors");
      return response.data.connectors;
    },
  });
}

export function useConnector(connectorId: string) {
  return useQuery({
    queryKey: ["connectors", connectorId],
    queryFn: async () => {
      const response = await api.get<{ status: string; connector: Connector }>(
        `/connectors/${connectorId}`
      );
      return response.data.connector;
    },
    enabled: Boolean(connectorId),
  });
}

export function useNotificationCatalogue() {
  return useQuery({
    queryKey: ["connectors", "events"],
    queryFn: async () => {
      const response = await api.get<{
        status: string;
        events: CatalogueEvent[];
        connectors: { id: string; display_name: string; targets: ConnectorTarget[] }[];
      }>("/connectors/events");
      return response.data;
    },
  });
}

export function useDeliveries(connectorId: string) {
  return useQuery({
    queryKey: ["connectors", connectorId, "deliveries"],
    queryFn: async () => {
      const response = await api.get<{ status: string; deliveries: Delivery[] }>(
        `/connectors/${connectorId}/deliveries`
      );
      return response.data.deliveries;
    },
    enabled: Boolean(connectorId),
  });
}

/**
 * Everything that changes a connector invalidates the whole `connectors` tree.
 * Adding a webhook changes the connector, the destination list *and* which
 * choices the routing table can offer — keeping three keys in step by hand is
 * how a dropdown ends up offering something that was just deleted.
 */
function useConnectorMutation<TVariables, TData = unknown>(
  fn: (variables: TVariables) => Promise<TData>
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["connectors"] });
    },
  });
}

export function useSaveConnector(connectorId: string) {
  return useConnectorMutation(
    async (payload: { enabled?: boolean; config?: Record<string, string> }) => {
      const response = await api.post(`/connectors/${connectorId}`, payload);
      return response.data;
    }
  );
}

export function useCheckConnector(connectorId: string) {
  return useConnectorMutation<void, CheckResult>(async () => {
    const response = await api.post<{ status: string; result: CheckResult }>(
      `/connectors/${connectorId}/check`
    );
    return response.data.result;
  });
}

export function useAddTarget(connectorId: string) {
  return useConnectorMutation(
    async (payload: { label: string; credential: string; make_default?: boolean }) => {
      const response = await api.post(`/connectors/${connectorId}/targets`, payload);
      return response.data;
    }
  );
}

export function useUpdateTarget(connectorId: string) {
  return useConnectorMutation(
    async ({
      targetId,
      ...payload
    }: {
      targetId: string;
      label?: string;
      credential?: string;
      enabled?: boolean;
      make_default?: boolean;
    }) => {
      const response = await api.patch(`/connectors/${connectorId}/targets/${targetId}`, payload);
      return response.data;
    }
  );
}

export function useDeleteTarget(connectorId: string) {
  return useConnectorMutation(async (targetId: string) => {
    const response = await api.delete(`/connectors/${connectorId}/targets/${targetId}`);
    return response.data;
  });
}

export function useTestTarget(connectorId: string) {
  return useConnectorMutation(async (targetId: string) => {
    const response = await api.post(`/connectors/${connectorId}/targets/${targetId}/test`);
    return response.data;
  });
}

export function useSaveRoutes() {
  return useConnectorMutation(
    async (
      routes: {
        event_key: string;
        connector_id: string;
        target_id: string | null;
        enabled: boolean;
      }[]
    ) => {
      const response = await api.put("/connectors/routes", { routes });
      return response.data;
    }
  );
}
