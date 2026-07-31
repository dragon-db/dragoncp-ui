"""
DragonCP Explore

Compares the remote library against the local one and turns the difference into
a plan you can review before anything is written to disk.

The module is deliberately self-contained and free of Flask, SSH and rsync
specifics at its core, so the comparison and planning logic can be tested
without a server:

    identity.py   filename -> episode identity (the anchor everything hangs off)
    inventory.py  both sides of the library as a flat list of files
    compare.py    line the two up and label every episode
    planner.py    turn a comparison into an operation plan + safety verdict
    executor.py   carry a plan out: back up what is superseded, fetch the rest
    store.py      persistence for snapshots, plans and per-file outcomes
    service.py    the facade the routes talk to

See docs/plans/explore-rebuild.md for the reasoning behind the design.
"""
