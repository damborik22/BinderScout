from os import listdir
from os import remove
from os.path import isfile
from os.path import isdir
from shutil import rmtree

def clear_dir(path):
    """Clear content of directory, but do not remove directory itself."""
    for item in listdir(path):
        if isfile(item):
            remove(item)
        elif isdir(item):
            rmtree(item)