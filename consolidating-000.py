import os
import re
import shutil

def consolidate_subtitle_folders(base_dir):
    print(f"Starting consolidation in: {base_dir}")
    
    # Get all items in the base directory
    items = os.listdir(base_dir)
    
    for item in items:
        original_folder_path = os.path.join(base_dir, item)
        
        # Process only directories that start with 'UC' and are not excluded
        if os.path.isdir(original_folder_path) and item.startswith('UC') and \
           item not in ['Distilling Intel', 'temp_subtitles']:
            
            # Extract channel_id.uploader_id from the folder name
            # This assumes the format UC...id.uploader_id.playlist_name or UC...id.uploader_id
            parts = item.split('.')
            if len(parts) >= 2:
                channel_id_uploader_id = f"{parts[0]}.{parts[1]}"
                
                new_parent_folder_path = os.path.join(base_dir, channel_id_uploader_id)
                
                # Create the new parent folder if it doesn't exist
                if not os.path.exists(new_parent_folder_path):
                    os.makedirs(new_parent_folder_path)
                    print(f"Created new parent folder: {new_parent_folder_path}")
                
                # Move the original folder into the new parent folder
                try:
                    shutil.move(original_folder_path, new_parent_folder_path)
                    print(f"Moved '{item}' to '{new_parent_folder_path}'")
                except shutil.Error as e:
                    print(f"Error moving '{item}': {e}")
                except Exception as e:
                    print(f"An unexpected error occurred while moving '{item}': {e}")
            else:
                print(f"Skipping '{item}': Does not match expected naming convention for consolidation.")
        elif os.path.isdir(original_folder_path):
            print(f"Skipping non-UC folder or excluded folder: '{item}'")

    print("Consolidation complete.")

if __name__ == '__main__':
    # Define the base directory for your subtitles
    subtitles_base_directory = '/home/reikoku/Build From Source/Gemini Taylor/YtSubtitlesMissions/subtitles'
    consolidate_subtitle_folders(subtitles_base_directory)
