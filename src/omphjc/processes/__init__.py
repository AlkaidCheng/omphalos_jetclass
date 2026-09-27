"""The JetClass process catalogue and the packaged reference resources."""

from omphjc.processes.catalogue import (
    ProcessSpec,
    RunCardValue,
    catalogue,
    get_process,
    load_catalogue,
    process_names,
)
from omphjc.processes.resources_access import (
    VENDORED_MODELS,
    delphes_card_path,
    models_dir,
    reference_dir,
    resource_root,
)

__all__ = [
    "VENDORED_MODELS",
    "ProcessSpec",
    "RunCardValue",
    "catalogue",
    "delphes_card_path",
    "get_process",
    "load_catalogue",
    "models_dir",
    "process_names",
    "reference_dir",
    "resource_root",
]
