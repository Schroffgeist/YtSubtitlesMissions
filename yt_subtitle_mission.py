import csv
import json
import os
import re
import shlex
import subprocess
import sys
import time
import argparse # Added for command-line arguments
from datetime import datetime
from pathlib import Path

# --- Configuration ---
MASTER_CHANNEL_LIST = Path("youtube_channel_list.csv") # Assuming this still exists
PROCESSED_DIR = Path("processed_subtitles")
MODEL = "gemini-2.5-flash" # For LLM calls
LLM_TIMEOUT = 377 # Timeout for LLM calls
YT_DLP_METADATA_TIMEOUT = 180 # Timeout for yt-dlp metadata fetching
YT_DLP_DOWNLOAD_TIMEOUT = 300 # Timeout for yt-dlp subtitle download
YT_DLP_SLEEP_INTERVAL = 21 # Minimum sleep between requests
YT_DLP_MAX_SLEEP_INTERVAL = 34 # Maximum sleep between requests
YT_DLP_RETRY_COUNT = 3 # Retries for yt-dlp commands

# --- Helper Functions ---

def print_header(title):
    """Prints a formatted header to the console."""
    print("\n" + "=" * 70)
    print(f"--- {title.upper()} ---")
    print("=" * 70)

def get_user_input(prompt, default=None):
    """Gets user input with a default option and handles cancellation."""
    prompt_text = f"{prompt} "
    if default:
        prompt_text += f"[{default}] "
    
    try:
        response = input(prompt_text).strip()
        return response if response else default
    except (KeyboardInterrupt, EOFError):
        print("\n\nOperación cancelada por el operador.")
        sys.exit(1)

