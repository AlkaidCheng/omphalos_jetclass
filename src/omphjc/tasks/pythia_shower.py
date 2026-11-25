"""The shower of the generated events with Pythia 8, through ``DelphesPythia8``."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

from omphjc.data_files import FileRecord
from omphjc.events.formats import EventFileRecord
from omphjc.jobs.task import EVENTS_INPUT, TASK_REGISTRY, TaskOutcome
from omphjc.processes.catalogue import SettingValue
from omphjc.runs import EVENTS_OUTPUT, RunResult
from omphjc.tasks.families import ShowerTask
from omphjc.tools.pythia.driver import shower_events


@TASK_REGISTRY.register
@dataclass(frozen=True, kw_only=True)
class PythiaShower(ShowerTask):
    """The task that showers the generated events of a job with Pythia 8.

    It runs :func:`omphjc.tools.pythia.driver.shower_events` in its
    directory, ``shower-pythia/``. It reads the LHE file of the generation
    of its job (:class:`~omphjc.tasks.families.ShowerTask`), and uses the seed
    of the job and the event count that file holds.

    Its parameters are the event count, the seed and the Pythia overrides.
    Its record also holds the fingerprint of the event file it reads, so a
    sample that is generated again with the same events keeps its shower.

    Its events are the ROOT file, recorded with the number of events Pythia
    accepted and the fingerprint of its content
    (:class:`omphjc.events.delphes_root.DelphesROOTFile`).

    Its cards are the Pythia command file and the Delphes card that writes
    the generator record, both as the run used them.

    Its metadata holds:

    - the Pythia version;
    - the number of events read;
    - the fraction of events kept by matching, for a matched process.

    Parameters
    ----------
    overrides : Mapping[str, SettingValue], optional
        Pythia settings applied over those of the catalogue.

    The other settings are those of :class:`~omphjc.jobs.task.Task`.
    `program_path` is Delphes's ``DelphesPythia8``.
    """

    tool: ClassVar[str] = "pythia"

    overrides: Mapping[str, SettingValue] = field(default_factory=dict)

    def parameters(self, input_files: Mapping[str, FileRecord]) -> dict[str, Any]:
        """Return the event count of the input, the job's seed and the overrides."""
        events = self._input_events(input_files)
        return {
            "n_events": events.n_events,
            "seed": self.job.seed,
            "overrides": dict(self.overrides),
        }

    def execute(
        self,
        input_files: Mapping[str, FileRecord],
        overwrite: bool,
        log_path: Path,
    ) -> TaskOutcome:
        """Shower the generated events with ``DelphesPythia8``.

        The errors are those of
        :func:`omphjc.tools.pythia.driver.shower_events`.
        """
        # omphjc.events.delphes_root loads the array libraries, so it is
        # imported here and not when a command starts.
        from omphjc.events.delphes_root import DelphesROOTFile

        events = self._input_events(input_files)
        run = shower_events(
            self.job.spec,
            lhe_path=events.path,
            workdir=self.directory,
            n_events=events.n_events,
            seed=self.job.seed,
            overrides=dict(self.overrides),
            timeout=self.timeout_seconds,
            overwrite=overwrite,
            log_path=log_path,
            delphes_pythia8_path=self.program_path,
        )
        statistics = run.statistics
        metadata = {
            "pythia_version": statistics.pythia_version,
            "events_read": statistics.events_read,
        }
        if self.job.spec.matching and statistics.events_read > 0:
            metadata["matching_efficiency"] = (
                statistics.events_accepted / statistics.events_read
            )
        return TaskOutcome(
            RunResult(
                outputs={EVENTS_OUTPUT: DelphesROOTFile.record_file(run.output_path)},
                cards=dict(run.cards),
                metadata=metadata,
            ),
            usage=run.usage.as_record(),
            set_aside_dir=run.set_aside,
        )

    def _input_events(self, input_files: Mapping[str, FileRecord]) -> EventFileRecord:
        """Return the record of the events that the shower reads, with their count.

        Raises
        ------
        ValueError
            If the record of the file holds no event count.
        """
        events = input_files[EVENTS_INPUT]
        if not isinstance(events, EventFileRecord):
            raise ValueError(
                f"{self.name} reads the number of events in {events.path} from "
                "its record, but the record holds none. Run the task that made "
                "the file again."
            )
        return events
