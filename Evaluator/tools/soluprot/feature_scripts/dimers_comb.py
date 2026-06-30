#!/usr/bin/env python3
import csv
from Bio import SeqIO
import argparse
from tqdm import tqdm
from common.seq_count_fa import seq_count_fa
from itertools import combinations_with_replacement


class DimerComb:

    AA = "ACDEFGHIKLMNPQRSTVWY"

    def __init__(self):
        self.combs = []
        for c in combinations_with_replacement(DimerComb.AA, 2):
            self.combs.append(''.join(c))

    def get_comb_ratio(self, sequence):

        dimers = dict.fromkeys(self.combs, 0)
        dim = sequence[0:1]
        for j in range(1, len(sequence)):
            dim += sequence[j]
            comb = dim
            reflect_dim = dim[::-1]
            if reflect_dim in dimers:
                comb = reflect_dim
            if comb in dimers:
                dimers[comb] += 1
            dim = sequence[j]

        # normalizing
        dimers.update((comb, count/(len(sequence)-1)) for comb, count in
                      dimers.items())

        return dimers


def compute_comb(fasta, o_csv, round_to=4):
    fa = SeqIO.parse(fasta, format="fasta")
    dim = DimerComb()
    with open(o_csv, 'w') as f:
        csv_out = csv.DictWriter(f, fieldnames=["sid"] + dim.combs)
        csv_out.writeheader()
        seq_count = seq_count_fa(fasta)
        for record in tqdm(fa, total=seq_count):
            seq = str(record.seq)
            row = dim.get_comb_ratio(seq)
            row.update((comb, round(ratio, round_to)) for comb, ratio in
                        row.items())
            row["sid"] = record.id
            csv_out.writerow(row)


def main():
    args = arguments()
    compute_comb(args.i_fa, args.o_csv)


def arguments():

    parser = argparse.ArgumentParser(description="Tool for computing "
                                                 "frequencies of dimer "
                                                 "combinations")
    parser.add_argument('--i_fa', help="Input file in fasta format",
                        required=True)
    parser.add_argument('--o_csv', help="Name of output file", required=True)
    args = parser.parse_args()

    return args


if __name__ == '__main__':
    main()
