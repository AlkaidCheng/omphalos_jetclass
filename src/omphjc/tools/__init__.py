"""The external programs the stages run, one package per program.

Each package knows only its own program. Its ``__init__`` imports nothing, so
importing one module of a tool loads only what that module imports. Import
every name from the module that defines it.

A package may hold an ``adapter`` module, which offers the tool to a stage of
a job. It is the one module of the package that imports :mod:`omphjc.jobs`.
"""
