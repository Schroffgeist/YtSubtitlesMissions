#!/usr/bin/env python3
import os
import subprocess
import shutil
import argparse
from pathlib import Path
import concurrent.futures
from typing import List, Tuple
import heapq

def get_args():
    """Parses and returns command-line arguments."""
    parser = argparse.ArgumentParser(
        description="A script to recursively distill a large number of text files into a single summary using a Gemini LLM. Includes resume capability and multiple batching modes.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )

    # --- Directory and File Arguments ---
    parser.add_argument(
        "-s", "--source-dir",
        type=str,
        default="./",
        help="The folder where your initial source files are located."
    )
    parser.add_argument(
        "-o", "--output-dir",
        type=str,
        default="./distilled_output",
        help="The directory to store intermediate and final distilled files."
    )
    parser.add_argument(
        "-e", "--extension",
        type=str,
        default=".vtt",
        help="The file extension of your source files (e.g., '.vtt', '.txt')."
    )

    # --- LLM and Prompt Arguments ---
    parser.add_argument(
        "-m", "--model",
        type=str,
        default="gemini-2.5-flash",
        help="The model to use with the gemini-cli (e.g., 'gemini-2.5-pro', 'gemini-2.5-flash')."
    )
    parser.add_argument(
        "--prompt-file",
        type=str,
        default="./prompt_o3.000.txt",
        help="Path to a text file containing the prompt for the LLM."
    )

    # --- Concurrency and Batching Arguments ---
    parser.add_argument(
        "--batch-mode",
        choices=["count", "size", "balanced"],
        default="balanced",
        help="Batching mode: 'count' = by number of files, 'size' = greedy packing by size, 'balanced' = heap-based packing for even sizes."
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=55,
        help="Meaning depends on batch-mode: number of files for 'count', or max files per batch for 'balanced'."
    )
    parser.add_argument(
        "--max-batch-size-kb",
        type=int,
        default=1700,
        help="The maximum total size (in Kilobytes) of files to group into a single batch (for 'size' and 'balanced' modes)."
    )
    parser.add_argument(
        "--large-file-threshold-kb",
        type=int,
        default=1300,
        help="Files larger than this size (in Kilobytes) will be processed in their own dedicated batch (for 'size' mode)."
    )
    parser.add_argument(
        "-w", "--max-workers",
        type=int,
        default=3,
        help="Max number of concurrent workers (threads) for processing batches."
    )
    parser.add_argument(
        "-t", "--timeout",
        type=int,
        default=987,
        help="Timeout in seconds for each call to the gemini-cli."
    )

    # --- Resumability ---
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume an interrupted run. Skips batches that already have an output file."
    )

    return parser.parse_args()

def create_batches_by_count(file_list: List[Path], batch_size: int) -> List[List[Path]]:
    """Splits files into batches by a fixed number of files."""
    if not file_list:
        return []
    return [file_list[i:i + batch_size] for i in range(0, len(file_list), batch_size)]

def create_batches_by_greedy_size(
    file_list: List[Path], 
    max_batch_size_kb: int, 
    large_file_threshold_kb: int
) -> List[List[Path]]:
    """
    Splits files into batches using a greedy algorithm based on file size.
    """
    if not file_list:
        return []

    max_size_bytes = max_batch_size_kb * 1024
    large_file_bytes = large_file_threshold_kb * 1024

    try:
        files_with_sizes: List[Tuple[Path, int]] = [
            (p, p.stat().st_size) for p in file_list
        ]
    except FileNotFoundError as e:
        print(f"[ERROR] A file could not be found during batch creation: {e}")
        raise

    files_with_sizes.sort(key=lambda x: x[1], reverse=True)

    all_batches: List[List[Path]] = []
    files_to_pack: List[Tuple[Path, int]] = []

    for path, size in files_with_sizes:
        if size >= large_file_bytes:
            all_batches.append([path])
        else:
            files_to_pack.append((path, size))
            
    if files_to_pack:
        current_batch: List[Path] = []
        current_batch_size = 0
        for path, size in files_to_pack:
            if current_batch and current_batch_size + size > max_size_bytes:
                all_batches.append(current_batch)
                current_batch = []
                current_batch_size = 0
            
            current_batch.append(path)
            current_batch_size += size
        
        if current_batch:
            all_batches.append(current_batch)

    return all_batches

