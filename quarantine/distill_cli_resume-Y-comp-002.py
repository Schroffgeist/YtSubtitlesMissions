#!/usr/bin/env python3
import os
import subprocess
import shutil
import argparse
from pathlib import Path
import concurrent.futures
from typing import List, Tuple
import math

def get_args():
    """Parses and returns command-line arguments."""
    parser = argparse.ArgumentParser(
        description="A script to recursively distill a large number of text files into a single summary using a Gemini LLM. Includes resume capability.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )

    # --- Directory and File Arguments ---
    parser = argparse.ArgumentParser(
        description="A script to recursively distill a large number of text files into a single summary using a Gemini LLM. Includes resume capability.",
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
        help="The number of files to process in a single batch."
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

    # --- Size-based Batching ---
    parser.add_argument(
        "--size-based-batching",
        action="store_true",
        help="Enable size-based batching to distribute files more evenly by their sizes."
    )
    parser.add_argument(
        "--max-batch-size-mb",
        type=float,
        default=10.0,
        help="Maximum total size of files in a batch (in MB) when using size-based batching."
    )

    return parser.parse_args()

def get_file_size_mb(file_path: Path) -> float:
    """Get file size in megabytes."""
    return file_path.stat().st_size / (1024 * 1024)

def create_batches(file_list: List[Path], batch_size: int, size_based: bool = False, max_batch_size_mb: float = 10.0) -> List[List[Path]]:
    """
    Splits a list of files into smaller chunks (batches).
    If size_based is True, uses a bin packing approach to create more evenly-sized batches.
    """
    if not file_list:
        return []
    
    if not size_based:
        # Original simple batching by count
        return [file_list[i:i + batch_size] for i in range(0, len(file_list), batch_size)]
    
    # Size-based batching using First Fit Decreasing algorithm [[5]]
    # Sort files by size descending to place larger files first
    files_with_sizes = [(f, get_file_size_mb(f)) for f in file_list]
    files_with_sizes.sort(key=lambda x: x[1], reverse=True)
    
    batches = []
    batch_sizes = []  # Track current size of each batch
    
    for file_path, file_size in files_with_sizes:
        # Skip files larger than max_batch_size_mb
        if file_size > max_batch_size_mb:
            print(f"Warning: File {file_path} is larger than max batch size ({file_size:.2f} MB > {max_batch_size_mb} MB). Processing individually.")
            batches.append([file_path])
            batch_sizes.append(file_size)
            continue
            
        # Try to fit file in existing batch
        placed = False
        for i, batch in enumerate(batches):
            if batch_sizes[i] + file_size <= max_batch_size_mb:
                batch.append(file_path)
                batch_sizes[i] += file_size
                placed = True
                break
        
        # If file didn't fit in any existing batch, create new batch
        if not placed:
            batches.append([file_path])
            batch_sizes.append(file_size)
    
    # Further optimize by trying to fill smaller batches with tiny files
    # This is a simplified version of bin compaction [[4]]
    for i in range(len(batches) - 1, 0, -1):  # Iterate backwards
        if len(batches[i]) == 1 and get_file_size_mb(batches[i][0]) > max_batch_size_mb * 0.8:
            # Keep large single-file batches as they are
            continue
            
        # Try to move files from this batch to earlier batches
        files_to_move = []
        for j, file_path in enumerate(batches[i]):
            file_size = get_file_size_mb(file_path)
            for k in range(i):  # Check all previous batches
                if batch_sizes[k] + file_size <= max_batch_size_mb:
                    batches[k].append(file_path)
                    batch_sizes[k] += file_size
                    files_to_move.append(j)
                    break
        
        # Remove moved files (in reverse order to maintain indices)
        for j in reversed(files_to_move):
            batches[i].pop(j)
        
        # Remove batch if it became empty
        if not batches[i]:
            batches.pop(i)
            batch_sizes.pop(i)
    
    return batches

def _process_single_batch(batch: List[Path], round_number: int, batch_number: int, output_dir: Path, model: str, prompt: str, timeout: int):
    """
    Helper function to process a single batch. This will be run in a separate thread.
    """
    print(f"  -> Processing Batch {batch_number} (Round {round_number})...")
    
    # Calculate total size of this batch
    total_size_mb = sum(get_file_size_mb(f) for f in batch)
    print(f"     Batch contains {len(batch)} files, total size: {total_size_mb:.2f} MB")

    # <<< FIX: No longer need relative_to() as we now pass absolute paths directly.
    # This is more robust for subprocess calls.
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
            timeout=timeout # <<< FIX: Use the configurable timeout
        )
        output_filename = output_dir / f"round_{round_number}_batch_{batch_number}.txt"
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

def run_distillation_round(input_files: List[Path], round_number: int, output_path: Path, batch_size: int, max_workers: int, model: str, prompt: str, timeout: int, resume: bool, size_based_batching: bool, max_batch_size_mb: float) -> List[Path] or None:
    """
    Processes a list of input files in batches and generates distilled output files.
    Skips batches if resuming and their output already exists.
    """
    print(f"\n--- Starting Round {round_number} ---")
    print(f"Processing {len(input_files)} files in this round.")
    
    # Use the enhanced batching function
    batches = create_batches(input_files, batch_size, size_based_batching, max_batch_size_mb)
    
    print(f"Divided into {len(batches)} batches.")
    if size_based_batching:
        batch_info = [f"{len(b)} files, {sum(get_file_size_mb(f) for f in b):.2f} MB" for b in batches]
        print(f"Batch details: {', '.join(batch_info)}")

    output_files = []
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_batch_number = {}

        for i, batch in enumerate(batches):
            batch_number = i + 1
            expected_output = output_path / f"round_{round_number}_batch_{batch_number}.txt"

            if resume and expected_output.exists():
                print(f"  -> SKIPPING Batch {batch_number} (Round {round_number}): Output file already exists.")
                output_files.append(expected_output)
                continue

            future = executor.submit(_process_single_batch, batch, round_number, batch_number, output_path, model, prompt, timeout)
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
    
    # <<< FIX: Resolve paths at the beginning to ensure absolute paths are used everywhere.
    source_path = Path(args.source_dir).resolve()
    output_path = Path(args.output_dir).resolve()
    prompt_file_path = Path(args.prompt_file).resolve()

    print("--- LLM Distillation Script Initializing ---")
    print("Configuration:")
    # Create a dictionary from args for clean printing
    config_dict = vars(args)
    # Add resolved paths for clarity
    config_dict['source_dir_resolved'] = source_path
    config_dict['output_dir_resolved'] = output_path
    config_dict['prompt_file_resolved'] = prompt_file_path
    
    for arg, value in sorted(config_dict.items()):
        # Hide the original relative paths if you want, or just show all
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
            prompt = f.read()
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
            current_files, round_count, output_path,
            args.batch_size, args.max_workers, args.model, prompt, args.timeout, args.resume,
            args.size_based_batching, args.max_batch_size_mb  # Pass new arguments
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
        # This case handles when the script finishes a round and there are still multiple files left, but the loop condition `len > 1` will catch it.
        # It's good practice to have a final check.
        print(f"\n[INFO] Distillation finished. {len(current_files)} files remaining in the output directory.")

if __name__ == "__main__":
    main()