def run_shell_command(command_list, timeout, description="Executing command"):
    """Runs a shell command and returns its stdout, handling errors."""
    command_str = " ".join(shlex.quote(arg) for arg in command_list)
    print(f"  -> {description}: {command_str}")
    try:
        result = subprocess.run(
            command_list,
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
        print(f"  -> ERROR: Command failed with exit code {e.returncode}.")
        print(f"     Stderr: {e.stderr.strip()}")
    except Exception as e:
        print(f"  -> ERROR: An unexpected error occurred: {e}")
    return None

def sanitize_filename(title):
    """Sanitizes a string to be a safe filename."""
    s = re.sub(r'[<>:"/\\|?*]', '_', title) # Replace invalid characters
    s = re.sub(r'\\s+', '_', s).strip() # Replace spaces with single underscores
    s = s[:150] # Limit length
    return s

# --- LLM Interaction (for language detection only) ---

def get_language_from_title(title):
    """Uses LLM to detect if a title is in Spanish or English."""
    prompt = f"Detect the language of the following text. Respond only 'es' for Spanish or 'en' for English. Do not add any other text or explanation. Text: '{title}'"
    command = ["gemini", "-p", prompt, "-m", MODEL]
    output = run_shell_command(command, LLM_TIMEOUT, description="Detecting language with LLM")
    if output:
        clean_lines = [line for line in output.strip().split('\n') if "Loaded cached credentials" not in line]
        llm_response = clean_lines[-1].strip().lower() if clean_lines else None
        if llm_response in ['es', 'en']:
            return llm_response
    print(f"  -> WARNING: LLM could not reliably detect language for '{title}'. Defaulting to 'es'.")
    return 'es' # Fallback to a default language

# --- Mission Classes ---

class MissionItem:
    """Represents a single video to be processed."""
    def __init__(self, channel_name, channel_url, video_id, title, upload_date):
        self.channel_name = channel_name
        self.channel_url = channel_url
        self.video_id = video_id
        self.title = title
        self.upload_date = upload_date
        self.language = None # Will be determined later
        self.status = "Pending"
        self.error_message = ""
        self.final_filepath = None

    def process(self):
        """Downloads and cleans subtitles for this mission item."""
        print(f"\n--- Processing: {self.title} ({self.video_id}) ---")

        # 1. Check if already processed
        existing_files = list(PROCESSED_DIR.glob(f"*.{self.video_id}.*.cleaned.vtt"))
        if existing_files:
            self.status = "Success (Already Exists)"
            self.final_filepath = existing_files[0]
            print(f"  -> Subtitle already exists: {self.final_filepath.name}. Skipping download.")
            return

        # 2. Determine language (LLM call)
        self.language = get_language_from_title(self.title)
        print(f"  -> Detected language: {self.language.upper()}")

        # 3. Download subtitles
        if not self._download_subtitle():
            self.status = "Failed (Download)"
            self.error_message = "Subtitle download failed after retries."
            print(f"  -> ERROR: {self.error_message}")
            return

        # 4. Clean and rename
        if not self._clean_and_rename_subtitle():
            self.status = "Failed (Cleanup/Rename)"
            self.error_message = "Subtitle cleanup or renaming failed."
            print(f"  -> ERROR: {self.error_message}")
            return
        
        self.status = "Success"
        print(f"  -> Successfully processed: {self.final_filepath.name}")

    def _download_subtitle(self):
        """Attempts to download subtitles with retries and language fallback."""
        temp_vtt_path = PROCESSED_DIR / f"{self.video_id}.{self.language}.vtt"
        
        # Try primary language first
        yt_dlp_cmd = [
            "yt-dlp",
            "--write-auto-subs",
            "--skip-download",
            "--sub-langs", self.language,
            "--paths", str(PROCESSED_DIR),
            "-o", f"{self.video_id}.%(ext)s", # Output to temp name
            f"https://www.youtube.com/watch?v={self.video_id}"
        ]
        
        print(f"  -> Attempting download for '{self.language}'...")
        stdout = run_shell_command(yt_dlp_cmd, YT_DLP_DOWNLOAD_TIMEOUT, description="Downloading subtitle")
        
        if temp_vtt_path.exists():
            return True
        
        # Fallback to opposite language if primary fails
        fallback_lang = 'en' if self.language == 'es' else 'es'
        temp_vtt_path = PROCESSED_DIR / f"{self.video_id}.{fallback_lang}.vtt"
        yt_dlp_cmd[5] = fallback_lang # Update sub-langs
        
        print(f"  -> Primary language failed. Attempting fallback to '{fallback_lang}'...")
        stdout = run_shell_command(yt_dlp_cmd, YT_DLP_DOWNLOAD_TIMEOUT, description="Downloading subtitle (fallback)")
        
        if temp_vtt_path.exists():
            self.language = fallback_lang # Update language to the one that worked
            return True
        
        return False

    def _clean_and_rename_subtitle(self):
        """Cleans the VTT file and renames it to the final format."""
        raw_vtt_file = PROCESSED_DIR / f"{self.video_id}.{self.language}.vtt"
        if not raw_vtt_file.exists():
            print(f"  -> ERROR: Raw VTT file not found for cleaning: {raw_vtt_file}")
            return False

        sanitized_base_name = sanitize_filename(self.title)
        self.final_filepath = PROCESSED_DIR / f"{sanitized_base_name}.{self.video_id}.{self.language}.cleaned.vtt"

        print(f"  -> Cleaning and renaming to: {self.final_filepath.name}")
        
        # Use pure Python for cleaning to avoid shell injection and improve control
        try:
            with open(raw_vtt_file, 'r', encoding='utf-8') as infile, \
                 open(self.final_filepath, 'w', encoding='utf-8') as outfile:
                
                seen_lines = set()
                for line in infile:
                    # Remove common VTT metadata lines
                    if any(keyword in line for keyword in ["WEBVTT", "Kind:", "Language:", "-->"]):
                        continue
                    
                    # Remove HTML tags
                    clean_line = re.sub(r'<[^>]*>', '', line)
                    # Remove >>
                    clean_line = clean_line.replace('>>', '')
                    # Strip leading/trailing whitespace
                    clean_line = clean_line.strip()
                    # Replace multiple spaces with single space
                    clean_line = re.sub(r'\\s+', ' ', clean_line)
                    
                    if clean_line: # Only write non-empty lines
                        # Add a dash for readability, if not already present
                        if not clean_line.startswith('- '):
                            clean_line = '- ' + clean_line
                        
                        # Avoid duplicate lines
                        if clean_line not in seen_lines:
                            outfile.write(clean_line + '\n')
                            seen_lines.add(clean_line)
            
            raw_vtt_file.unlink() # Delete the raw VTT file
            return True
        except Exception as e:
            print(f"  -> ERROR during cleaning/renaming: {e}")
            return False


class MissionControl:
    """Orchestrates the entire subtitle mission."""
    def __init__(self):
        self.targets = [] # List of {'name', 'url', 'cutoff'}
        self.mission_queue = [] # List of MissionItem objects
        self.successful_missions = []
        self.failed_missions = []

    def run(self):
        """Executes the full mission workflow."""
        print_header("Starting YouTube Subtitle Mission")
        PROCESSED_DIR.mkdir(exist_ok=True)

        self._interactive_setup()
        if not self.targets:
            print("No targets defined. Aborting mission.")
            return

        self._adjudicate_targets()
        if not self.mission_queue:
            print("No videos found matching criteria. Aborting mission.")
            return

        self._process_mission_queue()
        self._generate_report()

    def _load_missions_from_file(self, file_path):
        """Loads missions from a pre-existing CSV file."""
        try:
            with file_path.open(newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f) # Assuming standard CSV with headers
                for row in reader:
                    # Adjust column names based on your actual CSV structure
                    self.mission_queue.append(MissionItem(
                        channel_name=row.get('Channel Name', 'Unknown'),
                        channel_url=row.get('Channel URL', 'Unknown'),
                        video_id=row.get('Video ID', 'Unknown'),
                        title=row.get('Title', 'Unknown'),
                        upload_date=row.get('Upload Date', 'Unknown')
                    ))
            print(f"Loaded {len(self.mission_queue)} missions from '{file_path}'.")
        except Exception as e:
            print(f"ERROR: Could not load missions from file: {e}")
            sys.exit(1)

    def _interactive_setup(self):
        """Guides user through selecting channels and setting cutoff dates."""
        print_header("Phase 1: Mission Manifest Creation")
        if not MASTER_CHANNEL_LIST.exists():
            print(f"ERROR: Master channel list '{MASTER_CHANNEL_LIST}' not found.")
            sys.exit(1)

        with MASTER_CHANNEL_LIST.open(newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f, skipinitialspace=True, quotechar="'")
            
            # Implement default date logic here if desired, similar to old script
            # default_date = datetime.now().strftime('%Y%m%d')

            for row in reader:
                name = row.get("Channel Name", "").strip()
                url = row.get("Handle / URL", "").strip()
                if not name or not url:
                    continue

                print(f"\n--- Channel: {name} ---")
                if get_user_input(f"  Include this channel? (s/n):", 'n') != 's':
                    continue

                base_url = url.split(";")[0].rstrip("/")
                
                # Videos and Streams sections
                for section in ("videos", "streams"):
                    date = get_user_input(f"    > Cutoff date for /{section} (YYYYMMDD) or Enter to skip:", default="")
                    if date:
                        self.targets.append({'name': name, 'url': f"{base_url}/{section}", 'cutoff': date})
                
                # Playlists (up to 3)
                for i in range(1, 4):
                    pl_url = row.get(f"Playlist URL {i}", "").strip()
                    if pl_url:
                        date = get_user_input(f"    > Cutoff date for Playlist {i} ({pl_url}) or Enter to skip:", default="")
                        if date:
                            self.targets.append({'name': name, 'url': pl_url, 'cutoff': date})

    def _adjudicate_targets(self):
        """Fetches video info using yt-dlp with date filters and populates mission queue."""
        print_header("Phase 2: Target Adjudication")
        for target in self.targets:
            print(f"\nAdjudicating for: {target['name']} ({target['url']})")
            print(f"  Cutoff date: {target['cutoff']}")

            # Use yt-dlp's --dateafter filter directly
            yt_dlp_cmd = [
                "yt-dlp",
                "--skip-download",
                "--print-json",
                "--dateafter", target['cutoff'],
                "--no-warnings", # Suppress warnings for cleaner output
                target['url']
            ]
            
            print(f"  -> Fetching metadata with yt-dlp...")
            try:
                process = subprocess.Popen(
                    yt_dlp_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, # Capture stderr to prevent clutter
                    text=True,
                    encoding='utf-8',
                    preexec_fn=os.setsid # Create new process group for clean termination
                )

                for line in process.stdout:
                    try:
                        data = json.loads(line)
                        video_id = data.get('id')
                        upload_date = data.get('upload_date')
                        title = data.get('title', 'No Title')
                        
                        if all([video_id, upload_date, title]):
                            print(f"    -> Found: {upload_date} - {title} [{video_id}]")
                            self.mission_queue.append(MissionItem(
                                target['name'], target['url'], video_id, title, upload_date
                            ))
                        else:
                            print(f"    -> WARNING: Incomplete metadata for a video. Skipping: {line.strip()}")

                    except json.JSONDecodeError:
                        pass
                
                stderr_output = process.stderr.read()
                if stderr_output:
                    print(f"  -> yt-dlp stderr: {stderr_output.strip()}")

                if process.poll() is None:
                    os.killpg(os.getpgid(process.pid), 15) # SIGTERM
                    process.wait() # Wait for it to actually terminate

            except FileNotFoundError:
                print("  -> ERROR: 'yt-dlp' not found. Please ensure it's installed and in your PATH.")
                sys.exit(1)
            except Exception as e:
                print(f"  -> ERROR: Failed to fetch metadata for {target['url']}: {e}")

        print(f"\n  -> Total videos added to mission queue: {len(self.mission_queue)}")

    def _process_mission_queue(self):
        """Processes each MissionItem in the queue."""
        print_header(f"Phase 3: Intelligence Extraction ({len(self.mission_queue)} videos)")
        for i, mission_item in enumerate(self.mission_queue):
            mission_item.process()
            if mission_item.status.startswith("Success"):
                self.successful_missions.append(mission_item)
            else:
                self.failed_missions.append(mission_item)
            
            if i < len(self.mission_queue) - 1:
                sleep_time = YT_DLP_SLEEP_INTERVAL
                print(f"  -> Sleeping for {sleep_time} seconds to avoid throttling...")
                time.sleep(sleep_time)

    def _generate_report(self):
        """Generates a final mission report."""
        print_header("Phase 4: Mission Report")
        print(f"Total videos attempted: {len(self.mission_queue)}")
        print(f"Successful extractions: {len(self.successful_missions)}")
        print(f"Failed extractions: {len(self.failed_missions)}")

        if self.failed_missions:
            print("\n--- Failed Missions Details ---")
            for mission in self.failed_missions:
                print(f"  - ID: {mission.video_id}")
                print(f"    Title: {mission.title}")
                print(f"    Error: {mission.error_message}")
        
        self._write_mission_report_csv(self.successful_missions, "successful_missions")
        self._write_mission_report_csv(self.failed_missions, "failed_missions")

        print("\n" + "=" * 70)
        print("--- MISSION COMPLETE ---")
        print("=" * 70)

    def _write_mission_report_csv(self, missions_list, filename_prefix):
        """Writes a list of missions to a CSV file."""
        if not missions_list:
            return
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = Path(f"{filename_prefix}_{timestamp}.csv")
        print(f"\nGenerating {filename_prefix} report in: {report_path}")
        try:
            with report_path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "Channel Name", "Channel URL", "Video ID", "Title",
                    "Upload Date", "Language", "Status", "Error Message", "Final Filepath"
                ])
                for m in missions_list:
                    writer.writerow([
                        m.channel_name, m.channel_url, m.video_id, m.title,
                        m.upload_date, m.language, m.status, m.error_message,
                        m.final_filepath.name if m.final_filepath else "N/A"
                    ])
        except Exception as e:
            print(f"  -> ERROR: Could not write {filename_prefix} report: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Automate YouTube subtitle extraction based on channels and date ranges.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        '-m', '--mission-file', type=str,
        help="Path to a pre-existing mission report CSV file to process directly (e.g., mission_report_20250810_123456.csv).\n" 
             "If provided, interactive setup is skipped and processing begins immediately."
    )
    args = parser.parse_args()

    controller = MissionControl()
    if args.mission_file:
        mission_file_path = Path(args.mission_file)
        if mission_file_path.exists():
            print(f"Non-interactive mode: Loading missions from '{mission_file_path}'")
            controller._load_missions_from_file(mission_file_path)
            if not controller.mission_queue:
                print("No missions loaded from file. Aborting.")
                sys.exit(1)
            controller._process_mission_queue()
            controller._generate_report()
        else:
            print(f"ERROR: Mission file specified does not exist: {mission_file_path}")
            sys.exit(1)
    else:
        controller.run() # This will trigger the interactive setup and full workflow
