#!/usr/bin/env python3

import csv
from Bio import SeqIO
import argparse
from itertools import product
from collections import OrderedDict
from tqdm import tqdm
from common.seq_count_fa import seq_count_fa

class KMerF:

    AA = "ACDEFGHIKLMNPQRSTVWY"

    def __init__(self, n, product=None, alphabet=AA):
        """
        :param n: level of k-mer, e.g. monomer, dimer..
        """
        self.alphabet = alphabet
        assert n > 0
        self._n = n
        if product is None:
            self.product = self.get_product()
        else:
            self.product = product

    def get_cols(self):
        return list(self.product.keys())

    def get_product(self):
        """
        :return: Sorted dictionary with all possible permutations (with
        repetition) of alphabet.
        """
        return OrderedDict(sorted(
            {''.join(i): 0 for i in product(self.alphabet, repeat=self._n)}.items()))

    def frequency(self, sequence, step=1):
        """
        Count "frequency" of k_mers in sequence - their occurrence divided by
        count of k_mers. For monomers count is length of sequence.
        :param sequence: sequence in given alphabet
        :return: dictionary key:k-mer value:frequency
        """
        assert step >= 1
        assert len(sequence) % step == 0
        assert self._n <= len(sequence)
        # count of k-mers in given sequence
        if step == 1:
            count_mers = len(sequence) - self._n + 1
        else:
            count_mers = len(sequence)/step

        product = self.product.copy()
        sequence = sequence.upper()
        # counting frequencies
        window = sequence[:self._n]
        if window in product:
            product[window] += 1
        for i in range(step, len(sequence), step):
            window = window[step:] + sequence[i:i+step]
            if window in product:
                product[window] += 1
        # dividing by k-mers count and rounding results
        product.update({key: round(value/count_mers, 4) for key, value in
                        product.items()})

        return product

    def compute_freq(self, fasta, output):
        """
        Compute frequencies of k-mers of sequences in fasta file.
        :param fasta: name of input fasta file
        :param output: name of output csv
        """
        fa = SeqIO.parse(fasta, format="fasta")
        with open(output, 'w') as f:
            csv_out = csv.writer(f)
            csv_out.writerow(['sid']+list(self.product.keys()))
            seq_count = seq_count_fa(fasta)
            for record in tqdm(fa, total=seq_count):
                seq = str(record.seq)
                csv_out.writerow([record.id] + list(self.frequency(
                    seq).values()))


def main():
    args = arguments()
    xmerf = KMerF(args.k)
    xmerf.compute_freq(args.i_fa, args.o_csv)


def arguments():

    parser = argparse.ArgumentParser(description="Tool for computing "
                                                 "frequencies of k-mers in "
                                                 "sequence. ")
    parser.add_argument('--i_fa', help="Input file in fasta format",
                        required=True)
    parser.add_argument('--o_csv', help="Name of output file", required=True)
    parser.add_argument('-k', help="Level of mer e.g. k=1 => monomers, k=2 => "
                                   "dimers", required=True,
                        type=int)
    args = parser.parse_args()

    return args


if __name__ == '__main__':
    main()
