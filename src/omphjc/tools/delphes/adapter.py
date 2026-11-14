"""Delphes as the detector simulator of a job.

:class:`DelphesSimulator` meets the interface the simulation stage expects
(:class:`omphjc.jobs.stages.simulate.DetectorSimulator`). It is the one module
of the Delphes package that imports the jobs layer.
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from omphjc.data_files import Card
from omphjc.events.delphes_root import DelphesROOTFile
from omphjc.events.formats import EventFile, EventFormat
from omphjc.jobs.task import (
    EVENTS_OUTPUT,
    EventOutput,
    TaskOutcome,
    TaskResult,
    read_cards,
)
from omphjc.processes.catalogue import ProcessSpec
from omphjc.tools.delphes.driver import (
    SimulationWorkspace,
    detector_card_text,
    simulate_events,
)


@dataclass(frozen=True)
class DelphesSimulator:
    """Delphes, run through ``DelphesROOT``, as the detector simulator of a job.

    Parameters
    ----------
    spec : ProcessSpec
        The process. Its catalogue names the detector card to use by default.
        When it names none, the official JetClass card is used.
    detector_card_path : Path or None, optional
        The detector card to use instead of the card of the process.
    timeout_seconds : float or None, optional
        Seconds a run may take. ``None`` sets no limit.
    delphes_root_path : Path or None, optional
        Path of Delphes's ``DelphesROOT``. By default the program is looked
        up on PATH.
    """

    name: ClassVar[str] = "delphes"
    input_formats: ClassVar[frozenset[EventFormat]] = frozenset(
        {EventFormat.DELPHES_ROOT}
    )
    log_name: ClassVar[str] = SimulationWorkspace.log_name
    card_classes: ClassVar[tuple[type[Card], ...]] = SimulationWorkspace.card_classes

    spec: ProcessSpec
    detector_card_path: Path | None = None
    timeout_seconds: float | None = None
    delphes_root_path: Path | None = None

    def parameters(self, *, seed: int) -> dict[str, Any]:
        """Return the seed and the SHA-256 of the chosen detector card.

        Raises
        ------
        FileNotFoundError
            If `detector_card_path` is given and is not a file.
        """
        card_text = detector_card_text(self.spec, self.detector_card_path)
        card_hash = hashlib.sha256(card_text.encode("utf-8")).hexdigest()
        return {"seed": seed, "card": card_hash}

    def simulate(
        self,
        event_file: EventFile,
        *,
        workdir: Path,
        seed: int,
        overwrite: bool,
        log_dir: Path,
    ) -> TaskOutcome:
        """Simulate the detector on the events in `event_file` with Delphes.

        The events of the outcome are the ROOT file Delphes wrote, with the
        number of entries in its tree and the fingerprint of its content
        (:class:`omphjc.events.delphes_root.DelphesROOTFile`). Its one card
        is the detector card as the run used it, with the seed.

        The parameters and the errors are those of
        :func:`omphjc.tools.delphes.driver.simulate_events`.
        """
        run = simulate_events(
            self.spec,
            events_path=event_file.path,
            workdir=workdir,
            seed=seed,
            detector_card_path=self.detector_card_path,
            timeout=self.timeout_seconds,
            overwrite=overwrite,
            log_dir=log_dir,
            delphes_root_path=self.delphes_root_path,
        )
        delphes_file = DelphesROOTFile.read(run.output_path)
        events = EventOutput(
            run.output_path,
            n_bytes=run.output_path.stat().st_size,
            format=EventFormat.DELPHES_ROOT,
            n_events=delphes_file.n_entries,
            fingerprint=delphes_file.fingerprint(),
        )
        return TaskOutcome(
            TaskResult(
                outputs={EVENTS_OUTPUT: events},
                cards=read_cards(run.card_paths),
            ),
            usage=run.usage.as_record(),
            set_aside_dir=run.set_aside,
        )
