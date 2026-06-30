#!/usr/bin/env python3
import argparse
from tqdm import tqdm
from Bio.SeqUtils import ProtParam
from Bio import SeqIO
import numpy as np
import csv


# Kyte & Doolittle index of hydrophobicity
kd = {'A':  1.8, 'R': -4.5, 'N': -3.5, 'D': -3.5, 'C':  2.5,
      'Q': -3.5, 'E': -3.5, 'G': -0.4, 'H': -3.2, 'I':  4.5,
      'L':  3.8, 'K': -3.9, 'M':  1.9, 'F':  2.8, 'P': -1.6,
      'S': -0.8, 'T': -0.7, 'W': -0.9, 'Y': -1.3, 'V':  4.2}


def check_seq(seq):
    for aa in seq:
        if aa not in "ACDEFGHIKLMNPQRSTVWY":
            return False
    return True


def fracnumcharge(aa_freq):
    return aa_freq['R'] + aa_freq['K'] + aa_freq['D'] + aa_freq['E']


def thermostability(aa_freq):
    return aa_freq['I'] + aa_freq['V'] + aa_freq['Y'] + aa_freq['W'] + \
           aa_freq['R'] + aa_freq['E'] + aa_freq['L']


def kr_ratio(aa_freq):
    if aa_freq['R'] == 0:
        return np.nan
    else:
        return aa_freq['K']/aa_freq['R']


def de_mul(aa_freq):
    return aa_freq['D']*aa_freq['E']


def physico_chemical(fa_path, f_csv):
    features = {"sid":[],
                "fracnumcharge": [], "thermostability":[], "kr_ratio":[],
                "de_mul":[], "aa_helix": [], "aa_sheet":[], "aa_turn": [],
                "molecular_weight": [], "length": [],
                'avg_molecular_weight': [], "aromaticity": [],
                "instability_index": [], "flexibility": [],
                "gravy": [], "isoelectric_point": [],
                "hydrophobicity6": [], "hydrophobicity6e": [],
                "hydrophobicity2": []}
    with open(f_csv, "w") as csv_out:
        csv_wr = csv.DictWriter(csv_out, fieldnames=features)
        csv_wr.writeheader()
        for seq in tqdm(SeqIO.parse(fa_path, "fasta")):
            if not check_seq(seq.seq):
                continue
            row = dict.fromkeys(features)
            row['sid'] = seq.id
            analysis = ProtParam.ProteinAnalysis(str(seq.seq))
            aa_freq = analysis.get_amino_acids_percent()
            row['fracnumcharge'] = fracnumcharge(aa_freq)
            row['thermostability'] = thermostability(aa_freq)
            row['kr_ratio'] = kr_ratio(aa_freq)
            row['de_mul'] = de_mul(aa_freq)
            row['molecular_weight'] = analysis.molecular_weight()
            row['length'] = analysis.length
            row['avg_molecular_weight'] = row['molecular_weight']/row['length']
            row['aromaticity'] = analysis.aromaticity()
            row['instability_index'] = analysis.instability_index()
            row['flexibility'] = np.mean(analysis.flexibility())
            row['gravy'] = analysis.gravy()
            row['isoelectric_point'] = analysis.isoelectric_point()
            h, s, t = analysis.secondary_structure_fraction()
            row["aa_helix"] = h
            row["aa_sheet"] = s
            row["aa_turn"] = t
            h6 = np.mean(analysis.protein_scale(kd, 6))
            row['hydrophobicity6'] = h6
            h6e = np.mean(analysis.protein_scale(kd, 6,edge=0.1))
            row['hydrophobicity6e'] = h6e
            h2 = np.mean(analysis.protein_scale(kd, 2))
            row['hydrophobicity2'] = h2
            csv_wr.writerow(row)


def arguments():
    parser = argparse.ArgumentParser(description="Compute basic "
                                                 "physico-chemical features.")
    parser.add_argument('--i_fa', help="Input file in fasta format",
                        required=True, type=str)
    parser.add_argument('--o_csv', help="Output csv file with features",
                        required=True,type=str)
    args = parser.parse_args()

    return args


def main():
    args = arguments()
    physico_chemical(args.i_fa, args.o_csv)


if __name__ == '__main__':
    main()