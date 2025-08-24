import os
import subprocess
import math
import shutil
from pathlib import Path
import concurrent.futures

# --- CONFIGURATION ---
# --- Please edit these variables to match your setup ---

# 1. The folder where your initial .vtt files are located.
#    Example: "/path/to/my/youtube_subtitles"
SOURCE_DIRECTORY = "./"

# 2. The file extension of your source files.
#    For subtitle files, this is typically ".vtt".
FILE_EXTENSION = ".vtt"

# 3. The directory to store the intermediate and final distilled files.
#    The script will create this folder if it doesn't exist.
OUTPUT_DIRECTORY = "./distilled_output"

# 4. The prompt you want to send to the Gemini LLM.
#    This will be used for every distillation step.
PROMPT = (
    "You are an expert analyst of subtitles/transcripts. Your task is to synthesize key themes, core ideas,"
    "and critical information from the provided transcripts into a concise, well-structured, and"
    "comprehensive summary. Here's how to approach it:"
    "1. Filtering: Ignore conversational filler, repeated phrases, and off-topic remarks."
    "2. Details: Include sources of information, important dates and facts, and people involved."
    "   Pay attention to the file title for hints about the subject and publication date."
    "3. Analysis:"
    "   - Perform a dialectic analysis."
    "   - Consider geopolitical implications, visualizing the world as a chess board with various"
    "       elements (people, companies, technology, politicians, weather) as players. Focus on their"
    "       positions, magnitudes, and strategic directions."
    "4. Length: If there's too much information, keep the summary under 8000 words."
    "5. Output: The result should be a template or layout for objective news reporting."
    "In other words: You are an expert analyst of subtitles. Your task is to synthesize the key themes, "
    "core ideas, and most important information from the following transcripts. "
    "Ignore conversational filler, repeated phrases, and off-topic remarks. "
    "Create a concise, well-structured, and comprehensive summary of the combined content."
    "Mention sources of info, important dates and facts as well as people involved."
    "The title of the file provides some info, a hint of the subject and the date of publication."
    "Also pay atention to a dialectic analysis and the geopolitical implications, decisions, positions,"
    "movements, military location as if the world was a chess board and people, companies, technology!,"
    "politicians and even weather take part of the game. Position, magnitud and direction of strategies are the main focus."
    "The only rule is that if there's too much information don't surpass 8000 words."
    "The result is expected to function as a template or layout of flat objective news, imagine you're news show host presenting the news in a very emotionless manner."
)

# 5. The model you want to use with the gemini-cli.
#    Example: "gemini-2.5-pro" or "gemini-1.5-flash"
MODEL = "gemini-2.5-flash"

# 6. The number of files to process in a single batch.
BATCH_SIZE = 3

# 7. Max number of concurrent workers (threads) for processing batches.
#    Adjust based on your system's capabilities and API rate limits.
MAX_WORKERS = 5

# --- END OF CONFIGURATION ---


def create_batches(file_list, batch_size):
    """Splits a list of files into smaller chunks (batches)."""
    if not file_list:
        return []
    return [file_list[i:i + batch_size] for i in range(0, len(file_list), batch_size)]

