"""Test case generation and labeling."""

from __future__ import annotations

import json
import os
import random
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from PIL import Image
from tqdm import tqdm

from ..core.workflow import StandardizedInput
from ..utils.logging import get_logger
from .strategies import (
    ComprehensiveStrategy,
    EdgeCasesStrategy,
    RandomStrategy,
    TestGenerationStrategy,
)

logger = get_logger(__name__)


@dataclass(frozen=True)
class TestCase:
    inputs: Dict[str, Any]
    expected_output: str | None = None


class TestCaseGenerator:
    """Generate and label test cases from `workflow_inputs.json`."""

    def __init__(self, inputs_file: str = "workflow_inputs.json"):
        self.inputs_file = Path(inputs_file)
        self.inputs = self._load_inputs()

    def _load_inputs(self) -> List[StandardizedInput]:
        if not self.inputs_file.exists():
            raise FileNotFoundError(f"Inputs file not found: {self.inputs_file}")
        with open(self.inputs_file, "r") as f:
            raw = json.load(f)
        return [StandardizedInput.model_validate(x) for x in raw]

    def generate_test_cases(
        self, n: int, strategy: str = "comprehensive", seed: int | None = None
    ) -> List[Dict[str, Any]]:
        """Generate N input dictionaries according to strategy."""
        value_specs = [
            {"name": inp.input_name, "values": self._generate_values_for_input(inp)}
            for inp in self.inputs
        ]

        strat: TestGenerationStrategy
        if strategy == "comprehensive":
            strat = ComprehensiveStrategy(seed=seed)
        elif strategy == "random":
            strat = RandomStrategy(seed=seed)
        elif strategy == "edge_cases":
            strat = EdgeCasesStrategy(seed=seed)
        else:
            raise ValueError(f"Unknown strategy: {strategy}")

        return strat.generate(value_specs, n)

    def save_test_cases(
        self, test_cases: List[Dict[str, Any]], output_file: str = "test_cases.json"
    ) -> None:
        output_path = Path(output_file)
        with open(output_path, "w") as f:
            json.dump(test_cases, f, indent=2)
        logger.info("Saved test cases", extra={"count": len(test_cases), "path": str(output_path)})

    def label_test_cases(
        self,
        *,
        test_cases: List[Dict[str, Any]],
        workflow_image_path: str,
        valid_outputs: List[str],
        workflow_analysis: Optional[Dict[str, Any]] = None,
        model: str | None = None,
        batch_size: int = 20,
        max_workers: int = 5,
        log_responses: bool = False,
        max_retries: int = 3,
        backoff_base: float = 1.0,
        backoff_cap: float = 8.0,
        best_of_n: int = 1,
    ) -> List[Dict[str, Any]]:
        """Label test cases with expected outputs using Azure OpenAI (image + prompt).

        Args:
            test_cases: Unlabeled test cases to label
            workflow_image_path: Path to workflow diagram image
            valid_outputs: List of valid output strings to choose from
            workflow_analysis: Optional structured workflow analysis for context
            model: Model name (defaults to HAIKU_DEPLOYMENT_NAME or DEPLOYMENT_NAME)
            batch_size: Number of test cases per API call
            max_workers: Maximum parallel API calls (default: 5)
            log_responses: If True, logs a preview of raw model responses per batch
            max_retries: Number of retry attempts on API failure (default: 3)
            backoff_base: Initial backoff seconds for exponential backoff (default: 1.0)
            backoff_cap: Maximum backoff seconds (default: 8.0)
            best_of_n: Number of independent labeling passes to run, then take majority vote (default: 1)
        """
        if best_of_n <= 1:
            # Single pass (original behavior)
            return self._label_test_cases_single_pass(
                test_cases=test_cases,
                workflow_image_path=workflow_image_path,
                valid_outputs=valid_outputs,
                workflow_analysis=workflow_analysis,
                model=model,
                batch_size=batch_size,
                max_workers=max_workers,
                log_responses=log_responses,
                max_retries=max_retries,
                backoff_base=backoff_base,
                backoff_cap=backoff_cap,
                shuffle_seed=None,
            )

        # Best-of-N: Run multiple passes with different shuffle seeds, then majority vote
        logger.info(
            f"🎯 Running 'best of {best_of_n}' labeling: {best_of_n} independent passes with majority voting"
        )

        all_results: List[List[Dict[str, Any]]] = []

        for pass_num in range(1, best_of_n + 1):
            logger.info(f"\n{'='*60}")
            logger.info(f"🔄 Labeling Pass {pass_num}/{best_of_n}")
            logger.info(f"{'='*60}")

            # Use different shuffle seed for each pass to ensure different batches
            shuffle_seed = pass_num * 42  # Deterministic but different per pass

            pass_results = self._label_test_cases_single_pass(
                test_cases=test_cases,
                workflow_image_path=workflow_image_path,
                valid_outputs=valid_outputs,
                workflow_analysis=workflow_analysis,
                model=model,
                batch_size=batch_size,
                max_workers=max_workers,
                log_responses=log_responses and pass_num == 1,  # Only log responses on first pass
                max_retries=max_retries,
                backoff_base=backoff_base,
                backoff_cap=backoff_cap,
                shuffle_seed=shuffle_seed,
            )
            all_results.append(pass_results)

        # Aggregate results using majority voting
        logger.info(f"\n{'='*60}")
        logger.info("📊 Aggregating results with majority voting...")
        logger.info(f"{'='*60}")

        aggregated, stats = self._aggregate_majority_vote(test_cases, all_results)

        logger.info(f"\n{'='*60}")
        logger.info("📈 Agreement Statistics:")
        logger.info(
            f"  Perfect agreement (3/3): {stats['perfect_3_3']} ({stats['perfect_3_3_pct']:.1f}%)"
        )
        logger.info(
            f"  Majority agreement (2/3): {stats['majority_2_3']} ({stats['majority_2_3_pct']:.1f}%)"
        )
        logger.info(
            f"  No consensus (1/3 or 0/3): {stats['no_consensus']} ({stats['no_consensus_pct']:.1f}%)"
        )
        logger.info(f"  Total: {stats['total']}")
        logger.info(f"{'='*60}")
        
        # Summary for quick reference
        labeled_count = len([tc for tc in aggregated if tc.get("expected_output") is not None])
        pct_labeled = (labeled_count / stats['total'] * 100) if stats['total'] > 0 else 0.0
        logger.info(
            f"✓ Final result: {labeled_count}/{stats['total']} test cases labeled ({pct_labeled:.1f}%)"
        )

        return aggregated

    def _label_test_cases_single_pass(
        self,
        *,
        test_cases: List[Dict[str, Any]],
        workflow_image_path: str,
        valid_outputs: List[str],
        workflow_analysis: Optional[Dict[str, Any]] = None,
        model: str | None = None,
        batch_size: int = 20,
        max_workers: int = 5,
        log_responses: bool = False,
        max_retries: int = 3,
        backoff_base: float = 1.0,
        backoff_cap: float = 8.0,
        shuffle_seed: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Single-pass labeling (internal method)."""
        from src.utils.request_utils import make_image_request  # legacy module

        if model is None:
            model = os.getenv("HAIKU_DEPLOYMENT_NAME") or os.getenv("DEPLOYMENT_NAME", "haiku")

        logger.info(
            "🏷️ Starting test case labeling",
            extra={
                "count": len(test_cases),
                "model": model,
                "batch_size": batch_size,
                "max_workers": max_workers,
                "total_batches": (len(test_cases) + batch_size - 1) // batch_size,
                "log_responses": log_responses,
            },
        )

        if workflow_analysis:
            logger.info("✓ Using structured workflow analysis for context")

        # Allow loading truncated images (common with JPEG compression)
        from PIL import ImageFile

        ImageFile.LOAD_TRUNCATED_IMAGES = True

        # Load and convert image to base64 once (thread-safe)
        img = Image.open(workflow_image_path)
        img_format = (img.format or "PNG").upper()
        format_map = {"JPEG": "PNG", "JPG": "PNG", "PNG": "PNG", "WEBP": "PNG", "GIF": "PNG"}
        format_str = format_map.get(img_format, "PNG")

        # Convert to base64 for thread-safe sharing
        from ..utils.image_utils import image_to_base64

        img_base64 = image_to_base64(img, format=format_str)
        img.close()  # Close original image

        # Shuffle test cases if seed provided (for best-of-N to ensure different batches)
        test_cases_to_label = test_cases.copy()
        if shuffle_seed is not None:
            random.seed(shuffle_seed)
            random.shuffle(test_cases_to_label)
            logger.debug(f"Shuffled test cases with seed {shuffle_seed}")

        # Create batches
        batches = []
        for batch_idx in range(0, len(test_cases_to_label), batch_size):
            batch = test_cases_to_label[batch_idx : batch_idx + batch_size]
            batch_num = (batch_idx // batch_size) + 1
            batches.append((batch_num, batch))

        total_batches = len(batches)
        logger.info(f"📦 Created {total_batches} batches of up to {batch_size} test cases each")

        # Pre-allocate with empty dicts (will be replaced)
        labeled: List[Dict[str, Any] | None] = [None] * len(test_cases)

        # Track successes and failures
        successful_batches = 0
        failed_batches = 0

        def label_batch(
            batch_num: int, batch: List[Dict[str, Any]], *, log_responses_local: bool
        ) -> tuple[int, List[Dict[str, Any]]]:
            """Label a single batch and return (batch_num, labeled_batch)."""
            import random
            import time

            logger.debug(
                f"🔄 Processing batch {batch_num}/{total_batches} ({len(batch)} test cases)"
            )
            prompt = self._create_labeling_prompt(batch, valid_outputs, workflow_analysis)

            max_retries_local = max_retries
            backoff_base_local = backoff_base
            backoff_cap_local = backoff_cap

            for attempt in range(max_retries_local + 1):
                try:
                    # Recreate image from base64 for this thread
                    import base64
                    from io import BytesIO

                    img_bytes = base64.b64decode(img_base64)
                    img_thread = Image.open(BytesIO(img_bytes))

                    response = make_image_request(
                        image=img_thread,
                        prompt=prompt,
                        max_tokens=64000,
                        model=model,
                        image_format=format_str,
                    )
                    img_thread.close()  # Clean up

                    response_text = response.content[0].text if response.content else ""

                    # Check for empty response
                    if not response_text or not response_text.strip():
                        if attempt < max_retries_local:
                            logger.warning(
                                f"⚠️ Batch {batch_num}/{total_batches} returned empty response (attempt {attempt + 1}/{max_retries_local + 1}). Retrying...",
                                extra={"batch_num": batch_num, "attempt": attempt + 1},
                            )
                            # Retry with backoff
                            sleep_s = min(
                                backoff_base_local * (2**attempt) + random.uniform(0, 1),
                                backoff_cap_local,
                            )
                            time.sleep(sleep_s)
                            continue
                        else:
                            logger.error(
                                f"⚠️ Batch {batch_num}/{total_batches} returned empty response after {max_retries_local + 1} attempts.\n"
                                f"Response type: {type(response)}\n"
                                f"Response.content: {response.content}\n"
                                f"Response object: {response}\n"
                                f"Has usage? {hasattr(response, 'usage')}\n"
                                f"Usage: {getattr(response, 'usage', None)}"
                            )
                            labeled_batch = []
                            for tc in batch:
                                out = tc.copy()
                                out["expected_output"] = None
                                labeled_batch.append(out)
                            return batch_num, labeled_batch

                    if log_responses_local:
                        preview = (response_text or "")[:800]
                        logger.info(
                            f"\n{'='*80}\n📝 Batch {batch_num} Model Response:\n{preview}\n{'='*80}"
                        )
                    logger.debug(f"✓ Batch {batch_num}/{total_batches} labeled successfully")
                    return batch_num, self._parse_labeling_response(
                        batch, response_text, valid_outputs
                    )

                except Exception as e:
                    if attempt >= max_retries_local:
                        logger.error(
                            f"⚠️ Error labeling batch {batch_num}/{total_batches} after {max_retries_local + 1} attempts: {str(e)}",
                            extra={
                                "batch_num": batch_num,
                                "error": str(e),
                                "attempts": max_retries_local + 1,
                            },
                        )
                        labeled_batch = []
                        for tc in batch:
                            out = tc.copy()
                            out["expected_output"] = None
                            labeled_batch.append(out)
                        return batch_num, labeled_batch
                    else:
                        # Exponential backoff with jitter
                        sleep_s = min(
                            backoff_base_local * (2**attempt) + random.uniform(0, 1),
                            backoff_cap_local,
                        )
                        logger.info(
                            f"⚠️ Error labeling batch {batch_num}/{total_batches} (attempt {attempt + 1}/{max_retries_local + 1}): {str(e)}. Retrying after {sleep_s:.2f}s...",
                            extra={
                                "batch_num": batch_num,
                                "attempt": attempt + 1,
                                "sleep_s": round(sleep_s, 2),
                            },
                        )
                        time.sleep(sleep_s)

            # Fallback: should never reach here, but satisfy type checker
            labeled_batch = []
            for tc in batch:
                out = tc.copy()
                out["expected_output"] = None
                labeled_batch.append(out)
            return batch_num, labeled_batch

        # Process batches in parallel
        logger.info(f"🚀 Starting parallel labeling with {max_workers} workers...")
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {}
            for batch_num, batch in batches:
                fut = executor.submit(
                    label_batch, batch_num, batch, log_responses_local=log_responses
                )
                futures[fut] = (batch_num, batch)

            with tqdm(total=total_batches, desc="Labeling batches", unit="batch", file=sys.stderr) as pbar:
                for future in as_completed(futures):
                    batch_num, batch = futures[future]
                    try:
                        result_batch_num, labeled_batch = future.result()
                        # Find the original indices for this batch
                        batch_idx = (batch_num - 1) * batch_size
                        for i, labeled_tc in enumerate(labeled_batch):
                            if batch_idx + i < len(labeled):
                                labeled[batch_idx + i] = labeled_tc

                        # Check if labeling was successful (has expected_output)
                        if labeled_batch and labeled_batch[0].get("expected_output") is not None:
                            successful_batches += 1
                        else:
                            failed_batches += 1

                    except Exception as e:
                        failed_batches += 1
                        # Use tqdm.write() to avoid interfering with progress bar
                        pbar.write(
                            f"❌ Unexpected error processing batch {batch_num}: {str(e)}",
                        )
                    pbar.update(1)

        logger.info(
            f"✓ Labeling complete: {successful_batches} successful, {failed_batches} failed batches",
            extra={
                "successful": successful_batches,
                "failed": failed_batches,
                "total": total_batches,
            },
        )

        # Filter out None entries (shouldn't happen, but safety check)
        result: List[Dict[str, Any]] = [tc for tc in labeled if tc is not None]
        labeled_count = len([tc for tc in result if tc.get("expected_output") is not None])
        unlabeled_count = len(result) - labeled_count

        # Map back to original order if we shuffled
        if shuffle_seed is not None:
            # Create mapping from normalized test case to result
            result_map = {}
            for tc in result:
                key = tuple(sorted((k, v) for k, v in tc.items() if k != "expected_output"))
                result_map[key] = tc

            # Reconstruct in original order
            ordered_result = []
            for original_tc in test_cases:
                key = tuple(
                    sorted((k, v) for k, v in original_tc.items() if k != "expected_output")
                )
                ordered_result.append(result_map.get(key, original_tc.copy()))
            result = ordered_result

        if len(result) != len(test_cases):
            logger.warning(
                "⚠️ Some test cases were not labeled",
                extra={
                    "expected": len(test_cases),
                    "actual": len(result),
                    "missing": len(test_cases) - len(result),
                },
            )

        logger.info(
            f"📊 Labeling summary: {labeled_count} labeled, {unlabeled_count} unlabeled, {len(result)} total",
            extra={"labeled": labeled_count, "unlabeled": unlabeled_count, "total": len(result)},
        )

        return result

    def _aggregate_majority_vote(
        self, original_test_cases: List[Dict[str, Any]], all_results: List[List[Dict[str, Any]]]
    ) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Aggregate multiple labeling passes using majority voting.

        Args:
            original_test_cases: Original test cases in order
            all_results: List of labeling results from each pass

        Returns:
            Tuple of (aggregated_results, statistics_dict)
        """
        from collections import Counter

        # Create mapping from test case to all labels
        test_case_key_to_labels: Dict[tuple, List[str | None]] = {}

        for result_list in all_results:
            for labeled_tc in result_list:
                key = tuple(sorted((k, v) for k, v in labeled_tc.items() if k != "expected_output"))
                label = labeled_tc.get("expected_output")
                if key not in test_case_key_to_labels:
                    test_case_key_to_labels[key] = []
                test_case_key_to_labels[key].append(label)

        # Aggregate with majority voting
        aggregated = []
        stats: Dict[str, Any] = {
            "perfect_3_3": 0,
            "majority_2_3": 0,
            "no_consensus": 0,
            "total": 0,
            "perfect_3_3_pct": 0.0,
            "majority_2_3_pct": 0.0,
            "no_consensus_pct": 0.0,
        }

        for original_tc in original_test_cases:
            key = tuple(sorted((k, v) for k, v in original_tc.items() if k != "expected_output"))
            labels = test_case_key_to_labels.get(key, [])

            # Filter out None labels for counting
            non_null_labels = [l for l in labels if l is not None]

            if len(non_null_labels) == 0:
                # No labels at all
                final_label = None
                stats["no_consensus"] += 1
            elif len(non_null_labels) == len(labels) and len(set(non_null_labels)) == 1:
                # Perfect agreement (all 3 agree)
                final_label = non_null_labels[0]
                stats["perfect_3_3"] += 1
            else:
                # Count votes
                vote_counts = Counter(non_null_labels)
                most_common = vote_counts.most_common(1)[0]
                final_label, vote_count = most_common

                if vote_count >= 2:
                    # Majority (2/3 or 3/3)
                    stats["majority_2_3"] += 1
                else:
                    # No consensus (1/3 or tie)
                    stats["no_consensus"] += 1
                    # Still use the most common, but it's a weak consensus

            result_tc = original_tc.copy()
            result_tc["expected_output"] = final_label
            aggregated.append(result_tc)
            stats["total"] += 1

        # Calculate percentages
        if stats["total"] > 0:
            stats["perfect_3_3_pct"] = (stats["perfect_3_3"] / stats["total"]) * 100
            stats["majority_2_3_pct"] = (stats["majority_2_3"] / stats["total"]) * 100
            stats["no_consensus_pct"] = (stats["no_consensus"] / stats["total"]) * 100
        else:
            stats["perfect_3_3_pct"] = 0.0
            stats["majority_2_3_pct"] = 0.0
            stats["no_consensus_pct"] = 0.0

        return aggregated, stats

    def _create_labeling_prompt(
        self,
        test_cases: List[Dict[str, Any]],
        valid_outputs: List[str],
        workflow_analysis: Optional[Dict[str, Any]] = None,
    ) -> str:
        test_cases_json = json.dumps(test_cases, indent=2)

        # Build structured context if workflow_analysis is provided
        context_section = ""
        if workflow_analysis:
            context_section = f"""
WORKFLOW STRUCTURE (use this structured analysis to help determine outputs):
{json.dumps(workflow_analysis, indent=2)}

This structured analysis includes:
- inputs: All workflow inputs with their types and ranges
- decision_points: Decision logic with exact conditions and branches
- workflow_paths: Complete paths from inputs to outputs
- outputs: All possible output states

Use this structured information ALONGSIDE the workflow image to accurately determine outputs.
"""

        return f"""You are analyzing a workflow diagram to label test cases with their EXACT expected outputs.
{context_section}
VALID OUTPUTS (you MUST choose EXACTLY one of these, preserving the exact capitalization and punctuation):
{json.dumps(valid_outputs, indent=2)}

TEST CASES TO LABEL:
{test_cases_json}

CRITICAL INSTRUCTIONS:
1. For EACH test case, trace through the workflow step-by-step from start to finish
2. Follow EVERY decision point carefully using the EXACT input values provided
3. Use the structured workflow analysis (decision_points, workflow_paths) to understand the logic
4. Cross-reference with the workflow image to verify your path
5. The output MUST be EXACTLY one of the valid outputs listed above (exact match, including capitalization)
6. If you're unsure between two paths, re-trace the logic carefully - there is only ONE correct answer per test case

APPROACH:
- Start with the first input/decision point
- For each decision, check the condition against the test case values
- Follow the branch that matches
- Continue until you reach a terminal output
- Double-check: does this output match one of the valid outputs EXACTLY?

Return your response as a JSON array with the same length as the test cases array. Each element should be a string containing the expected output for that test case. The string must EXACTLY match one of the valid outputs (character-for-character, including case and punctuation).

Return ONLY the JSON array, no explanations or other text."""

    def _normalize_output(self, output: str | None, valid_outputs: List[str]) -> str | None:
        """Fuzzy match output to valid_outputs with case-insensitive and normalization."""
        if output is None:
            return None

        # Exact match first
        if output in valid_outputs:
            return output

        # Case-insensitive match
        output_lower = output.strip().lower()
        for valid in valid_outputs:
            if valid.strip().lower() == output_lower:
                logger.debug(
                    "Case-insensitive match",
                    extra={"model_output": output, "matched": valid},
                )
                return valid

        # Normalize punctuation and whitespace
        output_normalized = re.sub(r"\s+", " ", output.strip())
        for valid in valid_outputs:
            valid_normalized = re.sub(r"\s+", " ", valid.strip())
            if valid_normalized.lower() == output_normalized.lower():
                logger.debug(
                    "Normalized match",
                    extra={"model_output": output, "matched": valid},
                )
                return valid

        # Log what we couldn't match
        logger.warning(
            "Could not match model output to valid outputs",
            extra={"model_output": output, "valid_outputs": valid_outputs[:5]},
        )
        return None

    def _parse_labeling_response(
        self, test_cases: List[Dict[str, Any]], response_text: str, valid_outputs: List[str]
    ) -> List[Dict[str, Any]]:
        json_match = re.search(r"\[.*\]", response_text, re.DOTALL)
        json_text = json_match.group(0) if json_match else response_text.strip()

        try:
            expected_outputs = json.loads(json_text)
            if not isinstance(expected_outputs, list):
                raise ValueError("Response is not a list")
        except Exception as e:
            logger.error(
                f"❌ Failed parsing labeling response: {str(e)}\n"
                f"Response preview: {response_text[:800]}\n"
                f"JSON text extracted: {json_text[:500]}",
                extra={"error": str(e)},
            )
            expected_outputs = [None] * len(test_cases)

        if len(expected_outputs) != len(test_cases):
            if len(expected_outputs) < len(test_cases):
                expected_outputs.extend([None] * (len(test_cases) - len(expected_outputs)))
            else:
                expected_outputs = expected_outputs[: len(test_cases)]

        labeled: List[Dict[str, Any]] = []
        for tc, expected in zip(test_cases, expected_outputs):
            out = tc.copy()
            # Use fuzzy matching instead of strict equality
            out["expected_output"] = self._normalize_output(expected, valid_outputs)
            labeled.append(out)
        return labeled

    def _generate_values_for_input(self, inp: StandardizedInput, num_samples: int = 5) -> List[Any]:
        from ..core.workflow import StandardizedRange

        input_type = inp.input_type
        range_info = inp.range

        logger.debug(
            f"Generating values for {inp.input_name}: type={input_type}, range={range_info}"
        )

        if input_type == "bool":
            return [True, False]

        if isinstance(range_info, list):
            return range_info

        # Handle both dict and StandardizedRange (Pydantic model)
        if isinstance(range_info, (dict, StandardizedRange)):
            if isinstance(range_info, StandardizedRange):
                min_val = range_info.min
                max_val = range_info.max
                value = range_info.value
            else:
                min_val = range_info.get("min")
                max_val = range_info.get("max")
                value = range_info.get("value")

            if value is not None:
                return [value]

            if input_type == "Int":
                if min_val is not None and max_val is not None:
                    values: List[Any] = [int(min_val), int(max_val)]
                    if max_val > min_val:
                        mid = (int(min_val) + int(max_val)) // 2
                        values.append(mid)
                        for _ in range(max(0, num_samples - 3)):
                            values.append(random.randint(int(min_val), int(max_val)))
                    return list(dict.fromkeys(values))
                if min_val is not None:
                    return [int(min_val), int(min_val) + 10, int(min_val) + 100]
                if max_val is not None:
                    return [int(max_val), int(max_val) - 10, int(max_val) - 100]
                return [0, 1, 10, 100, -1, -10]

            if input_type == "Float":
                if min_val is not None and max_val is not None:
                    values2: List[Any] = [float(min_val), float(max_val)]
                    if max_val > min_val:
                        midf = (float(min_val) + float(max_val)) / 2
                        values2.append(midf)
                        for _ in range(max(0, num_samples - 3)):
                            values2.append(random.uniform(float(min_val), float(max_val)))
                    # ensure JSON-serializable float values
                    return list(dict.fromkeys(values2))
                if min_val is not None:
                    return [float(min_val), float(min_val) + 0.1, float(min_val) + 1.0]
                if max_val is not None:
                    return [float(max_val), float(max_val) - 0.1, float(max_val) - 1.0]
                return [0.0, 0.1, 1.0, 10.0, -1.0, -10.0]

        if input_type == "str":
            return ["value1", "value2", "example", ""]
        if input_type == "date":
            return ["2024-01-01", "2024-06-15", "2024-12-31"]
        return [None]
