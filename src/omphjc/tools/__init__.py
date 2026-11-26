"""The tools that the tasks of a job use, one package per tool.

Each package knows only its own tool. Its ``__init__`` imports nothing, so
importing one module of a tool loads only what that module imports. Import
every name from the module that defines it.

No module of a tool imports the jobs or the task classes
(:mod:`omphjc.jobs`, :mod:`omphjc.tasks`): a task class calls the driver of
its tool.
"""