class _Bin:
    """Helper for the bin-packing algorithm."""
    __slots__ = ("paths", "size")

    def __init__(self) -> None:
        self.paths: List[Path] = []
        self.size: int = 0

    def __lt__(self, other: "_Bin") -> bool:
        return self.size < other.size

def create_balanced_batches(
    file_list: List[Path],
    max_files_per_batch: int,
) -> List[List[Path]]:
    """
    Splits files into batches with the most evenly distributed total byte size
    using a heap-based worst-fit-decreasing algorithm.
    """
    if not file_list:
        return []

    sized_files: List[Tuple[int, Path]] = [
        (p.stat().st_size, p) for p in file_list
    ]
    sized_files.sort(reverse=True, key=lambda t: t[0])

    num_batches = max(1, (len(file_list) + max_files_per_batch - 1) // max_files_per_batch)

    bins: List[_Bin] = [_Bin() for _ in range(num_batches)]
    heapq.heapify(bins)

    for size, path in sized_files:
        smallest_bin = heapq.heappop(bins)
        
        if len(smallest_bin.paths) >= max_files_per_batch:
            new_bin = _Bin()
            new_bin.paths.append(path)
            new_bin.size = size
            heapq.heappush(bins, new_bin)
        else:
            smallest_bin.paths.append(path)
            smallest_bin.size += size
            heapq.heappush(bins, smallest_bin)

    return [b.paths for b in bins if b.paths]

def _process_single_batch(batch: List[Path], round_number: int, batch_number: int, output_dir: Path, model: str, prompt: str, timeout: int):
    """
    Helper function to process a single batch in a separate thread.
    """
    batch_size_kb = sum(p.stat().st_size for p in batch) / 1024
    print(f"  -> Processing Batch {batch_number} (Round {round_number}) - {len(batch)} files, {batch_size_kb:.2f} KB...")

    # BUGFIX: Correctly format file paths with variables. The original code used {{}} which escaped the f-string.
    # The '@' prefix is kept as it seems to be the intended syntax for the gemini-cli.
    file_references = " ".join([f"'@'{file_path.resolve()}'" for file_path in batch])
    full_prompt = f"{prompt} {file_references}"

    # BUGFIX: Construct command as a list and use shell=False to avoid shell injection
    # and quoting issues with the prompt content.
    command = ["gemini", "-m", model, "-y", "-p", full_prompt]

    # BUGFIX: Correctly format the output filename.
    output_filename = output_dir / f"round_{round_number}_batch_{batch_number}.txt"

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,
            encoding='utf-8',
            timeout=timeout
        )
        with open(output_filename, "w", encoding='utf-8') as f:
            f.write(result.stdout)
        print(f"     Success! Saved distilled output to: {output_filename.name}")
        return output_filename
    except FileNotFoundError:
        print(f"\n[ERROR] 'gemini' command not found. Please ensure gemini-cli is installed and in your PATH.")
        raise
    except subprocess.TimeoutExpired:
        print(f"\n[ERROR] Command timed out for Batch {batch_number} after {timeout} seconds.")
        raise
    except subprocess.CalledProcessError as e:
        print(f"\n[ERROR] An error occurred while running gemini-cli for Batch {batch_number}.")
        print(f"  Exit Code: {e.returncode}")
        print(f"  Stderr: {e.stderr}")
        raise
    except Exception as e:
        print(f"\n[ERROR] An unexpected error occurred for Batch {batch_number}: {e}")
        raise


