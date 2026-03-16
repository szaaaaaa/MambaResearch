from __future__ import annotations

import re
from typing import Iterable

from src.dynamic_os.contracts.artifact import ArtifactRecord
from src.dynamic_os.contracts.route_plan import RoleId


_CAMEL_BOUNDARY = re.compile(r"(?<!^)(?=[A-Z])")


def artifact_type_suffix(artifact_type: str) -> str:
    normalized = str(artifact_type or "").strip()
    if not normalized:
        raise ValueError("artifact_type is required")
    return _CAMEL_BOUNDARY.sub("_", normalized).lower()


def artifact_id_for(*, node_id: str, artifact_type: str) -> str:
    normalized_node_id = str(node_id or "").strip()
    if not normalized_node_id:
        raise ValueError("node_id is required")
    return f"{normalized_node_id}_{artifact_type_suffix(artifact_type)}"


def artifact_ref(artifact_type: str, artifact_id: str) -> str:
    normalized_type = str(artifact_type or "").strip()
    normalized_id = str(artifact_id or "").strip()
    if not normalized_type or not normalized_id:
        raise ValueError("artifact_type and artifact_id are required")
    return f"artifact:{normalized_type}:{normalized_id}"


def artifact_ref_for(*, node_id: str, artifact_type: str) -> str:
    return artifact_ref(artifact_type, artifact_id_for(node_id=node_id, artifact_type=artifact_type))


def parse_artifact_ref(reference: str) -> tuple[str, str]:
    parts = str(reference or "").split(":", 2)
    if len(parts) != 3 or parts[0] != "artifact":
        raise ValueError(f"invalid artifact reference: {reference}")
    artifact_type = str(parts[1] or "").strip()
    artifact_id = str(parts[2] or "").strip()
    if not artifact_type or not artifact_id:
        raise ValueError(f"invalid artifact reference: {reference}")
    return artifact_type, artifact_id


def artifact_ref_for_record(record: ArtifactRecord) -> str:
    return artifact_ref(record.artifact_type, record.artifact_id)


def source_input_refs(records: Iterable[ArtifactRecord]) -> list[str]:
    return [artifact_ref_for_record(record) for record in records]


def predicted_output_refs(*, node_id: str, artifact_types: Iterable[str]) -> list[str]:
    refs: list[str] = []
    for artifact_type in artifact_types:
        ref = artifact_ref_for(node_id=node_id, artifact_type=str(artifact_type or "").strip())
        if ref not in refs:
            refs.append(ref)
    return refs


def make_artifact(
    *,
    node_id: str,
    artifact_type: str,
    producer_role: RoleId,
    producer_skill: str,
    payload: dict,
    source_inputs: list[str] | None = None,
) -> ArtifactRecord:
    return ArtifactRecord(
        artifact_id=artifact_id_for(node_id=node_id, artifact_type=artifact_type),
        artifact_type=artifact_type,
        producer_role=producer_role,
        producer_skill=producer_skill,
        payload=payload,
        source_inputs=list(source_inputs or []),
    )