def _process_single_batch(batch, round_number, batch_number, output_dir):
    """
    Helper function to process a single batch.
    This function will be run in a separate thread.
    """
    print(f"  -> Processing Batch {batch_number} (Round {round_number})...")

    # Convert the absolute path to a relative path from the current working directory.
    # This now works for all rounds because `batch` always contains absolute paths.
    file_references = " ".join([f"'@{str(file_path.relative_to(Path.cwd()))}'" for file_path in batch])

    # Combine the main prompt and the file references into a single prompt string.
    full_prompt = f"{PROMPT} {file_references}"

    # The command now passes the combined prompt to the -p argument.
    command_str = f"gemini -m {MODEL} -p \"{full_prompt}\""

    try:
        # Using shell=True to correctly handle the complex, quoted prompt string.
        result = subprocess.run(
            command_str,
            shell=True,
            capture_output=True,
            text=True,
            check=True,
            encoding='utf-8',
            timeout=300
        )

        # `output_dir` is absolute, so `output_filename` will be too.
        output_filename = output_dir / f"round_{round_number}_batch_{batch_number}.txt"
        with open(output_filename, "w", encoding='utf-8') as f:
            f.write(result.stdout)

        print(f"     Success! Saved distilled output to: {output_filename.name}")
        # Return the absolute path of the new file for the next round.
        return output_filename

    except FileNotFoundError:
        print(f"\n[ERROR] 'gemini' command not found for Batch {batch_number}.")
        raise
    except subprocess.TimeoutExpired:
        print(f"\n[ERROR] Command timed out for Batch {batch_number}.")
        raise
    except subprocess.CalledProcessError as e:
        print(f"\n[ERROR] An error occurred while running the gemini-cli for Batch {batch_number}.")
        print(f"  Command executed: {command_str}")
        print(f"  Exit Code: {e.returncode}")
        print(f"  Stdout: {e.stdout}")
        print(f"  Stderr: {e.stderr}")
        raise
    except Exception as e:
        print(f"\n[ERROR] An unexpected error occurred for Batch {batch_number}: {e}")
        raise

def run_distillation_round(input_files, round_number, output_path):
    """
    Processes a list of input files in batches and generates distilled output files.
    """
    print(f"\n--- Starting Round {round_number} ---")
    print(f"Processing {len(input_files)} files in this round.")

    batches = create_batches(input_files, BATCH_SIZE)
    print(f"Divided into {len(batches)} batches of up to {BATCH_SIZE} files each.")

    output_files = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # Pass the absolute output_path to each worker thread.
        future_to_batch_number = {
            executor.submit(_process_single_batch, batch, round_number, i + 1, output_path): i + 1
            for i, batch in enumerate(batches)
        }

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
    base_path = Path.cwd()
    source_path = base_path / SOURCE_DIRECTORY
    output_path = base_path / OUTPUT_DIRECTORY

    print("--- LLM Distillation Script Initializing ---")

    if not source_path.is_dir():
        print(f"[ERROR] Source directory not found: '{source_path}'")
        return

    if output_path.exists():
        print(f"Output directory '{output_path}' already exists. Clearing it for a fresh run.")
        shutil.rmtree(output_path)
    os.makedirs(output_path)
    print(f"Output will be saved in: '{output_path.resolve()}'")

    # Use resolve() to ensure we start with absolute paths.
    initial_files = sorted([p for p in source_path.resolve().glob(f"**/*{FILE_EXTENSION}")])

    if not initial_files:
        print(f"[ERROR] No files with extension '{FILE_EXTENSION}' found in '{source_path}'.")
        return

    print(f"Found {len(initial_files)} source files to process.")

    current_files = initial_files
    round_count = 1

    while len(current_files) > 1:
        # Pass the absolute output_path to the distillation round function.
        distilled_files = run_distillation_round(current_files, round_count, output_path)

        if distilled_files is None:
            print("\nAborting script due to an error in the distillation round.")
            return

        # The returned `distilled_files` now contains absolute paths,
        # ensuring the next round works correctly.
        current_files = distilled_files
        round_count += 1

    if len(current_files) == 1:
        final_file = current_files[0]
        final_destination = output_path / "ULTRA_DISTILLED_SUMMARY.txt"
        shutil.move(str(final_file), str(final_destination))
        print("\n==============================================")
        print("✅ Distillation Complete!")
        print(f"The final summary has been saved as:")
        print(f"   {final_destination.resolve()}")
        print("==============================================")
    elif not current_files:
         print("\n[ERROR] No distilled files were produced in the last round. Aborting.")
    else:
        print("\n[WARNING] Something went wrong. No final file was produced.")


if __name__ == "__main__":
    main()

