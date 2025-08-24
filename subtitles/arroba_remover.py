import os

def remove_arroba_from_names(start_path):
    """
    Removes the '@' symbol from folder names and filenames
    within the specified starting path.
    """
    print(f"Starting to remove '@' from names in: {start_path}")

    # Walk through the directory tree from the bottom up
    # This ensures files are renamed before their parent directories,
    # preventing issues with paths changing during traversal.
    for dirpath, dirnames, filenames in os.walk(start_path, topdown=False):
        # Rename files first
        for name in filenames:
            if '@' in name:
                old_path = os.path.join(dirpath, name)
                new_name = name.replace('@', '')
                new_path = os.path.join(dirpath, new_name)
                try:
                    os.rename(old_path, new_path)
                    print(f"Renamed file: '{old_path}' to '{new_path}'")
                except OSError as e:
                    print(f"Error renaming file '{old_path}': {e}")

        # Rename directories
        # We need to iterate over a copy of dirnames because we might modify it
        for name in list(dirnames):
            if '@' in name:
                old_path = os.path.join(dirpath, name)
                new_name = name.replace('@', '')
                new_path = os.path.join(dirpath, new_name)
                try:
                    os.rename(old_path, new_path)
                    print(f"Renamed directory: '{old_path}' to '{new_path}'")
                    # Update dirnames in place so os.walk continues correctly
                    dirnames[dirnames.index(name)] = new_name
                except OSError as e:
                    print(f"Error renaming directory '{old_path}': {e}")

    print("Finished processing.")

if __name__ == "__main__":
    current_directory = "/home/reikoku/Build From Source/Gemini Taylor/YtSubtitlesMissions/subtitles"
    remove_arroba_from_names(current_directory)
