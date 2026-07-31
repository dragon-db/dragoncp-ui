import { useEffect, useState } from "react";

/**
 * Follows a CSS media query from React.
 *
 * Layout belongs in CSS, so reach for this only when behaviour has to change
 * too — for example opening a side panel as a sheet on a narrow screen when
 * the same panel is already on screen on a wide one.
 */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(false);

  useEffect(() => {
    const list = window.matchMedia(query);
    const onChange = () => setMatches(list.matches);
    onChange();
    list.addEventListener("change", onChange);
    return () => list.removeEventListener("change", onChange);
  }, [query]);

  return matches;
}
