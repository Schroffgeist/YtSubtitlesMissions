#!/usr/bin/env python3
import os
import subprocess
import shutil
import argparse
from pathlib import Path
import concurrent.futures
from typing import List

def get_args():
    """Parses and returns command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Recursively distill a large number of text files into a single summary using Gemini LLM. Supports batching by count or size, with resume capability.",
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
        default="prompt.txt",
        help="Path to a text file containing the prompt for the LLM."
    )

    # --- Concurrency and Batching Arguments ---
    parser.add_argument(
        "-b", "--batch-size",
        type=int,
        default=21,
        help="Batch size meaning depends on --batch-mode: number of files (count) or total bytes (size)."
    )
    parser.add_argument(
        "--batch-mode",
        choices=["count", "size"],
        default="count",
        help="Batching mode: 'count' = batch by number of files, 'size' = batch by total file size (bytes)."
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
        default=610,
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
    """Splits files into batches by count (old behavior)."""
    if not file_list:
        return []
    return [file_list[i:i + batch_size] for i in range(0, len(file_list), batch_size)]

def create_batches_by_size(file_list: List[Path], target_batch_size: int) -> List[List[Path]]:
    """
    Create batches of files based on total byte size.
    - Large files go alone.
    - Small files are grouped until the batch reaches the target size.
    """
    if not file_list:
        return []

    files_with_sizes = [(f, f.stat().st_size) for f in file_list]
    files_with_sizes.sort(key=lambda x: x[1], reverse=True)  # biggest first

    batches = []
    current_batch = []
    current_size = 0

    for f, size in files_with_sizes:
        if size >= target_batch_size:
            if current_batch:
                batches.append(current_batch)
                current_batch = []
                current_size = 0
            batches.append([f])  # big file alone
        else:
            if current_size + size > target_batch_size and current_batch:
                batches.append(current_batch)
                current_batch = []
                current_size = 0
            current_batch.append(f)
            current_size += size

    if current_batch:
        batches.append(current_batch)

    return batches

def create_batches(file_list: List[Path], batch_size: int, batch_mode: str) -> List[List[Path]]:
    """Dispatch to batching strategy based on mode."""
    if batch_mode == "size":
        return create_batches_by_size(file_list, batch_size)
    else:
        return create_batches_by_count(file_list, batch_size)

def _process_single_batch(batch: List[Path], round_number: int, batch_number: int,
                          output_dir: Path, model: str, prompt: str, timeout: int):
    """Process a single batch in a separate thread."""
    print(f"  -> Processing Batch {batch_number} (Round {round_number})...")
    file_references = " ".join([f"'@{str(file_path)}'" for file_path in batch])
    full_prompt = f"{prompt} {file_references}"
    command_str = f"gemini -m {model} -y -p \"{full_prompt}\""

    try:
        result = subprocess.run(
            command_str,
            shell=True,
            capture_output=True,
            text=True,
            check=True,
            encoding='utf-8',
            timeout=timeout
        )
        output_filename = output_dir / f"round_{round_number}_batch_{batch_number}.txt"
        with open(output_filename, "w", encoding='utf-8') as f:
            f.write(result.stdout)
        print(f"     Success! Saved distilled output to: {output_filename.name}")
        return output_filename
    except FileNotFoundError:
        print(f"[ERROR] 'gemini' command not found. Please ensure gemini-cli is installed and in your PATH.")
        raise
    except subprocess.TimeoutExpired:
        print(f"[ERROR] Command timed out for Batch {batch_number} after {timeout} seconds.")
        raise
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] gemini-cli failed for Batch {batch_number}. Exit Code: {e.returncode}")
        print(f"Stderr: {e.stderr}")
        raise
    except Exception as e:
        print(f"[ERROR] Unexpected error in Batch {batch_number}: {e}")
        raise

def run_distillation_round(input_files: List[Path], round_number: int, output_path: Path,
                           batch_size: int, batch_mode: str, max_workers: int,
                           model: str, prompt: str, timeout: int, resume: bool) -> List[Path] or None:
    """Run one round of distillation in batches."""
    print(f"\n--- Starting Round {round_number} ---")
    print(f"Processing {len(input_files)} files in this round.")

    batches = create_batches(input_files, batch_size, batch_mode)
    print(f"Divided into {len(batches)} batches (mode={batch_mode}, size={batch_size}).")

    output_files = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_batch_number = {}
        for i, batch in enumerate(batches):
            batch_number = i + 1
            expected_output = output_path / f"round_{round_number}_batch_{batch_number}.txt"
            if resume and expected_output.exists():
                print(f"  -> SKIPPING Batch {batch_number}: output already exists.")
                output_files.append(expected_output)
                continue
            future = executor.submit(_process_single_batch,
                                     batch, round_number, batch_number,
                                     output_path, model, prompt, timeout)
            future_to_batch_number[future] = batch_number

        for future in concurrent.futures.as_completed(future_to_batch_number):
            batch_number = future_to_batch_number[future]
            try:
                output_file = future.result()
                if output_file:
                    output_files.append(output_file)
            except Exception as exc:
                print(f"Batch {batch_number} failed: {exc}")
                executor.shutdown(wait=False, cancel_futures=True)
                return None

    return sorted(output_files, key=lambda p: p.name)

def main():
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
        print(f"  - {arg}: {value}")
    print("--------------------------------------------")

    if not source_path.is_dir():
        print(f"[ERROR] Source directory not found: {source_path}")
        return
    if not prompt_file_path.is_file():
        print(f"[ERROR] Prompt file not found: {prompt_file_path}")
        return
    try:
        with open(prompt_file_path, "r", encoding="utf-8") as f:
            prompt = f.read()
    except Exception as e:
        print(f"[ERROR] Could not read prompt file: {e}")
        return

    if args.resume:
        print(f"Resume mode enabled. Using existing output directory: {output_path}")
        os.makedirs(output_path, exist_ok=True)
    else:
        if output_path.exists():
            print(f"Clearing output directory: {output_path}")
            shutil.rmtree(output_path)
        os.makedirs(output_path)

    initial_files = sorted([p for p in source_path.glob(f"**/*{args.extension}")])
    if not initial_files:
        print(f"[ERROR] No files with extension '{args.extension}' found in {source_path}")
        return

    print(f"Found {len(initial_files)} source files.")
    current_files = initial_files
    round_count = 1

    while len(current_files) > 1:
        distilled_files = run_distillation_round(
            current_files, round_count, output_path,
            args.batch_size, args.batch_mode, args.max_workers,
            args.model, prompt, args.timeout, args.resume
        )
        if distilled_files is None:
            print("Aborting due to error. Use --resume to continue.")
            return
        current_files = distilled_files
        round_count += 1

    if len(current_files) == 1:
        final_file = current_files[0]
        final_destination = output_path / "ULTRA_DISTILLED_SUMMARY.txt"
        shutil.move(str(final_file), str(final_destination))
        print("\n✅ Distillation Complete!")
        print(f"Final summary saved to: {final_destination}")
    else:
        print("[ERROR] No distilled files produced. Aborting.")

if __name__ == "__main__":
    main()

