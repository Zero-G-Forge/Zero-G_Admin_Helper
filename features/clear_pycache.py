# clear_pycache.py

import os
import shutil

def clear_pycache(directory=None):
    """
    Recursively discovers and removes all __pycache__ bytecode directories
    starting from the project root.
    """
    if directory is None:
        # Dynamically resolve root project directory
        directory = os.path.dirname(os.path.abspath(__file__))

    removed_count = 0
    for root, dirs, files in os.walk(directory):
        if '__pycache__' in dirs:
            pycache_path = os.path.join(root, '__pycache__')
            try:
                shutil.rmtree(pycache_path)
                dirs.remove('__pycache__')
                removed_count += 1
            except Exception as e:
                print(f"[WARNING] Could not remove {pycache_path}: {e}")

    print(f"[SUCCESS] Cleared {removed_count} __pycache__ directories.")

if __name__ == "__main__":# Clear pycache
    root_directory = os.path.dirname(os.path.abspath(__file__))
    clear_pycache(root_directory)

print("[SUCCESS] All pycache directories have been removed.")