"""Transcript-driven diagnostics for image-eval failures."""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence
import json
import sqlite3


BUCKET_LABEL_OCR_MISS = "label OCR miss"
BUCKET_MISSED_NODE = "missed node"
BUCKET_EXTRA_NODE = "extra hallucinated node"
BUCKET_WRONG_BRANCH = "wrong branch direction/label"
BUCKET_VARIABLE_MISS = "variable extraction miss"
BUCKET_AMBIGUITY = "ambiguity unresolved"


def _fetch_transcript_snippets(history_db_path: Path, session_id: str) -> Dict[str, str]:
    if not history_db_path.exists() or not session_id:
        return {"user": "", "assistant": ""}

    with sqlite3.connect(history_db_path) as conn:
        rows = conn.execute(
            """
            SELECT role, content
            FROM messages
            WHERE session_id = ?
            ORDER BY id ASC
            """,
            (session_id,),
        ).fetchall()

    user_msg = ""
    assistant_msg = ""
    for role, content in rows:
        if role == "user" and not user_msg:
            user_msg = str(content)
        if role == "assistant":
            assistant_msg = str(content)

    return {
        "user": user_msg[:600],
        "assistant": assistant_msg[:1200],
    }


def classify_failure_buckets(
    metrics: Mapping[str, Any],
    details: Mapping[str, Any],
    doubts: Iterable[str],
) -> List[str]:
    buckets: List[str] = []

    node_f1 = float(metrics.get("node_f1", 0.0))
    edge_f1 = float(metrics.get("edge_f1", 0.0))
    variable_f1 = float(metrics.get("variable_f1", 0.0))

    node_detail = details.get("node", {}) if isinstance(details.get("node"), Mapping) else {}
    edge_detail = details.get("edge", {}) if isinstance(details.get("edge"), Mapping) else {}

    node_mismatch = int(details.get("node_label_mismatch_count", 0))
    edge_direction_mismatch = int(details.get("edge_direction_mismatch_count", 0))
    edge_label_mismatch = int(details.get("edge_label_mismatch_count", 0))

    node_ref = int(node_detail.get("reference_total", 0))
    node_pred = int(node_detail.get("predicted_total", 0))
    node_matched = int(node_detail.get("matched", 0))

    if node_mismatch > 0 and edge_f1 >= 0.6 and node_f1 < 0.95:
        buckets.append(BUCKET_LABEL_OCR_MISS)

    if node_ref > node_matched:
        buckets.append(BUCKET_MISSED_NODE)

    if node_pred > node_matched:
        buckets.append(BUCKET_EXTRA_NODE)

    if edge_f1 < 0.9 or edge_direction_mismatch > 0 or edge_label_mismatch > 0:
        buckets.append(BUCKET_WRONG_BRANCH)

    if variable_f1 < 0.9:
        buckets.append(BUCKET_VARIABLE_MISS)

    if list(doubts):
        buckets.append(BUCKET_AMBIGUITY)

    # Preserve order but remove duplicates.
    ordered_unique = list(dict.fromkeys(buckets))
    return ordered_unique


def emit_diagnostics(
    *,
    run_id: str,
    trials: Sequence[Mapping[str, Any]],
    history_db_path: Path,
    results_dir: Path,
) -> Dict[str, str]:
    failures_path = results_dir / "failures.jsonl"
    report_path = results_dir / "report.md"

    bucket_counter: Counter[str] = Counter()
    case_counter: Dict[str, Counter[str]] = defaultdict(Counter)
    records: List[Dict[str, Any]] = []

    for trial in trials:
        score = trial.get("score", {}) if isinstance(trial.get("score"), Mapping) else {}
        metrics = score.get("metrics", {}) if isinstance(score.get("metrics"), Mapping) else {}
        details = score.get("details", {}) if isinstance(score.get("details"), Mapping) else {}

        analysis = trial.get("analysis", {}) if isinstance(trial.get("analysis"), Mapping) else {}
        doubts = analysis.get("doubts", []) if isinstance(analysis.get("doubts"), list) else []

        buckets = classify_failure_buckets(metrics, details, doubts)
        for bucket in buckets:
            bucket_counter[bucket] += 1
            case_counter[str(trial.get("case_id", "unknown"))][bucket] += 1

        transcript = _fetch_transcript_snippets(history_db_path, str(trial.get("session_id", "")))

        record = {
            "run_id": run_id,
            "case_id": trial.get("case_id"),
            "trial_index": trial.get("trial_index"),
            "session_id": trial.get("session_id"),
            "composite_score": score.get("composite_score"),
            "metrics": score.get("percentage_metrics", {}),
            "buckets": buckets,
            "doubts": doubts,
            "transcript": transcript,
            "semantic_failures": ((details.get("semantic") or {}).get("failures") if isinstance(details, Mapping) else []),
        }
        records.append(record)

    with failures_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=True) + "\n")

    lines: List[str] = []
    lines.append(f"# Image Eval Diagnostics: {run_id}")
    lines.append("")
    lines.append("## Bucket Counts")
    lines.append("")
    if bucket_counter:
        for bucket, count in bucket_counter.most_common():
            lines.append(f"- {bucket}: {count}")
    else:
        lines.append("- No failure buckets were detected.")

    lines.append("")
    lines.append("## Per-Case Bucket Distribution")
    lines.append("")
    for case_id in sorted(case_counter.keys()):
        lines.append(f"### {case_id}")
        for bucket, count in case_counter[case_id].most_common():
            lines.append(f"- {bucket}: {count}")
        if not case_counter[case_id]:
            lines.append("- no categorized failures")
        lines.append("")

    lines.append("## Trial Notes")
    lines.append("")
    for record in records:
        lines.append(
            f"### {record['case_id']} trial {record['trial_index']} - composite {record.get('composite_score', 0)}"
        )
        bucket_text = ", ".join(record["buckets"]) if record["buckets"] else "none"
        lines.append(f"- Buckets: {bucket_text}")
        if record["doubts"]:
            lines.append(f"- Doubts: {'; '.join(record['doubts'][:5])}")
        user_excerpt = record["transcript"].get("user", "")
        assistant_excerpt = record["transcript"].get("assistant", "")
        if user_excerpt:
            lines.append(f"- User prompt excerpt: `{user_excerpt[:180]}`")
        if assistant_excerpt:
            lines.append(f"- Assistant excerpt: `{assistant_excerpt[:240]}`")
        lines.append("")

    report_path.write_text("\n".join(lines), encoding="utf-8")

    return {
        "failures_jsonl": str(failures_path),
        "report_md": str(report_path),
    }
