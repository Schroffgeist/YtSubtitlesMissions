import heapq
from typing import List, Tuple
from pathlib import Path

# ---------- NEW HELPER -------------------------------------------------
class _Bin:
    """Helper for the bin-packing algorithm."""
    __slots__ = ("paths", "size")

    def __init__(self) -> None:
        self.paths: List[Path] = []
        self.size: int = 0

    # Make the bin comparable by size so heapq can always give us the smallest
    def __lt__(self, other: "_Bin") -> bool:
        return self.size < other.size


def create_size_balanced_batches(
    file_list: List[Path],
    *,
    max_files_per_batch: int,
    max_batches: int = None,
) -> List[List[Path]]:
    """
    Split *file_list* into at most *max_batches* batches whose **total byte size**
    is as even as possible.  No batch will contain more than *max_files_per_batch*
    individual files.
    """
    if not file_list:
        return []

    # Build (size, path) pairs and sort DESCENDING (largest first)
    sized_files: List[Tuple[int, Path]] = [
        (p.stat().st_size, p) for p in file_list
    ]
    sized_files.sort(reverse=True, key=lambda t: t[0])

    if max_batches is None:
        max_batches = max(1, (len(file_list) + max_files_per_batch - 1) // max_files_per_batch)

    # ---------- Worst-fit decreasing ----------
    bins: List[_Bin] = [_Bin() for _ in range(max_batches)]
    heapq.heapify(bins)

    for size, path in sized_files:
        # Pick the bin that currently has the smallest total size
        smallest_bin = heapq.heappop(bins)

        # Respect the hard file-count limit
        if len(smallest_bin.paths) >= max_files_per_batch:
            # All bins are full by *count*; open a new one
            new_bin = _Bin()
            new_bin.paths.append(path)
            new_bin.size = size
            heapq.heappush(bins, new_bin)
        else:
            smallest_bin.paths.append(path)
            smallest_bin.size += size
            heapq.heappush(bins, smallest_bin)

    # Return non-empty bins only
    return [b.paths for b in bins if b.paths]


# ---------- PATCHED `run_distillation_round` -----------------------------
def run_distillation_round(
    input_files: List[Path],
    round_number: int,
    output_path: Path,
    batch_size: int,
    max_workers: int,
    model: str,
    prompt: str,
    timeout: int,
    resume: bool,
) -> List[Path] | None:
    """
    Same interface as before, but internally uses the size-balanced batching.
    """
    print(f"\n--- Starting Round {round_number} ---")
    print(f"Processing {len(input_files)} files in this round.")

    batches = create_size_balanced_batches(
        input_files,
        max_files_per_batch=batch_size,
        max_batches=None,  # let the algo decide, capped by file-count above
    )
    print(f"Divided into {len(batches)} size-balanced batches.")

    output_files = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_batch_number = {}

        for i, batch in enumerate(batches):
            batch_number = i + 1
            expected_output = output_path / f"round_{round_number}_batch_{batch_number}.txt"

            if resume and expected_output.exists():
                print(
                    f"  -> SKIPPING Batch {batch_number} (Round {round_number}): "
                    f"Output file already exists."
                )
                output_files.append(expected_output)
                continue

            future = executor.submit(
                _process_single_batch,
                batch,
                round_number,
                batch_number,
                output_path,
                model,
                prompt,
                timeout,
            )
            future_to_batch_number[future] = batch_number

        for future in concurrent.futures.as_completed(future_to_batch_number):
            batch_number = future_to_batch_number[future]
            try:
                output_file = future.result()
                if output_file:
                    output_files.append(output_file)
            except Exception as exc:
                print(f"Batch {batch_number} generated an exception: {exc}")
                executor.shutdown(wait=False, cancel_futures=True)
                return None

    return sorted(output_files, key=lambda p: p.name)
