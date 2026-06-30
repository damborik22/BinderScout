#!/usr/bin/env python3
from Bio import SeqIO
from Bio.SeqUtils import ProtParam
from Bio.Seq import Seq
from Bio.SeqIO import FastaIO
from sklearn.externals import joblib
import argparse
import subprocess as sb
import pandas as pd
import numpy as np
import sys
import os
import shutil

from feature_scripts.common.get_abs_path import get_abs_path

# for loading other modules inside directory feature_scripts
sys.path.insert(1, get_abs_path(__file__, './feature_scripts'))
sys.path.insert(1, get_abs_path(__file__, './data'))

from feature_scripts.dimers_comb import DimerComb
from feature_scripts.common.prefix import set_df_prefix
from feature_scripts.physico_chemical import fracnumcharge, kr_ratio
from feature_scripts.blast6_to_max_id_csv import process_blast6
from data.RandomForestModel import RandomForestModel
from data.GradientBoostingClassifierWrapper import GradientBoostingClassifierWrapper

AA = "ACDEFGHIKLMNPQRSTVWY"

class Paths:
    """
    Relative paths of additional tools to SoluProt script
    """
    _SCRIPT = __file__
    _MODEL = './data/grad_clf_v1_tc.pkl'
    _MODEL_NO_TMHMM = './data/grad_clf_v1_tc_notmhmm.pkl'
    _USEARCH = None
    _PDB_ECOLI_FA = './data/Ecoli_xray_nmr_pdb_no_nesg.fa'
    _TMHMM = None

    @staticmethod
    def _get_abs_path(rel_path):
        return get_abs_path(Paths._SCRIPT, rel_path)

    @staticmethod
    def get_and_check_command(cmd, alt_path, exp):
        if alt_path:
            return Paths.get_and_check_abs_file_path(alt_path, exp)
        cmd_path = shutil.which(cmd)
        if cmd_path:
            return cmd_path
        raise exp

    @staticmethod
    def get_and_check_abs_file_path(rel_path, exp):
        abs_path = get_abs_path(Paths._SCRIPT, rel_path)
        if not os.path.exists(abs_path) or os.path.isdir(abs_path):
            raise exp
        return abs_path

    @staticmethod
    def model():
        return Paths.get_and_check_abs_file_path(Paths._MODEL,
                                                 ModelInvalidPath())

    @staticmethod
    def usearch():
        return Paths.get_and_check_command("usearch", Paths._USEARCH,
                                           UsearchInvalidPath())

    @staticmethod
    def pdb_db():
        return Paths.get_and_check_abs_file_path(Paths._PDB_ECOLI_FA,
                                                 PdbDatabaseNotFound())

    @staticmethod
    def tmhmm():
        return Paths.get_and_check_command("tmhmm", Paths._TMHMM,
                                           TmhmmInvalidPath())

class InvalidAlphabet(Exception):
    pass

class ShortSequence(Exception):
    pass

class DuplicatedSid(Exception):
    pass

class UsearchInvalidPath(Exception):
    pass

class UsearchExcecutionFailed(Exception):
    pass

class PdbDatabaseNotFound(Exception):
    pass

class TmhmmInvalidPath(Exception):
    pass

class TmhmmExecutionFailed(Exception):
    pass

class TmhmmParsingError(Exception):
    pass

class ModelInvalidPath(Exception):
    pass

class ModelIsNotCompatible(Exception):
    pass

class MissingModelFeatures(Exception):
    pass

