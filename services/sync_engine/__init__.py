"""
The sync engine — one pipeline every sync goes through.

See `stages.py` for the nine stages and what each kind of sync does at each,
and `engine.py` for the engine itself. Kept import-free on purpose: the
storage layer imports the stage catalogue, and the engine imports the storage
layer, so this package must not import the engine when it is first touched.
"""
