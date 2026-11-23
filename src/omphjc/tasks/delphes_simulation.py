"""The detector simulation of the showered events, with Delphes's ``DelphesROOT``."""

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from omphjc.events.formats import EventFileRecord, EventFormat
from omphjc.jobs.task import EVENTS_INPUT, TASK_REGISTRY, Task, TaskInput, TaskOutcome
from omphjc.runs import EVENTS_OUTPUT, RunResult
from omphjc.stages import ShowerStage, SimulateStage, Stage
from omphjc.tools.delphes.driver import detector_card_text, simulate_events


@TASK_REGISTRY.register
@dataclass(frozen=True, kw_only=True)
class DelphesSimulation(Task):
    """The task that simulates the detector on the showered events with Delphes.

    It runs :func:`omphjc.tools.delphes.driver.simulate_events` in its
    directory, ``simulate-delphes/``, on the event file that the task of the
    shower stage made, with the seed of the job.

    Its parameters are the seed, the SHA-256 of the detector card and the
    fingerprint of the event file it reads. A shower that is repeated with
    the same events therefore keeps its simulation.

    Its events are the ROOT file Delphes wrote, recorded with the number of
    entries in its tree and the fingerprint of its content
    (:class:`omphjc.events.delphes_root.DelphesROOTFile`). Its one card is the
    detector card as the run used it, with the seed.

    Parameters
    ----------
    detector_card_path : Path or None, optional
        The detector card to use instead of the card of the process. The
        catalogue of a process names its card; when it names none, the
        official JetClass card is used.

    The other settings are those of :class:`~omphjc.jobs.task.Task`.
    `program_path` is Delphes's ``DelphesROOT``.
    """

    stage: ClassVar[Stage] = SimulateStage()
    tool: ClassVar[str] = "delphes"
    inputs: ClassVar[tuple[TaskInput, ...]] = (
        TaskInput(EVENTS_INPUT, frozenset({EventFormat.DELPHES_ROOT}), ShowerStage()),
    )

    detector_card_path: Path | None = None

    def parameters(self, input_events: Mapping[str, EventFileRecord]) -> dict[str, Any]:
        """Return the seed of the job and the SHA-256 of the chosen detector card.

        Raises
        ------
        FileNotFoundError
            If `detector_card_path` is given and is not a file.
        """
        card_text = detector_card_text(self.job.spec, self.detector_card_path)
        card_hash = hashlib.sha256(card_text.encode("utf-8")).hexdigest()
        return {"seed": self.job.seed, "card": card_hash}

    def execute(
        self,
        input_events: Mapping[str, EventFileRecord],
        overwrite: bool,
        log_path: Path,
    ) -> TaskOutcome:
        """Simulate the detector on the showered events with ``DelphesROOT``.

        The errors are those of
        :func:`omphjc.tools.delphes.driver.simulate_events`.
        """
        # omphjc.events.delphes_root loads the array libraries, so it is
        # imported here and not when a command starts.
        from omphjc.events.delphes_root import DelphesROOTFile

        events = input_events[EVENTS_INPUT]
        run = simulate_events(
            self.job.spec,
            events_path=events.path,
            workdir=self.directory,
            seed=self.job.seed,
            detector_card_path=self.detector_card_path,
            timeout=self.timeout_seconds,
            overwrite=overwrite,
            log_path=log_path,
            delphes_root_path=self.program_path,
        )
        return TaskOutcome(
            RunResult(
                outputs={EVENTS_OUTPUT: DelphesROOTFile.record_file(run.output_path)},
                cards=dict(run.cards),
            ),
            usage=run.usage.as_record(),
            set_aside_dir=run.set_aside,
        )