class Predictor:

    _PRE_MONOMERS = "monomers"
    _PRE_DIMERS = "dimers_comb"
    _PRE_PHYSICO_CHEM = "physico_chemical"
    _PRE_IDENTITY = "ecoli_usearch_identity"
    _PRE_TMHMM = "tmhmm"

    _MIN_SEQ_LENGTH = 20

    def __init__(self, fasta_file, tmp_dir, no_tmhmm, model_path, usearch, pdb_db,
                 tmhmm, usearch_threads=1, check_unknown=True):

        try:
            self.model = joblib.load(model_path)
        except AttributeError:
            raise ModelIsNotCompatible()

        fasta_parser = SeqIO.parse(fasta_file, "fasta")
        fa_id = []
        sequences = []
        for record in fasta_parser:
            fa_id.append(record.id)
            seq = str(record.seq)
            new_seq = ""
            for aa in seq:
                if aa not in AA:
                    if check_unknown:
                        raise InvalidAlphabet()
                else:
                    new_seq += aa
            seq = new_seq
            if len(seq) < Predictor._MIN_SEQ_LENGTH:
                raise ShortSequence()
            sequences.append(seq)

        self.seq = pd.DataFrame({"sequence": sequences, "fa_id": fa_id},
                                index=range(len(sequences)))
        self.seq.index = self.seq.index.astype(str)
        self.seq.index.name = "sid"
        if self.seq.index.nunique() != self.seq.index.shape[0]:
            raise DuplicatedSid()
        self.features = pd.DataFrame(index=self.seq.index)

        # other arguments
        self.tmp_dir = os.path.abspath(tmp_dir)
        if not os.path.exists(self.tmp_dir):
            os.mkdir(self.tmp_dir)
        self.fasta_path = None
        self.usearch_threads = usearch_threads
        self.usearch = usearch
        self.pdb_db = pdb_db
        self.tmhmm = tmhmm
        self.no_tmhmm = no_tmhmm

    def file_path(self, file_name):
        return os.path.join(self.tmp_dir, file_name)

    def compute_features(self):
        """Computing features"""
        self.create_fasta("query.fa")
        self._add_monomers()
        self._add_dimers()
        self._add_physico_chemical()
        if not self.no_tmhmm:
            self._add_tmhmm()
        self._add_usearch_identity()

    def predict(self, round_to=4):
        """Prediction"""
        if len(self.features.columns) != len(self.model.order):
            raise MissingModelFeatures()
        is_null = self.features.isnull().any(axis=1)
        null_features = self.features[is_null]
        for index, row in null_features.iterrows():
            for col in null_features.columns:
                if pd.isnull(row[col]):
                    print("Warning: feature {f} can not be calculated for "
                          "sequence with id {id}, mean of training set will be "
                          "used.".format(f=col, id=index), file=sys.stderr)
                    self.features.at[index, col] = self.model.features_mean[col]

        pred = self.model.predict(self.features)
        pred = np.round(pred, round_to)
        pred = np.where(pred < 0, 0, pred)
        pred = np.where(pred > 1, 1, pred)
        results = pd.DataFrame({"soluble":pred}, index=self.features.index)
        results = results.join(self.seq["fa_id"])
        results.index.name = "runtime_id"
        return results[["fa_id", "soluble"]]

    def _join(self, feature: pd.DataFrame, prefix):
        feature.index = feature.index.astype(str)
        set_df_prefix(feature, prefix)
        cols = feature.columns[feature.columns.isin(self.model.order)]
        feature = feature[cols]
        self.features = self.features.join(feature, how="left")

    def _add_monomers(self):
        """Monomers"""
        print("Computing monomers")
        monomers = pd.DataFrame(index=self.features.index, columns=list(AA))
        for index, row in self.seq.iterrows():
            analysis = ProtParam.ProteinAnalysis(row["sequence"])
            aa_freq = analysis.get_amino_acids_percent()
            monomers.loc[index] = aa_freq
        self._join(monomers, Predictor._PRE_MONOMERS)

    def _add_dimers(self):
        """Dimers"""
        print("Computing dimers")
        dim = DimerComb()
        dimers_comb = pd.DataFrame(index=self.features.index, columns=dim.combs)
        for index, row in self.seq.iterrows():
            dimers_comb.loc[index] = dim.get_comb_ratio(row["sequence"])
        self._join(dimers_comb, Predictor._PRE_DIMERS)

    def _add_physico_chemical(self):
        """Physico-chemical features"""
        print("Computing physico-chemical features")
        cols = ["fracnumcharge", "kr_ratio", "aa_helix", "aa_sheet",
                "aa_turn", "molecular_weight", "aromaticity",
                "avg_molecular_weight", "flexibility", "gravy",
                "isoelectric_point", "instability_index"]
        physico_chem = pd.DataFrame(index=self.features.index, columns=cols)
        for index, row in self.seq.iterrows():
            pc_row = dict.fromkeys(cols, np.nan)
            analysis = ProtParam.ProteinAnalysis(row["sequence"])
            aa_freq = analysis.get_amino_acids_percent()
            pc_row["fracnumcharge"] = fracnumcharge(aa_freq)
            pc_row["kr_ratio"] = kr_ratio(aa_freq)
            h, s, t = analysis.secondary_structure_fraction()
            pc_row["aa_helix"] = h
            pc_row["aa_sheet"] = s
            pc_row["aa_turn"] = t
            pc_row['molecular_weight'] = analysis.molecular_weight()
            pc_row['length'] = analysis.length
            pc_row['avg_molecular_weight'] = pc_row['molecular_weight']/pc_row['length']
            pc_row['aromaticity'] = analysis.aromaticity()
            pc_row['flexibility'] = np.mean(analysis.flexibility())
            pc_row['gravy'] = analysis.gravy()
            pc_row['isoelectric_point'] = analysis.isoelectric_point()
            pc_row['instability_index'] = analysis.instability_index()

            physico_chem.loc[index] = pc_row
        self._join(physico_chem, Predictor._PRE_PHYSICO_CHEM)

    def _add_usearch_identity(self, b6="identity.b6"):
        """Identity"""
        print("Computing identity")
        b6_path = self.file_path(b6)
        check_remove_file(b6_path)
        usearch_arguments = ['-usearch_global', self.fasta_path,
                             '-db', self.pdb_db, '-id', '0.0', '-blast6out',
                             b6_path, '-threads', str(self.usearch_threads),
                             '-top_hits_only']
        try:
            sb.run([self.usearch] + usearch_arguments, check=True,
                   stdout=sb.DEVNULL)
        except sb.CalledProcessError:
            raise UsearchExcecutionFailed()
        if not os.path.exists(b6_path):
            raise UsearchExcecutionFailed()
        identity = process_blast6(b6_path, "sid", "identity")
        identity.set_index('sid', inplace=True)
        self._join(identity, Predictor._PRE_IDENTITY)

    def _add_tmhmm(self, tmhmm="tmhmm.tmhmm"):
        """Transmembrane regions"""
        print("Computing transmembrane regions")
        tmhmm_path = self.file_path(tmhmm)
        check_remove_file(tmhmm_path)
        try:
            with open(tmhmm_path, "w") as tm_f:
                sb.run([self.tmhmm, self.fasta_path, '-noplot', '-short'], check=True, stdout=tm_f)
        except sb.CalledProcessError:
            raise TmhmmExecutionFailed()
        if not os.path.exists(tmhmm_path):
            raise TmhmmExecutionFailed()
        tm_df = tmhmm_to_df(tmhmm_path, "sid")
        tm_df.set_index('sid', inplace=True)
        self._join(tm_df, Predictor._PRE_TMHMM)

    def create_fasta(self, file_name):
        """Creating FASTA with internal mapping - runtime id"""
        file_path = self.file_path(file_name)
        with open(file_path, "w") as f_fasta:
            fasta_wr = FastaIO.FastaWriter(f_fasta, wrap=None)
            fasta_wr.write_header()  # does nothing, but is required
            for index, row in self.seq.iterrows():
                record = SeqIO.SeqRecord(
                    seq=Seq(row["sequence"]),
                    id=str(index), description='')
                fasta_wr.write_record(record)
            fasta_wr.write_footer()  # does nothing, but is required
        self.fasta_path = file_path


