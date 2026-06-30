
import os


def get_abs_path(script_path, rel_path):
    """
    Create absolute path from path relative to the calling script.
    """
    source_path = os.path.realpath(script_path)
    source_path = os.path.dirname(source_path)
    joined_path = os.path.join(source_path, rel_path)

    return os.path.realpath(joined_path)

