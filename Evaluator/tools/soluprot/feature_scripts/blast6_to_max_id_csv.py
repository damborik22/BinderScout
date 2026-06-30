#!/usr/bin/env python3
import argparse
import pandas as pd
import numpy as np


def process_blast6(blast6, id_col, chosen):
    names = ("query", "target", "identity", "alignment_length",
             "number_of_mismatches", "number_of_gap_opens",
             "start_position_in_query",  "end_position_in_query",
             "start_position_in_target", "end_position_in_target",
             "e-value", "bit_score")
    b6 = pd.read_csv(blast6, names=names, sep="\t")
    if chosen not in b6.columns:
        raise ValueError("Column not in blast6 format.")
    b6 = b6.groupby("query")[[chosen]].max().reset_index()
    if chosen == "identity":
        b6[chosen] = round(b6[chosen]/100, 3)
    b6.rename(columns={"query": id_col}, inplace=True)
    return b6


def main():
    args = arguments()
    b6_csv = process_blast6(args.i_blast6, args.id, args.chosen)
    seq = pd.read_csv(args.i_seq)
    # add 0 identity to sequences with no result in blast6 format
    b6_csv = pd.merge(seq[[args.id]], b6_csv, how="left")
    condition = b6_csv[args.chosen].isnull()
    b6_csv[args.chosen] = np.where(condition, 0.0, b6_csv[args.chosen])
    b6_csv.to_csv(args.o_iden, index=False)


def arguments():
    parser = argparse.ArgumentParser(description="Extract max identity from "
                                                 "blast6 format")
    parser.add_argument('--i_blast6', help="Blast6 file.",
                        type=str)
    parser.add_argument('--o_iden', help="Output file with identity.",
                        type=str, default="tt_identity.csv")
    parser.add_argument('--i_seq', help="Sequences (csv).",
                        type=str)
    parser.add_argument('--id', help="Name of sequence_id column",
                        type=str,
                        default="sequence_id")
    parser.add_argument('--chosen', default="identity", type=str)
    args = parser.parse_args()
    return args


if __name__ == '__main__':
    main()