def check_remove_file(file_path):
    if os.path.exists(file_path):
        os.remove(file_path)


def tmhmm_to_df(tmhmm_path, id_col):
    """Processing TMHMM results"""
    F_COUNT = 5
    df_dict = {id_col: [], "len": [], "ExpAA": [], "First60": [],
               "PredHel": [], "Topology": []}
    with open(tmhmm_path, "r") as tm_f:
        for line in tm_f:
            line = line.rstrip()
            values = line.split('\t')
            seq_id, features = values[0], values[1:]
            df_dict[id_col].append(seq_id)
            for f in features:
                key, val = f.split('=')
                df_dict[key].append(val)
            if len(features) != F_COUNT:
                raise TmhmmParsingError()
    df = pd.DataFrame(df_dict)
    df.rename(columns={"ExpAA": "exp_aa", "First60": "first_60",
                       "PredHel": "pred_hel", "Topology": "topology"},
              inplace=True)
    return df


def main():
    args = arguments()
    if not os.path.isfile(args.i_fa):
        print("Invalid path to input FASTA file.", file=sys.stderr)
        return 1

    if args.model is not None:
        # Model specified as cmdline parameter
        Paths._MODEL = args.model
    elif args.no_tmhmm:
        # Use model without TMHMM features
        Paths._MODEL = Paths._MODEL_NO_TMHMM

    Paths._USEARCH = args.usearch
    Paths._TMHMM = args.tmhmm
    Paths._PDB = args.pdb

    try:
        tmhmm_path = None
        if not args.no_tmhmm:
            # Use TMHMM, so check TMHMM path
            tmhmm_path = Paths.tmhmm()

        pred = Predictor(args.i_fa, args.tmp_dir, no_tmhmm=args.no_tmhmm, model_path=Paths.model(),
                       usearch=Paths.usearch(), tmhmm=tmhmm_path,
                       pdb_db=Paths.pdb_db(), check_unknown=args.check_unknown,
                       usearch_threads=args.no_proc)
        pred.compute_features()
        res = pred.predict()
        res.to_csv(args.o_csv)
    except UsearchInvalidPath:
        print("Path to USEARCH is invalid:", Paths._USEARCH, file=sys.stderr)
    except TmhmmInvalidPath:
        print("Path to TMHMM is invalid:",Paths._TMHMM ,file=sys.stderr)
    except PdbDatabaseNotFound:
        print("PDB database was not found on given path:", Paths._PDB,
              file=sys.stderr)
    except ModelInvalidPath:
        print("Model does not exists, path:", Paths._MODEL, file=sys.stderr)
    except InvalidAlphabet:
        print("Invalid amino acid alphabet, sequences can contain only "
              "standard amino acids.", file=sys.stderr)
    except ShortSequence:
        print("Some sequences are too short, minimum length of sequence is 20 "
              "amino acids.", file=sys.stderr)
    except DuplicatedSid:
        print("Duplicated identifier in FASTA file, each sequence must "
              "contain unique identifier, duplicated sequences with same "
              "identifier are not allowed.", file=sys.stderr)
    except UsearchExcecutionFailed:
        print("Execution of USEARCH failed.", file=sys.stderr)
    except TmhmmExecutionFailed:
        print("Execution of TMHMM failed.", file=sys.stderr)
    except TmhmmParsingError:
        print("Processing of TMHMM results failed.", file=sys.stderr)
    except ModelIsNotCompatible:
        print("Loaded model is not compatible with predictor.", file=sys.stderr)
    except MissingModelFeatures:
        print("Model requires features that are not computed by predictor.",
              file=sys.stderr)


