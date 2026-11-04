"""The external programs the stages run, one package per program.

Each package knows only its own program. Its ``__init__`` imports nothing, so
importing one module of a tool loads only what that module imports; import
every name from the module that defines it.
"""
