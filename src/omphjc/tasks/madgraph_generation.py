"""The generation of parton-level events with MadGraph."""

import shutil
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, ClassVar

from omphjc.data_files import FileRecord
from omphjc.events.formats import EventFileRecord
from omphjc.jobs.task import TASK_REGISTRY, Task, TaskOutcome
from omphjc.runs import EVENTS_OUTPUT, RunResult
from omphjc.stages import GenerateStage, Stage
from omphjc.tools.madgraph.driver import generate_events
from omphjc.tools.madgraph.lhe_file import LHEFile


@TASK_REGISTRY.register
@dataclass(frozen=True, kw_only=True)
class MadGraphGeneration(Task):
    """The task that generates the parton-level events of a job with MadGraph.

    It runs :func:`omphjc.tools.madgraph.driver.generate_events` in its
    directory, ``generate-madgraph/``, and then copies the cards MadGraph ran
    with into ``cards/`` there.

    Its parameters are the event count and the seed of the job. A changed
    seed is therefore refused like any other change unless the task is forced.

    Its events are the LHE file, recorded with the event count in its banner
    and the fingerprint of its content
    (:class:`omphjc.tools.madgraph.lhe_file.LHEFile`).

    Its cards are the copies in ``cards/``: the process card, the run card,
    the parameter card and, with MadSpin, the MadSpin card.

    Its metadata holds:

    - the MadGraph version;
    - the cross section and its error, in pb;
    - the number of cores MadGraph ran on.

    Parameters
    ----------
    n_events : int
        Events to generate.
    n_cores : int or None, optional
        Cores MadGraph may use; ``None`` for every usable CPU. A sample with
        MadSpin is reproduced only on the same number of cores.

    The other settings are those of :class:`~omphjc.jobs.task.Task`.
    `program_path` is MadGraph's ``bin/mg5_aMC``.
    """

    stage: ClassVar[Stage] = GenerateStage()
    tool: ClassVar[str] = "madgraph"

    card_copies_dir_name: ClassVar[str] = "cards"

    n_events: int
    n_cores: int | None = None

    def parameters(self, input_events: Mapping[str, EventFileRecord]) -> dict[str, Any]:
        """Return the event count and the seed of the job."""
        return {"events": self.n_events, "seed": self.job.seed}

    def execute(
        self,
        input_events: Mapping[str, EventFileRecord],
        overwrite: bool,
        log_path: Path,
    ) -> TaskOutcome:
        """Generate the events with MadGraph and copy the cards it ran with.

        The errors are those of
        :func:`omphjc.tools.madgraph.driver.generate_events`.
        """
        run = generate_events(
            self.job.spec,
            workdir=self.directory,
            n_events=self.n_events,
            seed=self.job.seed,
            n_cores=self.n_cores,
            timeout=self.timeout_seconds,
            overwrite=overwrite,
            log_path=log_path,
            mg5_path=self.program_path,
        )
        return TaskOutcome(
            RunResult(
                outputs={EVENTS_OUTPUT: LHEFile.record_file(run.output_path)},
                cards=self._copy_cards(run.cards),
                metadata={
                    "madgraph_version": run.banner.version,
                    "cross_section_pb": run.banner.cross_section_pb,
                    "cross_section_error_pb": run.banner.cross_section_error_pb,
                    "n_cores": run.n_cores,
                },
            ),
            usage=run.usage.as_record(),
            set_aside_dir=run.set_aside,
        )

    def _copy_cards(self, cards: Mapping[str, FileRecord]) -> dict[str, FileRecord]:
        """Copy the file of each card of `cards` into the directory of the copies.

        The record of each copy is returned under the name of the card. A
        copy has the size and the content of its card, so its record differs
        only in its path.
        """
        copies_dir = self.directory / self.card_copies_dir_name
        copies_dir.mkdir(parents=True, exist_ok=True)
        copies = {}
        for name, card in cards.items():
            copy_path = copies_dir / card.path.name
            shutil.copyfile(card.path, copy_path)
            copies[name] = replace(card, path=copy_path)
        return copies
