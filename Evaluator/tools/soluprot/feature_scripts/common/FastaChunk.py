from Bio import SeqIO
from itertools import islice

class FastaChunk:

    """Split fasta file into chunks."""
    def __init__(self, chunk_size, fasta):
        self._chunk_size = chunk_size
        self._fasta = SeqIO.parse(fasta, format="fasta")

    def __iter__(self):
        return self

    def __next__(self):
        chunk = list(islice(self._fasta, self._chunk_size))
        if len(chunk) == 0:
            raise StopIteration
        return chunk
