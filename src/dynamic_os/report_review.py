"""Bind final-report acceptance to the exact artifact being delivered."""
import hashlib
import json


def payload_digest(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def matching_review(artifacts, target):
    digest = payload_digest(target.payload)
    matches = [a for a in artifacts if a.artifact_type == "ReviewVerdict"
               and a.payload.get("target_artifact_id") == target.artifact_id
               and a.payload.get("target_payload_sha256") == digest]
    return max(reversed(matches), key=lambda a: a.created_at) if matches else None


def latest_report(artifacts):
    reports = [a for a in artifacts if a.artifact_type == "ResearchReport"]
    return max(reversed(reports), key=lambda a: a.created_at) if reports else None


def report_stop_reason(artifacts):
    report = latest_report(artifacts)
    if report is None:
        return None
    if not str(report.payload.get("report") or "").strip():
        return "report_empty"
    review = matching_review(artifacts, report)
    if review is None:
        return "report_review_missing"
    payload = review.payload
    if (payload.get("verdict") != "accept" or payload.get("task_completed") is not True
            or payload.get("claims_supported") is not True):
        return "report_review_not_accepted"
    return None
