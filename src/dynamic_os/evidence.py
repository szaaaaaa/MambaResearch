"""Deduplicate complete source bodies for models; stored artifacts stay untouched."""
import hashlib


def evidence_payloads(artifacts):
    documents = {}
    result = []
    for artifact in artifacts:
        if artifact.artifact_type != "SourceSet":
            result.append({"id": artifact.artifact_id, "type": artifact.artifact_type, "payload": artifact.payload})
            continue
        payload = artifact.payload
        candidates = [*payload.get("documents", []), *payload.get("sources", [])]
        for source in candidates:
            if not isinstance(source, dict):
                continue
            retrieved = source.get("retrieved_document")
            for item in [source, retrieved] if isinstance(retrieved, dict) else [source]:
                content = str(item.get("content") or item.get("text") or "").strip()
                if not content and not retrieved:
                    content = str(item.get("abstract") or "").strip()
                if not content:
                    continue
                key = hashlib.sha256(content.encode("utf-8")).hexdigest()
                document = documents.setdefault(key, {"content": content, "sources": []})
                origin = {k: v for k, v in item.items() if k not in {"content", "text", "retrieved_document"}
                          and not (k == "abstract" and str(v or "").strip() in content)}
                origin["artifact_id"] = artifact.artifact_id
                if origin not in document["sources"]:
                    document["sources"].append(origin)
    if documents:
        result.append({"type": "SourceSet", "payload": {"documents": list(documents.values())}})
    return result
