import os
import hashlib
import argparse
import shutil

def calculate_file_hash(filepath, hash_algorithm='md5', block_size=65536):
    """
    Calculates the hash of a file's content.
    """
    hasher = hashlib.new(hash_algorithm)
    try:
        with open(filepath, 'rb') as f:
            for block in iter(lambda: f.read(block_size), b''):
                hasher.update(block)
        return hasher.hexdigest()
    except FileNotFoundError:
        print(f"Warning: File not found during hash calculation: {filepath}")
        return None
    except Exception as e:
        print(f"Error calculating hash for {filepath}: {e}")
        return None

def deduplicate_vtt_files_safe(base_dir, dry_run=True):
    print(f"Starting safe deduplication in: {base_dir}")
    if dry_run:
        print("*** DRY RUN MODE: No files will be moved. ***")

    quarantine_dir = os.path.join(base_dir, "deduplicated_vtt_quarantine")
    if not os.path.exists(quarantine_dir) and not dry_run:
        os.makedirs(quarantine_dir)
        print(f"Created quarantine directory: {quarantine_dir}")

    # Dictionary to store file hashes and their paths
    # {hash: set(filepath1, filepath2, ...)} - using a set to ensure unique paths
    hashes = {}
    # Set to store unique file identifiers (inode, device) to avoid processing the same physical file multiple times
    processed_file_ids = set()
    
    # Walk through the directory tree
    for dirpath, _, filenames in os.walk(base_dir):
        for filename in filenames:
            if filename.endswith('.vtt'):
                filepath = os.path.join(dirpath, filename)
                
                try:
                    # Get file's unique identifier (inode and device)
                    stat_info = os.stat(filepath)
                    file_id = (stat_info.st_ino, stat_info.st_dev)

                    if file_id in processed_file_ids:
                        # This physical file has already been processed, skip it
                        # This handles cases where os.walk might yield the same file via different paths (e.g., hard links)
                        # or if there's an anomaly causing the same path string to be yielded multiple times.
                        # print(f"DEBUG: Skipping already processed physical file: {filepath}") # Uncomment for more verbose debug
                        continue
                    
                    processed_file_ids.add(file_id)

                    # Normalize the path to ensure consistent representation for storage
                    normalized_filepath = os.path.realpath(filepath)
                    
                    file_hash = calculate_file_hash(normalized_filepath)
                    if file_hash:
                        if file_hash in hashes:
                            hashes[file_hash].add(normalized_filepath)
                        else:
                            hashes[file_hash] = {normalized_filepath}
                except FileNotFoundError:
                    print(f"Warning: File not found during scan: {filepath}")
                except Exception as e:
                    print(f"Error processing file {filepath}: {e}")

    # Process duplicates
    moved_count = 0
    for file_hash, filepaths_set in hashes.items():
        # Convert set to list for consistent ordering (though not guaranteed)
        filepaths = list(filepaths_set)
        
        # Debugging prints (can be removed after verification)
        # print(f"\nDEBUG: Processing hash {file_hash}")
        # print(f"DEBUG: filepaths_set (raw set): {filepaths_set}")
        # for fp in filepaths_set:
        #     print(f"DEBUG:   - repr(fp): {repr(fp)}, id(fp): {id(fp)}")

        if len(filepaths) > 1:
            print(f"\nFound {len(filepaths)} duplicates for hash {file_hash}:")
            print(f"  Keeping: {filepaths[0]}") # Always keep the first encountered
            
            files_to_move = filepaths[1:] # Files to move to quarantine
            for filepath_to_move in files_to_move:
                # Construct new path in quarantine directory
                # Use os.path.basename to get just the filename, then join with quarantine_dir
                destination_path = os.path.join(quarantine_dir, os.path.basename(filepath_to_move))
                
                # If a file with the same name already exists in quarantine, append a number
                counter = 1
                original_destination_path = destination_path
                while os.path.exists(destination_path) and not dry_run:
                    name, ext = os.path.splitext(original_destination_path)
                    destination_path = f"{name}_{counter}{ext}"
                    counter += 1

                if dry_run:
                    print(f"  [DRY RUN] Would move: {filepath_to_move} to {destination_path}")
                    moved_count += 1 # <--- ADDED THIS LINE
                else:
                    try:
                        shutil.move(filepath_to_move, destination_path)
                        print(f"  Moved: {filepath_to_move} to {destination_path}")
                        moved_count += 1
                    except Exception as e:
                        print(f"  Error moving {filepath_to_move}: {e}")

    print(f"\nSafe deduplication complete. {'(Dry Run)' if dry_run else ''}")
    print(f"Total files {'would be ' if dry_run else ''}moved to quarantine: {moved_count}")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Safely find and move duplicate .vtt files based on content hash to a quarantine folder.')
    parser.add_argument('--base-dir', type=str, default='/home/reikoku/Build From Source/Gemini Taylor/YtSubtitlesMissions/subtitles', help='Base directory to search for .vtt files.')
    parser.add_argument('--dry-run', action='store_true', help='If set, no files will be moved, only reported.')

    args = parser.parse_args()

    deduplicate_vtt_files_safe(args.base_dir, args.dry_run)