def run_distillation_round(
    input_files: List[Path], 
    round_number: int, 
    output_path: Path, 
    args: argparse.Namespace
) -> List[Path] or None:
    """
    Processes a list of input files in batches and generates distilled output files.
    """
    print(f"\n--- Starting Round {round_number} ---")
    print(f"Processing {len(input_files)} files in this round.")
    
    if args.batch_mode == 'count':
        batches = create_batches_by_count(input_files, args.batch_size)
    elif args.batch_mode == 'size':
        batches = create_batches_by_greedy_size(
            input_files, 
            args.max_batch_size_kb,
            args.large_file_threshold_kb
        )
    elif args.batch_mode == 'balanced':
        batches = create_balanced_batches(input_files, args.batch_size)
    
    print(f"Divided into {len(batches)} batches using '{args.batch_mode}' mode.")

    output_files = []
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.max_workers) as executor:
        future_to_batch_number = {}

        for i, batch in enumerate(batches):
            batch_number = i + 1
            # BUGFIX: Correctly format the output filename with variables.
            expected_output = output_path / f"round_{round_number}_batch_{batch_number}.txt"

            if args.resume and expected_output.exists():
                print(f"  -> SKIPPING Batch {batch_number} (Round {round_number}): Output file already exists.")
                output_files.append(expected_output)
                continue

            future = executor.submit(
                _process_single_batch, 
                batch, 
                round_number, 
                batch_number, 
                output_path, 
                args.model, 
                args.prompt,
                args.timeout
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

def main():
    """Main function to run the entire distillation pipeline."""
    args = get_args()
    
    source_path = Path(args.source_dir).resolve()
    output_path = Path(args.output_dir).resolve()
    prompt_file_path = Path(args.prompt_file).resolve()

    print("--- LLM Distillation Script Initializing ---")
    print("Configuration:")
    config_dict = vars(args)
    config_dict['source_dir_resolved'] = source_path
    config_dict['output_dir_resolved'] = output_path
    config_dict['prompt_file_resolved'] = prompt_file_path
    
    for arg, value in sorted(config_dict.items()):
        if '_resolved' in arg:
            print(f"  - {arg.replace('_', ' ').replace('resolved', '(resolved)')}: {value}")
        else:
            print(f"  - {arg.replace('_', ' ').capitalize()}: {value}")

    print("--------------------------------------------")

    if not source_path.is_dir():
        print(f"[ERROR] Source directory not found: '{source_path}'")
        return

    if not prompt_file_path.is_file():
        print(f"[ERROR] Prompt file not found: '{prompt_file_path}'")
        return
        
    try:
        with open(prompt_file_path, "r", encoding="utf-8") as f:
            args.prompt = f.read()
    except Exception as e:
        print(f"[ERROR] Could not read the prompt file: {e}")
        return

    if args.resume:
        print(f"Resume mode enabled. Will not clear output directory: '{output_path}'")
        os.makedirs(output_path, exist_ok=True)
    else:
        if output_path.exists():
            print(f"Output directory '{output_path}' already exists. Clearing it for a fresh run.")
            shutil.rmtree(output_path)
        os.makedirs(output_path)
    
    initial_files = sorted([p for p in source_path.glob(f"**/*{args.extension}")])

    if not initial_files:
        print(f"[ERROR] No files with extension '{args.extension}' found in '{source_path}'.")
        return

    print(f"Found {len(initial_files)} source files to process.")
    current_files = initial_files
    round_count = 1

    while len(current_files) > 1:
        distilled_files = run_distillation_round(
            current_files, round_count, output_path, args
        )
        if distilled_files is None:
            print("\nAborting script due to an error in the distillation round.")
            print("To continue, run the script again with the --resume flag.")
            return
        current_files = distilled_files
        round_count += 1

    if len(current_files) == 1 and round_count > 1:
        final_file = current_files[0]
        final_destination = output_path / "ULTRA_DISTILLED_SUMMARY.txt"
        shutil.move(str(final_file), str(final_destination))
        print("\n==============================================")
        print("✅ Distillation Complete!")
        print(f"The final summary has been saved as:")
        print(f"   {final_destination}")
        print("==============================================")
    elif len(current_files) == 1 and round_count == 1:
        print("\n[INFO] Only one batch was processed. The result is in the output folder.")
    elif not current_files:
         print("\n[ERROR] No distilled files were produced in the last round. Aborting.")
    else:
        print(f"\n[INFO] Distillation finished. {len(current_files)} files remaining in the output directory.")

if __name__ == "__main__":
    main()
