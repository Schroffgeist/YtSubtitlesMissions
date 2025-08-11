#!/usr/bin/env python3
import csv
import json
import os
import re
import shlex
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# --- Configuration ---
PROCESSED_DIR = Path("subtitulos_jalife")
YT_DLP_ARCHIVE = Path("ytdl-archive.txt")
MODEL = "gemini-2.5-flash"
LLM_TIMEOUT = 377
YT_DLP_TIMEOUT = 300
YT_DLP_SLEEP_INTERVAL = 5
YT_DLP_MAX_SLEEP_INTERVAL = 13
YT_DLP_SLEEP_REQUESTS = 3
YT_DLP_SLEEP_SUBTITLES = 21
YT_DLP_RETRIES = 3

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
        print(f"  -> ERROR: El comando excedió el tiempo límite de {timeout}s.")
    except subprocess.CalledProcessError as e:
        print(f"  -> ERROR: El comando falló con el código {e.returncode}.")
        print(f"     Stderr: {e.stderr.strip()}")
    except Exception as e:
        print(f"  -> ERROR: Ocurrió un error inesperado al ejecutar el comando: {e}")
    return None

def sanitize_title_for_filename(title):
    """A more robust function to sanitize titles for filenames."""
    if not title:
        return "no_title"
    # Remove invalid file system characters
    sanitized = re.sub(r'[<>:"/|?*]', '_', title)
    # Replace sequences of whitespace with a single underscore
    sanitized = re.sub(r'\s+', '_', sanitized)
    # Remove leading/trailing underscores
    sanitized = sanitized.strip('_')
    # Limit length to avoid issues with file systems
    return sanitized[:100]

# --- LLM Interaction ---

def get_language_from_title(title):
    """Uses LLM to detect if a title is in Spanish or English."""
    prompt = f"Detecta el idioma del siguiente texto. Responde solo 'es' para español o 'en' para inglés.\n\nTexto: '{title}'"
    command = ["gemini", "-p", prompt, "-m", MODEL]
    output = run_command(command, LLM_TIMEOUT)
    if output:
        # Extract the last meaningful line from the output
        lines = output.strip().split('\n')
        clean_lines = [line for line in lines if "Loaded cached credentials" not in line]
        response = clean_lines[-1].strip().lower() if clean_lines else None
        if response in ['es', 'en']:
            return response
    return 'es' # Default to Spanish if detection fails

# --- Core Classes ---

class Mission:
    """Represents a single video processing task."""
    def __init__(self, channel_name, url, video_id, upload_date, title):
        self.channel_name = channel_name
        self.url = url
        self.video_id = video_id
        self.upload_date = upload_date
        self.title = title
        self.language = 'es' # Default language
        self.final_filename = None
        self.status = "Pendiente"
        self.error_message = ""

    def process(self):
        """Handles the download, cleaning, and renaming of a single video's subtitles."""
        print_header(f"Procesando: {self.title}")

        sanitized_title = sanitize_title_for_filename(self.title)
        
        # Check for existing file using a pattern that matches the new format
        # Format: [id].(upload_date).sanitized_title.lang.cleaned.vtt
        existing_files = list(PROCESSED_DIR.glob(f"{self.video_id}.*.cleaned.vtt"))
        if existing_files:
            self.status = "Éxito (Existente)"
            self.final_filename = existing_files[0]
            print(f"  -> El archivo ya existe: {self.final_filename.name}. Omitiendo.")
            return

        print("1. Detectando idioma del título...")
        self.language = get_language_from_title(self.title)
        print(f"  -> Idioma detectado: {self.language.upper()}")

        self.final_filename = PROCESSED_DIR / f"[{self.video_id}].({self.upload_date}).{sanitized_title}.{self.language}.cleaned.vtt"
        print(f"  -> Nombre final propuesto: {self.final_filename.name}")

        print("2. Descargando y limpiando subtítulos...")
        if self._download_and_clean(sanitized_title):
            self.status = "Éxito"
            print(f"  -> Subtítulo guardado en {self.final_filename}")
        else:
            self.status = "Fallo (Descarga)"
            self.error_message = "La descarga falló en ambos idiomas o la limpieza falló."
            print(f"  -> ERROR: {self.error_message}")

    def _download_and_clean(self, sanitized_title):
        """Attempts to download subtitles and cleans them."""
        for lang_attempt in [self.language, 'en' if self.language == 'es' else 'es']:
            print(f"  -> Intentando descarga en '{lang_attempt}'...")
            
            # Temporary filename for the download
            temp_output_template = f"[{self.video_id}].({self.upload_date}).{sanitized_title}.{lang_attempt}"
            
            yt_dlp_command = [
                "yt-dlp",
                "--write-auto-subs", "--sub-langs", lang_attempt,
                "--skip-download",
                "--continue", "--no-overwrites",
                "--retries", str(YT_DLP_RETRIES), "--retry-sleep", f"exp={YT_DLP_SLEEP_INTERVAL}:{YT_DLP_MAX_SLEEP_INTERVAL}",
                "--sleep-interval", str(YT_DLP_SLEEP_INTERVAL), "--max-sleep-interval", str(YT_DLP_MAX_SLEEP_INTERVAL),
                "--sleep-requests", str(YT_DLP_SLEEP_REQUESTS), "--sleep-subtitles", str(YT_DLP_SLEEP_SUBTITLES),
                "--match-filter", "availability ='public'",
                "--extractor-args", "youtube:formats=missing_pot",
                "--quiet", "--no-warnings",
                "--paths", str(PROCESSED_DIR),
                "-o", f"{temp_output_template}.%(ext)s",
                f"https://www.youtube.com/watch?v={self.video_id}"
            ]
            
            run_command(yt_dlp_command, YT_DLP_TIMEOUT)
            
            raw_vtt_path = PROCESSED_DIR / f"{temp_output_template}.{lang_attempt}.vtt"

            if raw_vtt_path.exists():
                print(f"  -> Descarga exitosa: {raw_vtt_path.name}")
                # The final filename is already determined, just rename the cleaned file
                self.final_filename = PROCESSED_DIR / f"[{self.video_id}].({self.upload_date}).{sanitized_title}.{lang_attempt}.cleaned.vtt"
                
                sed_awk_cmd = (
                    f"sed -E '/WEBVTT/d; /Kind:/d; /Language:/d; /-->/d; /^[[:space:]]*$/d; "
                    f"s/<[^>]*>//g; s/&gt;&gt;//g; s/^[[:space:]]*//; s/[[:space:]]*$//; "
                    f"s/[[:space:]][[:space:]]*/ /g; s/^/- /' '{raw_vtt_path}' | awk '!x[$0]++' > '{self.final_filename}'"
                )
                try:
                    subprocess.run(sed_awk_cmd, shell=True, check=True, timeout=60)
                    raw_vtt_path.unlink()
                    self.language = lang_attempt # Set language to the one that worked
                    return True
                except Exception as e:
                    print(f"  -> ERROR: Falló la limpieza del subtítulo: {e}")
                    if raw_vtt_path.exists(): raw_vtt_path.unlink()
                    return False
        return False

