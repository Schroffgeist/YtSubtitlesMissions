#!/usr/bin/env python3

import os
import subprocess
import argparse
import re
import shutil
import json

def sanitize_filename(filename):
    """
    Removes or replaces characters that can be problematic for shells or file systems.
    """
    # Replace known problematic characters with an underscore
    unsafe_chars = r'[$&|!*\'"`@~#]'
    sanitized = re.sub(unsafe_chars, '_', filename)
    # Replace multiple spaces with a single space
    sanitized = re.sub(r'\s+', ' ', sanitized).strip()
    return sanitized

def clean_vtt_file_python(input_filepath, output_filepath):
    """
    Applies cleaning operations to a VTT file using pure Python.
    Removes WEBVTT header, metadata, timestamps, blank lines, HTML tags,
    and duplicate lines. Prepends lines with '- '.
    """
    seen_lines = set()
    try:
        with open(input_filepath, 'r', encoding='utf-8') as infile, \
             open(output_filepath, 'w', encoding='utf-8') as outfile:
            for line in infile:
                # Skip header and metadata
                if line.strip() == 'WEBVTT' or 'Kind:' in line or 'Language:' in line:
                    continue
                # Skip timestamps
                if '-->' in line:
                    continue
                # Strip HTML tags
                line = re.sub(r'<[^>]*>', '', line)
                # Strip " >>" which often appears as &gt;&gt;
                line = line.replace('&gt;&gt;', '')
                # Normalize whitespace and strip leading/trailing space
                line = re.sub(r'\s+', ' ', line).strip()
                # Skip blank lines that might result from cleaning
                if not line:
                    continue
                # Prepend with dash and space
                line_to_check = f'- {line}'
                # Ensure uniqueness
                if line_to_check not in seen_lines:
                    outfile.write(line_to_check + '\n')
                    seen_lines.add(line_to_check)
        print(f"Cleaned '{input_filepath}' to '{output_filepath}'")
        return True
    except Exception as e:
        print(f"An unexpected error occurred during Python cleaning of {input_filepath}: {e}")
        return False

def download_and_organize_subtitles(batch_file, datebefore, dateafter, sub_langs, output_path):
    """
    Downloads subtitles and then organizes them into folders by channel handle.
    """
    temp_dir = os.path.join(output_path, 'temp_subtitles')
    os.makedirs(temp_dir, exist_ok=True)

    # --- Pass 1: Download all subtitles to a temporary directory ---
    print("--- Starting Pass 1: Downloading all subtitles ---")
    download_command = [
        'yt-dlp',
        '--windows-filenames',
        '--restrict-filenames',
        '--progress',
        '--batch-file', batch_file,
        '--datebefore', datebefore,
        f'--break-match-filters', f"upload_date >= {dateafter}",
        '--download-archive', os.path.abspath(os.path.join(output_path, 'ytdl-archive.txt')),
        '--force-write-archive',
        '--sleep-interval', '8',
        '--max-sleep-interval', '13',
        '--sleep-requests', '5',
        '--sleep-subtitles', '21',
        '--retries', '3',
        '--retry-sleep', 'exp=8:13',
        '--skip-download',
        '--match-filter', "availability ='public'",
        '--write-auto-subs',
        '--sub-langs', sub_langs,
        '--paths', temp_dir,
        '-o', '%(id)s.%(ext)s',
        '--write-info-json',
        '--break-per-input'
    ]

    try:
        print(f"Executing download command: {' '.join(download_command)}")
        subprocess.run(download_command, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Warning: yt-dlp exited with an error (code {e.returncode}). This can be normal if --break-match-filters is triggered. Continuing to organization pass.")
    except Exception as e:
        print(f"An unexpected error occurred during download: {e}")

    print("--- Finished Pass 1: Downloading subtitles ---")

    # --- Pass 2: Organize subtitles into folders ---
    print("--- Starting Pass 2: Organizing subtitles ---")
    for filename in os.listdir(temp_dir):
        if filename.endswith('.info.json'):
            json_path = os.path.join(temp_dir, filename)
            vtt_filename = filename.replace('.info.json', '.es.vtt')
            vtt_path = os.path.join(temp_dir, vtt_filename)

            if os.path.exists(vtt_path):
                with open(json_path, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)

                # Extract data from metadata
                upload_date = metadata.get('upload_date', '')
                video_id = metadata.get('id', '')
                playlist = metadata.get('playlist', '')
                uploader_id = metadata.get('uploader_id', '')
                channel_id = metadata.get('channel_id', '')
                title = metadata.get('title', '')
                lang = 'es'
                ext = 'vtt'

                # Sanitize parts for final filename and folder name
                playlist_clean = sanitize_filename(playlist)
                uploader_id_clean = sanitize_filename(uploader_id.replace('@', ''))
                channel_id_clean = sanitize_filename(channel_id)
                title_clean = sanitize_filename(title)

                # Construct final clean filename
                final_filename_parts = [
                    f"({upload_date})",
                    f"[{video_id}]",
                    playlist_clean,
                    uploader_id_clean,
                    channel_id_clean,
                    title_clean,
                    lang,
                    'cleaned',
                    ext
                ]
                final_filename = '.'.join(filter(None, final_filename_parts))
                
                # Construct final folder name
                folder_name_parts = [channel_id_clean, uploader_id_clean, playlist_clean]
                folder_name = '.'.join(filter(None, folder_name_parts))
                
                if not folder_name:
                    print(f"Could not determine a valid directory name for {vtt_filename}. Leaving in temp folder.")
                    os.remove(json_path) # remove json file
                    continue

                # Clean the VTT file
                cleaned_temp_path = vtt_path.replace('.vtt', '.cleaned.vtt')
                if clean_vtt_file_python(vtt_path, cleaned_temp_path):
                    os.remove(vtt_path)
                else:
                    print(f"Skipping organization for failed-to-clean file: {vtt_filename}")
                    os.remove(json_path) # remove json file
                    continue

                # Move and rename the cleaned file
                channel_dir = os.path.join(output_path, folder_name)
                os.makedirs(channel_dir, exist_ok=True)
                dest_path = os.path.join(channel_dir, final_filename)

                print(f"Moving and renaming {cleaned_temp_path} to {dest_path}")
                try:
                    shutil.move(cleaned_temp_path, dest_path)
                    os.remove(json_path) # remove json file
                except FileNotFoundError:
                    print(f"Error moving file: {cleaned_temp_path} not found.")
            else:
                print(f"VTT file not found for {filename}. Skipping.")
                os.remove(json_path) # remove json file


    print("--- Finished Pass 2: Organizing subtitles ---")
    if os.path.isdir(temp_dir) and not os.listdir(temp_dir):
        try:
            os.rmdir(temp_dir)
            print(f"Removed empty temporary directory: {temp_dir}")
        except OSError as e:
            print(f"Error removing temp directory {temp_dir}: {e}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Download and organize YouTube subtitles.')
    parser.add_argument('--batch-file', required=True, help='File with list of URLs.')
    parser.add_argument('--datebefore', required=True, help='End date (YYYYMMDD).')
    parser.add_argument('--dateafter', required=True, help='Start date (YYYYMMDD).')
    parser.add_argument('--sub-langs', default='es', help='Subtitle languages (e.g., en,es).')
    parser.add_argument('--output-path', default='subtitles', help='Base directory for subtitles.')

    args = parser.parse_args()

    download_and_organize_subtitles(args.batch_file, args.datebefore, args.dateafter, args.sub_langs, args.output_path)
