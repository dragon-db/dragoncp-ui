/**
 * The server's own explanation of a failure, when it sent one.
 *
 * Every route in this app answers a refusal with `{status, message}`, and that
 * message is written for the operator — "That is not a Discord address" beats
 * "Request failed with status code 400". The fallback is only for a request
 * that never reached a handler.
 */
export function errorText(error: unknown, fallback: string) {
  const message = (error as { response?: { data?: { message?: string } } })?.response?.data
    ?.message;
  return message || fallback;
}
