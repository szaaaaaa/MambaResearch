from __future__ import annotations

from typing import Protocol

from src.dynamic_os.contracts.artifact import ArtifactRecord
from src.dynamic_os.contracts.observation import Observation
from src.dynamic_os.contracts.route_plan import RoutePlan


class ArtifactStore(Protocol):
    def save(self, record: ArtifactRecord) -> None: ...

    def get(self, artifact_id: str) -> ArtifactRecord | None: ...

    def list_by_type(self, artifact_type: str) -> list[ArtifactRecord]: ...

    def list_all(self) -> list[ArtifactRecord]: ...

    def summary(self) -> list[dict[str, str]]: ...


class ObservationStore(Protocol):
    def save(self, obs: Observation) -> None: ...

    def list_latest(self, n: int = 5) -> list[Observation]: ...

    def list_by_node(self, node_id: str) -> list[Observation]: ...


class PlanStore(Protocol):
    def save(self, plan: RoutePlan) -> None: ...

    def get_latest(self) -> RoutePlan | None: ...

    def list_all(self) -> list[RoutePlan]: ...


class InMemoryArtifactStore:
    def __init__(self) -> None:
        self._records: dict[str, ArtifactRecord] = {}

    def save(self, record: ArtifactRecord) -> None:
        self._records[record.artifact_id] = record

    def get(self, artifact_id: str) -> ArtifactRecord | None:
        return self._records.get(artifact_id)

    def list_by_type(self, artifact_type: str) -> list[ArtifactRecord]:
        return [record for record in self._records.values() if record.artifact_type == artifact_type]

    def list_all(self) -> list[ArtifactRecord]:
        return list(self._records.values())

    def summary(self) -> list[dict[str, str]]:
        return [
            {
                "artifact_id": record.artifact_id,
                "artifact_type": record.artifact_type,
                "artifact_ref": f"artifact:{record.artifact_type}:{record.artifact_id}",
                "producer_role": record.producer_role.value,
            }
            for record in self._records.values()
        ]


class InMemoryObservationStore:
    def __init__(self) -> None:
        self._observations: list[Observation] = []

    def save(self, obs: Observation) -> None:
        self._observations.append(obs)

    def list_latest(self, n: int = 5) -> list[Observation]:
        return self._observations[-n:]

    def list_by_node(self, node_id: str) -> list[Observation]:
        return [obs for obs in self._observations if obs.node_id == node_id]


class InMemoryPlanStore:
    def __init__(self) -> None:
        self._plans: list[RoutePlan] = []

    def save(self, plan: RoutePlan) -> None:
        self._plans.append(plan)

    def get_latest(self) -> RoutePlan | None:
        if not self._plans:
            return None
        return self._plans[-1]

    def list_all(self) -> list[RoutePlan]:
        return list(self._plans)
