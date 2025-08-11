#!/usr/bin/env python3
import csv
import sys
from pathlib import Path
import subprocess

# --- Configuration (copied from main script) ---
MODEL = "gemini-2.5-flash"
LLM_TIMEOUT = 600 

def llm_call(prompt):
    """Generic function to call the LLM, passing the prompt via stdin."""
    print("\n" + "-"*20 + " DEBUG LLM STDIN CALL " + "-"*20)
    print("PROMPT TO BE SENT TO LLM STDIN:")
    print(prompt)
    print("-" * 60)
    
    command = ["gemini", "-p", "-", "-m", MODEL]  # The "-" tells gemini to read from stdin

    try:
        result = subprocess.run(
            command,
            input=prompt,  # Pass the prompt to stdin
            capture_output=True,
            text=True,
            encoding='utf-8',
            timeout=LLM_TIMEOUT,
            check=True  # A non-zero exit code from gemini is a real error
        )
        output = result.stdout.strip()
        lines = output.strip().split('\n')
        clean_lines = [line for line in lines if "Loaded cached credentials" not in line]
        return "\n".join(clean_lines)
    except subprocess.TimeoutExpired:
        print(f"  -> ERROR: LLM command timed out after {LLM_TIMEOUT}s.")
    except subprocess.CalledProcessError as e:
        print(f"  -> ERROR: LLM command failed with code {e.returncode}.")
        print(f"     Stderr: {e.stderr.strip()}")
    except Exception as e:
        print(f"  -> ERROR: An unexpected error occurred during LLM call: {e}")
    return None

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
        print("Usage: python test_llm_stdin.py <path_to_mission_report.csv>")
        sys.exit(1)

    mission_file = Path(sys.argv[1])
    if not mission_file.exists():
        print(f"Error: File not found at {mission_file}")
        sys.exit(1)

    missions = []
    with mission_file.open(newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            missions.append({'id': row['Video ID'], 'title': row['Title']})
    
    bulk_detect_languages(missions)

if __name__ == "__main__":
    main()