class MissionControl:
    """Orchestrates the entire subtitle mission from setup to completion."""
    def __init__(self):
        self.targets = []
        self.missions = []

    def run(self):
        """Executes the full mission workflow."""
        try:
            print_header("Inicio de la Misión de Inteligencia YT")
            PROCESSED_DIR.mkdir(exist_ok=True)

            self._interactive_setup()
            if not self.targets:
                print("No se definieron objetivos. Abortando misión.")
                return
                
            self._adjudicate_targets()
            self._process_missions()
            self._generate_report()
        except KeyboardInterrupt:
            print("\n\nOperación cancelada por el operador. Finalizando la misión de forma controlada.")
            sys.exit(1)
        except Exception as e:
            print(f"\n\nERROR INESPERADO EN EL CONTROLADOR PRINCIPAL: {e}")
            sys.exit(1)

    def _interactive_setup(self):
        """Guides the user through selecting channels and setting date ranges."""
        print_header("Fase 1: Creación de Manifiesto de Misión")
        
        source_choice = get_user_input("¿Usar 'lista_urls.txt' (1) o 'youtube_channel_list.csv' (2)?", '1')

        if source_choice == '1':
            url_file = Path("lista_urls.txt")
            if not url_file.exists():
                print(f"ERROR: No se encontró el archivo '{url_file}'.")
                sys.exit(1)
            urls = [line.strip() for line in url_file.read_text().splitlines() if line.strip()]
            start_date = get_user_input("Fecha de inicio (YYYYMMDD): ")
            end_date = get_user_input("Fecha de fin (YYYYMMDD): ", datetime.now().strftime('%Y%m%d'))
            for url in urls:
                self.targets.append({'name': url.split('/')[-1], 'url': url, 'start': start_date, 'end': end_date})
        else:
            channel_file = Path("youtube_channel_list.csv")
            if not channel_file.exists():
                print(f"ERROR: No se encontró el archivo '{channel_file}'.")
                sys.exit(1)
            with channel_file.open(newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f, skipinitialspace=True, quotechar="'")
                for row in reader:
                    name = row.get("Channel Name", "").strip()
                    url = row.get("Handle / URL", "").strip()
                    if not name or not url: continue
                    
                    print(f"\n--- Canal: {name} ---")
                    if get_user_input(f"¿Incluir este canal? (s/n):", 'n') != 's': continue
                    
                    start_date = get_user_input(f"  > Fecha de inicio para {name} (YYYYMMDD): ")
                    end_date = get_user_input(f"  > Fecha de fin para {name} (YYYYMMDD): ", datetime.now().strftime('%Y%m%d'))
                    
                    base_url = url.split(";")[0].rstrip("/")
                    for section in ("videos", "streams"):
                        self.targets.append({'name': name, 'url': f"{base_url}/{section}", 'start': start_date, 'end': end_date})
                    for i in range(1, 4):
                        pl_url = row.get(f"Playlist URL {i}", "").strip()
                        if pl_url:
                            self.targets.append({'name': name, 'url': pl_url, 'start': start_date, 'end': end_date})

    def _adjudicate_targets(self):
        """Fetches video info, filters by date, and creates missions."""
        print_header("Fase 2: Adjudicación de Objetivos (Recopilando Títulos)")
        for target in self.targets:
            print(f"\nAdjudicando para: {target['name']} ({target['url']})")
            print(f"Rango de fechas: {target['start']} - {target['end']}")

            yt_dlp_command = [
                "yt-dlp",
                "--batch-file", target['url'],
                "--datebefore", target['end'],
                "--break-match-filters", f"upload_date < {target['start']}",
                "--download-archive", str(YT_DLP_ARCHIVE),
                "--print", "[%(id)s]--[%(upload_date)s]--[%(title)s]",
                "--sleep-interval", str(YT_DLP_SLEEP_INTERVAL), "--max-sleep-interval", str(YT_DLP_MAX_SLEEP_INTERVAL),
                "--sleep-requests", str(YT_DLP_SLEEP_REQUESTS),
                "--retries", str(YT_DLP_RETRIES), "--retry-sleep", f"exp={YT_DLP_SLEEP_INTERVAL}:{YT_DLP_MAX_SLEEP_INTERVAL}",
                "--continue", "--no-overwrites",
                "--skip-download",
                "--match-filter", "availability ='public'",
                "--extractor-args", "youtube:formats=missing_pot",
                "--quiet", "--no-warnings"
            ]
            
            output = run_command(yt_dlp_command, YT_DLP_TIMEOUT)
            if output:
                for line in output.split('\n'):
                    if '--' in line:
                        try:
                            video_id, upload_date, title = line.split('--', 2)
                            self.missions.append(Mission(target['name'], target['url'], video_id, upload_date, title))
                            print(f"  -> Encontrado: {upload_date} - {title}")
                        except ValueError:
                            print(f"  -> ADVERTENCIA: Línea mal formada, omitiendo: {line}")
                            continue

    def _process_missions(self):
        """Processes all queued video missions."""
        print_header(f"Fase 3: Extracción de Inteligencia ({len(self.missions)} videos)")
        if not self.missions:
            print("No hay videos que cumplan los criterios para procesar.")
            return
            
        for i, mission in enumerate(self.missions):
            mission.process()
            if i < len(self.missions) - 1:
                print(f"\nEsperando {YT_DLP_SLEEP_SUBTITLES} segundos para evitar throttling...")
                time.sleep(YT_DLP_SLEEP_SUBTITLES)

    def _generate_report(self):
        """Prints a final summary and writes detailed CSV reports."""
        print_header("Fase 4: Reporte Final de Misión")
        success_count = sum(1 for m in self.missions if "Éxito" in m.status)
        fail_count = len(self.missions) - success_count

        print(f"Total de videos procesados: {len(self.missions)}")
        print(f"Éxitos: {success_count}")
        print(f"Fallos: {fail_count}")

        if fail_count > 0:
            print("\n--- Detalles de Fallos ---")
            for m in self.missions:
                if "Fallo" in m.status:
                    print(f"  - ID: {m.video_id}")
                    print(f"    Título: {m.title}")
                    print(f"    Estado: {m.status}")
                    print(f"    Error: {m.error_message}")

        # Generate CSV reports
        self._write_full_mission_report()
        self._write_failed_mission_report()

        print("\n" + "=" * 70)
        print("--- MISIÓN COMPLETADA ---")
        print("=" * 70)

    def _write_full_mission_report(self):
        """Writes a CSV report of all missions processed."""
        if not self.missions: return
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = Path(f"mission_report_{timestamp}.csv")
        print(f"\nGenerando reporte completo de la misión en: {report_path}")
        self._write_csv(report_path, self.missions)

    def _write_failed_mission_report(self):
        """Writes a CSV report of only the failed missions."""
        failed_missions = [m for m in self.missions if "Fallo" in m.status]
        if not failed_missions: return
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = Path(f"failed_missions_{timestamp}.csv")
        print(f"Generando reporte de misiones fallidas en: {report_path}")
        self._write_csv(report_path, failed_missions)

    def _write_csv(self, path, missions):
        try:
            with path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["Channel", "Video ID", "Upload Date", "Title", "Status", "Language", "Final Filename", "Error"])
                for m in missions:
                    writer.writerow([
                        m.channel_name, m.video_id, m.upload_date, m.title,
                        m.status, m.language,
                        m.final_filename.name if m.final_filename else "N/A",
                        m.error_message
                    ])
        except Exception as e:
            print(f"  -> ERROR: No se pudo escribir el reporte: {e}")

if __name__ == "__main__":
    controller = MissionControl()
    controller.run()