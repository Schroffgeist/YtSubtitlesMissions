
import os
import re

def update_archive():
    """
    Updates the yt-dlp archive file to be in sync with the .vtt files.
    """
    subtitles_dir = "/home/reikoku/Build From Source/Gemini Taylor/YtSubtitlesMissions/subtitles"
    archive_path = os.path.join(subtitles_dir, "ytdl-archive.txt")

    # 1. Get video IDs from .vtt files
    vtt_files = []
    for root, _, files in os.walk(subtitles_dir):
        for file in files:
            if file.endswith(".vtt"):
                vtt_files.append(os.path.join(root, file))

    print(f"Found {len(vtt_files)} .vtt files.")
    print("-" * 30)
    print("Extracting and printing video IDs...")

    vtt_ids = set()
    regex = r'\(\d{8}\)\.\[([a-zA-Z0-9_-]{11})\s*'

    for vtt_file in vtt_files:
        match = re.search(regex, vtt_file)
        if match:
            video_id = match.group(1)
            vtt_ids.add(video_id)
            print(f"- {os.path.basename(vtt_file)} -> {video_id}")
        else:
            print(f"- {os.path.basename(vtt_file)} -> NOT FOUND")

    print("-" * 30)
    print(f"Found {len(vtt_ids)} unique video IDs.")

    # 2. Generate the new archive content
    new_archive_content = ""
    for video_id in sorted(list(vtt_ids)):
        new_archive_content += f"youtube {video_id}\n"

    # 3. Write the new content to the archive file
    with open(archive_path, 'w') as f:
        f.write(new_archive_content)
    
    print(f"\nSuccessfully updated ytdl-archive.txt with {len(vtt_ids)} entries.")

if __name__ == "__main__":
    update_archive()