def arguments():
    parser = argparse.ArgumentParser(
        description="Protein solubility predictor SoluProt. "
                    "NOTE: All paths of external tools "
                    "should be either relative to position of SoluProt "
                    "script or absolute.")
    parser.add_argument('--i_fa', help="Input sequences in FASTA format.",
                        required=True)
    parser.add_argument('--o_csv', help="Prediction results in csv format. "
                                        "Meaning of columns: runtime_id - "
                                        "unique identifier within the "
                                        "execution of program, "
                                        "this identifier is used for results "
                                        "of third party tools located in tmp "
                                        "directory, fa_id - matches the "
                                        "identifier in input FASTA file, "
                                        "soluble - results of prediction",
                        required=True)
    parser.add_argument('--tmp_dir', required=True,
                        help=("Directory for temporary results "
                              "and computations. It is recommended to create "
                              "new directory for this "
                              "purpose as files in this directory may be "
                              "overwritten."))
    parser.add_argument('--no_tmhmm', default=False,
                        help="Do not run TMHMM and use slightly less accurate (-0.5%%) model trained without TMHMM features", action='store_true')
    parser.add_argument('--model', default=None,
                        help="Relative or absolute path to the model")
    parser.add_argument('--usearch', default=Paths._USEARCH,
                        help="Relative or absolute path to USEARCH executable")
    parser.add_argument('--tmhmm', default=Paths._TMHMM,
                        help="Relative or absolute path to TMHMM executable")
    parser.add_argument('--pdb', default=Paths._PDB_ECOLI_FA,
                        help="Relative or absolute path to PDB FASTA file.")
    parser.add_argument('--check_unknown', default=False,
                        help="Raise error if sequence contains non standard residue.", action='store_true')
    parser.add_argument('--no_proc', type=int, default=1,
                        help="Number of processes.")
    args = parser.parse_args()

    return args


if __name__ == '__main__':
    main()
