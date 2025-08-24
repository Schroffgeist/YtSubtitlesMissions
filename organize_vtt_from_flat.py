import os
import re
import shutil

def sanitize_filename(filename):
    """
    Removes or replaces characters that can be problematic for shells or file systems.
    This version prefers spaces over underscores for readability, but replaces unsafe chars with underscores.
    """
    # Replace known problematic characters with an underscore
    unsafe_chars = r'[$&|!*`"@~#]'
    sanitized = re.sub(unsafe_chars, '_', filename)
    # Replace multiple spaces with a single space, preserving single spaces
    sanitized = re.sub(r'\s+', ' ', sanitized).strip()
    return sanitized

def organize_vtt_from_flat(source_flat_dir, destination_base_dir):
    print(f"Starting organization from flat directory: {source_flat_dir}")
    print(f"Organizing into base directory: {destination_base_dir}")

    # Regex to extract the fixed date and video_id parts, and the rest of the filename
    # This is the most robust way to handle the variable parts in between.
    initial_pattern = re.compile(r'^\((\d{8})\)\.\[([a-zA-Z0-9_-]+)\]\.(.*)\.([a-z]{2})\.cleaned\.vtt$')
    # Groups: 1=upload_date, 2=video_id, 3=content_before_lang, 4=lang

    processed_count = 0
    skipped_count = 0
    for filename in os.listdir(source_flat_dir):
        if filename.endswith('.vtt'):
            source_filepath = os.path.join(source_flat_dir, filename)
            match_initial = initial_pattern.match(filename)

            if match_initial:
                upload_date = match_initial.group(1)
                video_id = match_initial.group(2)
                content_before_lang = match_initial.group(3) # This part contains uploader_name.channel_id.title
                lang = match_initial.group(4)

                # Now, parse content_before_lang to extract uploader_name, channel_id, and title
                # The channel_id (UC...) is a strong anchor to split around.
                match_channel_id_and_rest = re.search(r'(UC[a-zA-Z0-9_-]+)\.(.*)$', content_before_lang)

                if match_channel_id_and_rest:
                    channel_id_raw = match_channel_id_and_rest.group(1)
                    # The part before channel_id is uploader_name/playlist_name
                    uploader_or_playlist_raw = content_before_lang[:match_channel_id_and_rest.start() - 1] # -1 to remove the dot before UC
                    # The part after channel_id is title
                    title_raw = match_channel_id_and_rest.group(2)

                    # Sanitize extracted parts, preserving spaces as requested
                    uploader_or_playlist_clean = sanitize_filename(uploader_or_playlist_raw)
                    channel_id_clean = sanitize_filename(channel_id_raw) # Should already be clean
                    title_clean = sanitize_filename(title_raw)

                    # Construct folder name: channel_id.uploader_or_playlist_name
                    # This will create folders like UC... .Puma Finanzas - Live
                    folder_name = f"{channel_id_clean}.{uploader_or_playlist_clean}"

                    # Construct final filename
                    final_filename_parts = [
                        f"({upload_date})",
                        f"[{video_id}]",
                        uploader_or_playlist_clean,
                        channel_id_clean,
                        title_clean,
                        lang,
                        'cleaned',
                        'vtt'
                    ]
                    final_filename = '.'.join(filter(None, final_filename_parts))

                    destination_folder = os.path.join(destination_base_dir, folder_name)
                    destination_filepath = os.path.join(destination_folder, final_filename)

                    # Create destination folder if it doesn't exist
                    os.makedirs(destination_folder, exist_ok=True)

                    # Move the file
                    try:
                        shutil.move(source_filepath, destination_filepath)
                        print(f"Moved '{filename}' to '{destination_filepath}'")
                        processed_count += 1
                    except shutil.Error as e:
                        print(f"Error moving '{filename}': {e}")
                    except Exception as e:
                        print(f"An unexpected error occurred while moving '{filename}': {e}")
                else:
                    print(f"Skipping '{filename}': Could not find channel ID (UC...) pattern in content part. Content: '{content_before_lang}'")
                    skipped_count += 1
            else:
                print(f"Skipping '{filename}': Does not match initial filename pattern. Filename: {filename}")
                skipped_count += 1
        else:
            print(f"Skipping '{filename}': Not a .vtt file. Filename: {filename}")
            skipped_count += 1

    print(f"Organization complete. Total files processed: {processed_count}, Total files skipped: {skipped_count}")

if __name__ == '__main__':
    # Define the source flat directory and the destination base directory
    source_flat_directory = '/home/reikoku/Build From Source/Gemini Taylor/YtSubtitlesMissions/subtitles/All subtitles transcripts'
    destination_base_directory = '/home/reikoku/Build From Source/Gemini Taylor/YtSubtitlesMissions/subtitles'
    
    organize_vtt_from_flat(source_flat_directory, destination_base_directory)