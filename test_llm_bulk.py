#!/usr/bin/env python3
import csv
import sys
from pathlib import Path
import subprocess

# --- Configuration (copied from main script) ---
MODEL = "gemini-2.5-flash"
LLM_TIMEOUT = 377

# --- Helper Functions (copied and simplified) ---

def run_command(command, timeout):
    """Runs a shell command and returns its stdout, handling errors."""
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding='utf-8',
            timeout=timeout,
            check=True
        )
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        print(f"  -> ERROR: Command timed out after {timeout}s.")
    except subprocess.CalledProcessError as e:
        print(f"  -> ERROR: Command failed with code {e.returncode}.")
        print(f"     Stderr: {e.stderr.strip()}")
    except Exception as e:
        print(f"  -> ERROR: An unexpected error occurred: {e}")
    return None

def llm_call(prompt):
    """Generic function to call the LLM."""
    print("\n" + "-"*20 + " DEBUG LLM CALL " + "-"*20)
    print("PROMPT SENT TO LLM:")
    print(prompt)
    print("-" * 56)
    
    command = ["gemini", "-p", prompt, "-m", MODEL]
    output = run_command(command, LLM_TIMEOUT)
    if not output:
        return None
    
    lines = output.strip().split('\n')
    clean_lines = [line for line in lines if "Loaded cached credentials" not in line]
    return "\n".join(clean_lines)

def bulk_detect_languages(missions):
    """Detects language for all missions in a single LLM call."""
    if not missions:
        print("No missions to process.")
        return

    separator = "|||"
    payload_lines = [f"{m['id']}{separator}{m['title']}" for m in missions]
    payload = "\n".join(payload_lines)

    prompt = (
        f"Analyze the following list of videos in 'video_id{separator}title' format.\n"
        f"For each line, detect if the title is in Spanish ('es') or English ('en').\n"
        f"Respond ONLY with a CSV list with 'video_id,language' columns.\n"
        f"Do not include headers. Your response must have exactly {len(payload_lines)} lines.\n\n"
        f"VIDEO LIST:\n{payload}"
    )

    print(f"Sending {len(missions)} titles to the LLM for analysis...")
    response_csv = llm_call(prompt)

    if not response_csv:
        print("  -> ERROR: No response received from LLM.")
        return

    print("\n" + "-"*20 + " LLM RESPONSE " + "-"*20)
    print(response_csv)
    print("-" * 54)

def main():
    if len(sys.argv) < 2:
        print("Usage: python test_llm_bulk.py <path_to_mission_report.csv>")
        sys.exit(1)

    mission_file = Path(sys.argv[1])
    if not mission_file.exists():
        print(f"Error: File not found at {mission_file}")
        sys.exit(1)

    missions = []
    with mission_file.open(newline='', encoding='utf-8') as f:
        # Assuming the report has headers: Channel,Video ID,Upload Date,Title,Status,Language,Final Filename,Error
        reader = csv.DictReader(f)
        for row in reader:
            missions.append({'id': row['Video ID'], 'title': row['Title']})
    
    bulk_detect_languages(missions)

if __name__ == "__main__":
    main()
