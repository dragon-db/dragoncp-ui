import { useEffect, useState } from "react";

/**
 * Waits for a value to settle before letting it out.
 *
 * List searches run against the database rather than the rows already on
 * screen, so without this a request would go out per keystroke.
 */
export function useDebouncedValue<T>(value: T, delay = 300): T {
  const [settled, setSettled] = useState(value);

  useEffect(() => {
    const id = window.setTimeout(() => setSettled(value), delay);
    return () => window.clearTimeout(id);
  }, [value, delay]);

  return settled;
}
