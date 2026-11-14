import { create } from "zustand";
import { persist } from "zustand/middleware";
import api from "@/lib/api";
import { libraryError } from "@/components/integrations/library-vocab";
import type {
  ProwlarrRelease,
  SearchIndexerRow,
  SearchPoll,
  SearchRequest,
} from "@/lib/prowlarr-types";

/**
 * The search on screen, kept outside the page so switching to the Indexers
 * tab and back, or to another page and back, keeps what was found.
 *
 * The server asks each indexer on its own and files the results as they come;
 * this asks it every POLL_MS for what is new since last time, until every
 * indexer has answered. Only new releases travel, so a phone on a weak signal
 * is not sent the same thousand rows twice a second.
 */
const POLL_MS = 600;
/** How many past searches the box offers again. */
const RECENT_LIMIT = 10;

interface SearchState {
  request: SearchRequest | null;
  searchId: string | null;
  releases: ProwlarrRelease[];
  indexers: SearchIndexerRow[];
  running: boolean;
  starting: boolean;
  reused: boolean;
  /** When the server started the search: a reused one can be minutes old. */
  serverStarted: string | null;
  error: string | null;
  startedAt: number | null;
  finishedAt: number | null;
  start: (request: SearchRequest) => Promise<void>;
  markGrabbed: (releaseId: number) => void;
  clear: () => void;
}

/** Bumped by every new search, so an older search's polling stops on its own. */
let generation = 0;

export const useProwlarrSearch = create<SearchState>()((set) => {
  const poll = async (searchId: string, mine: number, cursor: number) => {
    if (mine !== generation) return;
    try {
      const { data } = await api.get<{ search: SearchPoll }>(`/prowlarr/search/${searchId}`, {
        params: { cursor },
      });
      if (mine !== generation) return;
      const search = data.search;
      const grabbed = new Set(search.grabbed);
      set((state) => ({
        releases: [...state.releases, ...search.releases].map((release) =>
          grabbed.has(release.id) && !release.grabbed ? { ...release, grabbed: true } : release
        ),
        indexers: search.indexers,
        serverStarted: search.started,
        running: search.running,
        finishedAt: search.running ? null : Date.now(),
      }));
      if (search.running) {
        window.setTimeout(() => poll(searchId, mine, search.cursor), POLL_MS);
      }
    } catch (failure) {
      if (mine !== generation) return;
      set({ running: false, error: libraryError(failure, "Lost track of the search.") });
    }
  };

  return {
    request: null,
    searchId: null,
    releases: [],
    indexers: [],
    running: false,
    starting: false,
    reused: false,
    serverStarted: null,
    error: null,
    startedAt: null,
    finishedAt: null,

    start: async (request) => {
      const mine = ++generation;
      set({
        request,
        searchId: null,
        releases: [],
        indexers: [],
        running: false,
        starting: true,
        reused: false,
        serverStarted: null,
        error: null,
        startedAt: Date.now(),
        finishedAt: null,
      });
      useRecentSearches.getState().remember(request);
      try {
        const { data } = await api.post<{ search_id: string; reused: boolean }>(
          "/prowlarr/search",
          request
        );
        if (mine !== generation) return;
        set({ searchId: data.search_id, reused: data.reused, running: true, starting: false });
        await poll(data.search_id, mine, 0);
      } catch (failure) {
        if (mine !== generation) return;
        set({
          starting: false,
          error: libraryError(failure, "Prowlarr did not start the search."),
        });
      }
    },

    markGrabbed: (releaseId) =>
      set((state) => ({
        releases: state.releases.map((release) =>
          release.id === releaseId ? { ...release, grabbed: true } : release
        ),
      })),

    clear: () => {
      generation += 1;
      set({
        request: null,
        searchId: null,
        releases: [],
        indexers: [],
        running: false,
        starting: false,
        reused: false,
        serverStarted: null,
        error: null,
        startedAt: null,
        finishedAt: null,
      });
    },
  };
});

interface RecentState {
  recent: SearchRequest[];
  remember: (request: SearchRequest) => void;
  forget: (index: number) => void;
}

/** Past searches on this device, newest first, the same search kept once. */
export const useRecentSearches = create<RecentState>()(
  persist(
    (set) => ({
      recent: [],
      remember: (request) =>
        set((state) => {
          const kept: SearchRequest = { ...request, fresh: undefined };
          const same = (other: SearchRequest) =>
            JSON.stringify({ ...other, fresh: undefined }) === JSON.stringify(kept);
          return { recent: [kept, ...state.recent.filter((r) => !same(r))].slice(0, RECENT_LIMIT) };
        }),
      forget: (index) => set((state) => ({ recent: state.recent.filter((_, i) => i !== index) })),
    }),
    { name: "dragoncp-prowlarr-recent" }
  )
);
