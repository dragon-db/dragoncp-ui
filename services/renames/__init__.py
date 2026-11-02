"""
Renames from DragonCP (TASK-028).

Episodes Sonarr named while their title was still unknown carry a placeholder
in the title slot, `Example Show - S01E05 - TBA [WEBDL-1080p][GRP].mkv`. This
package finds them, works out the real title, and renames the file here, and
asks Sonarr to rename its own copy when it still holds one.

    naming.py   the file name rules: where the title sits, how Sonarr cleans one
    tmdb.py     episode titles from TMDB, for what Sonarr has no title for
    store.py    title checks, TMDB links, titles taken from TMDB
    service.py  the plan, the rename, Undo, the title check

See docs/features/renames/README.md for how it behaves.
"""
