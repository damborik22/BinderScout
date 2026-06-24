import re

def seq_count_fa(fasta):
    """Count number of sequrnces in fasta file."""
    with open(fasta, 'r') as f:
        i = 0
        regex = re.compile('^s*>')
        for line in f:
            if re.search(regex, line):
                i += 1
    return i