import os
import shutil
import logging
import concurrent.futures
from itertools import combinations, permutations

from pathlib import Path
from tqdm import tqdm

import numpy as np
import pandas as pd
from pandas.errors import ParserError
from scipy.stats import f_oneway, rv_histogram
from statsmodels.stats.weightstats import ttest_ind
from statsmodels.stats.multitest import multipletests

import annutils
from entry import Entry
from logo import create_logo_helper
from visualize import Visualizer


class Clipper:
    """Annotator class for processing and analyzing peptide proteomics data. All
    arguments are passed as a dictionary to the class constructor.

    Attributes:
        conditions (dict): A dictionary of conditions and their respective files.
        annot (pd.DataFrame): The input data as a Pandas DataFrame.
        outfolder (str): The path to the output folder.
        outfile_type (str): The type of output file to generate.
        logfolder (str): The path to the log folder.
        logfile (str): The path to the log file.
        figures (dict): A dictionary of generated figures.
        separate (bool): A flag to indicate if annotation data should be separate.
        pseudocounts (float): The pseudocount value for sequence logo generation.
        logo (str): The type of logo to generate.
        stat (bool): A flag to indicate if statistical calculations should be performed.
        df (pd.DataFrame): The dataframe to store processed data.
    """

    def __init__(self, args):
        """Initialize the Annotator class, and set the attributes from the arguments."""

        # global variables
        self.result_folder_name = "results"
        self.data_folder_name = "data"
        self.annotation_prefix = "_annot."

        self.alphafold_models_filename = "alphafold_accs.txt"
        self.merops_filename = "cleavage.csv"
        self.merops_name_filename = "protein_name.csv"
        self.protein_atlas_filename = "proteinatlas.tsv"

        # output folders
        self.plot_protein_folder = "protein_plots"
        self.plot_general_folder = "general_plots"
        self.plot_fold_change_folder = "fold_change_plots"
        self.plot_volcano_folder = "volcano_plots"
        self.plot_piechart_folder = "piecharts"
        self.plot_logo_folder = "logos"
        self.plot_enrichement_folder = "enrichment"
        self.plot_pathway_folder = "pathway"

        # input attributes
        self.infile_type = args["infile_type"]
        self.infile = args["infile"]
        self.software = args["software"]

        # filtering and sanitizing
        self.level = args["level"]
        self.dropna = args["dropna"]
        self.fillna = args["fillna"]

        # annotation attributes
        self.separate = args["separate"]
        self.sleeptime = args["sleeptime"]
        self.noexo = args["noexo"]
        self.merops = None
        self.nomerops = args["nomerops"]
        self.calcstructure = args["calcstructure"]

        self.conditionfile = args["conditionfile"]
        self.stat = args["stat"]
        self.pairwise = args["stat_pairwise"]
        self.significance = args["significance"]
        self.multiple_testing = 'fdr_bh'
        self.alpha = 0.05
        self.available_models = None

        self.plot = args["visualize"]
        self.cleavagevis = args["cleavagevis"]
        self.logo = args["logo"]
        self.pseudocounts = args["pseudocounts"]
        self.enrichment = args["enrichment"]
        self.pathway = args["pathway"]

        # logging and file handling
        self.timestamp = args["timestamp"]
        self.logfile = args["logfile"]
        self.outfile_type = args["outfile_type"]
        self.outname = args["output_name"]

        self.conditions = None
        self.figures = {}

        self.basefolder = Path.cwd().parent.absolute()
        self.resultfolder = self.basefolder / self.result_folder_name
        self.datafolder = self.basefolder / self.data_folder_name

        logging.info("Initialization successful.")

    def validate_input_output_formats(self):
        """Validate the input and output file formats."""

        if self.infile_type == "infer":
            if self.infile.endswith(".csv"):
                self.infile_type = "csv"
            elif self.infile.endswith(".xlsx") or self.infile.endswith(".xls"):
                self.infile_type = "excel"
            else:
                self.raise_invalid_file_format_error("input")

        valid_output_formats = ["xlsx", "csv", "tsv", "pkl", "json"]
        if self.outfile_type not in valid_output_formats:
            self.raise_invalid_file_format_error("output")

        if self.conditionfile is not None and not os.path.exists(self.conditionfile):
            error_message = "Invalid condition file. Check if the path exists, and try again."
            logging.critical("Exit with code 6.")
            raise TypeError(error_message)
            
        if not self.conditionfile.endswith(".txt"):
            self.raise_invalid_file_format_error("condition file")

    def raise_invalid_file_format_error(self, file_type):
        """Raise an error if the input or output file format is invalid."""

        error_message = f"Invalid {file_type} format. Please select a valid {file_type} format and try again."
        logging.critical(f"{error_message}. Exiting with code 1.")
        raise TypeError(error_message)
    
    def set_input_output_paths(self):
        """Set the paths to the input and output files."""

        if self.outname:
            self.outfolder = self.resultfolder / self.outname
            self.outname = self.outname + self.annotation_prefix + self.outfile_type
        else:
            self.outfolder = self.resultfolder / self.timestamp
            self.outname = Path(self.infile).name.rsplit(".", 1)[0] + self.annotation_prefix + self.outfile_type

        self.protein_folder = self.outfolder / self.plot_protein_folder
        self.general_folder = self.outfolder / self.plot_general_folder
        self.fold_change_folder = self.outfolder / self.plot_fold_change_folder
        self.volcano_folder = self.outfolder / self.plot_volcano_folder
        self.piechart_folder = self.outfolder / self.plot_piechart_folder
        self.logo_folder = self.outfolder / self.plot_logo_folder
        self.enrichment_folder = self.outfolder / self.plot_enrichement_folder
        self.pathway_folder = self.outfolder / self.plot_pathway_folder

        self.folders = {"out": self.resultfolder, "data": self.datafolder, "protein": self.protein_folder, "general": self.general_folder,
                        "volcano": self.volcano_folder, "fold": self.fold_change_folder, "piechart": self.piechart_folder, "logo": self.logo_folder,
                        "enrichment": self.enrichment_folder, "pathway": self.pathway_folder}

    def load_data(self):
        """Load the input data into a Pandas DataFrame."""

        logging.info("Reading file...")
        self.read_file()
        logging.info("Read dataframe.")
        logging.info(f"Read input with {len(self.df)} peptides\n")

    def set_software(self):
        """Set the software used to generate the input file, and generate the indexing patterns."""

        if self.software == "infer":
            try:
                self.df.loc[0, "Master Protein Accessions"]
                self.software = "pd"
            except KeyError:
                try:
                    self.df.loc[0, "PG.ProteinAccessions"]
                    self.software = "sm"
                except KeyError:
                    error_message = (
                        f"Invalid input. Please make sure input format is correct "
                        f"and contains accession and sequence columns with default "
                        f"names, and try again."
                    )
                    logging.critical("Invalid input. Exiting with code 4.")
                    raise TypeError(error_message)
                except:
                    logging.critical("Invalid input. Exiting with code 5.")
                    raise TypeError("Invalid input")

        logging.info(f"Input software is {self.software}")
        self.patterns = self.get_patterns()
        logging.info("Successfully generated indexing patterns.")
        logging.info(f"Patterns are: {self.patterns}")
        logging.info("Format check complete.\n")

    def remove_empty_accessions(self):
        """Remove rows with empty accession numbers."""

        col_acc = self.patterns['acc']
        invalid_acc = self.df[col_acc].isna()
        if invalid_acc.any():
            logging.info(f"Empty accession rows: {', '.join(map(str, invalid_acc.index + 1))}")
            self.df = self.df[~invalid_acc].reset_index(drop=True)

    def remove_empty_sequences(self):
        """Remove rows with empty sequences."""
        col_seq = self.patterns['seq']
        invalid_seq = self.df[col_seq].isna()
        if invalid_seq.any():
            logging.info(f"Empty sequence rows: {', '.join(map(str, invalid_seq.index + 1))}")
            self.df = self.df[~invalid_seq].reset_index(drop=True)

    def remove_invalid_alphabets(self):
        """Remove rows with invalid amino acid characters."""

        col_seq = self.patterns['seq']
        pattern = self.patterns['amino']
        invalid_alphabet = self.df[col_seq].str.contains(pattern)
        if invalid_alphabet.any():
            logging.info(f"Invalid sequence character rows: {', '.join(map(str, invalid_alphabet.index + 1))}")
            self.df = self.df[~invalid_alphabet].reset_index(drop=True)

    def sanitize(self):
        """Sanitize the dataframe."""
        
        self.remove_empty_accessions()
        self.remove_empty_sequences()
        self.remove_invalid_alphabets()

    def filter_df(self):
        """Uses --level to remove peptides not in desired level."""

        try:
            if self.level == "nterm":
                logging.info("Level is N-term")
                pattern = self.patterns['nterm']
            elif self.level == "quant":
                logging.info("Level is quant N-term")
                pattern = self.patterns['nterm_label']
            else:
                logging.warning("Unrecognized level argument. Falling back to all")
                return

            self.df = self.df[
                self.df[self.patterns['mod']].str.contains(pat=pattern, na=False)
            ].reset_index(drop=True)

        except:
            logging.critical("Exit with code 3")
            raise TypeError(
                f"Could not filter dataframe. Make sure software \
                {self.software} is correct, and try again."
            )

        if self.dropna:
            columns = self.df.columns[
                self.df.columns.str.contains(pat=self.patterns['quant'])
            ]
            self.df = self.df.dropna(subset=columns, how="all")
            
    def prepare(self):
        """Control of arguments from user input."""

        self.validate_input_output_formats()
        self.set_input_output_paths()
        self.load_data()
        self.set_software()

        if self.level != "all":
            self.filter_df()

        self.sanitize()
        self.make_folders()

    def make_folders(self):
        """Create output folders."""

        os.mkdir(self.outfolder)

        if self.plot:
            os.mkdir(self.general_folder)
            os.mkdir(self.fold_change_folder)
            os.mkdir(self.volcano_folder)
            os.mkdir(self.piechart_folder)
            if self.stat:
                if self.cleavagevis:
                    os.mkdir(self.protein_folder)
                if self.logo:
                    os.mkdir(self.logo_folder)
                if self.enrichment:
                    os.mkdir(self.enrichment_folder)
                if self.pathway:
                    os.mkdir(self.pathway_folder)

    def read_MEROPS(self):
        """Read MEROPS data from csv files."""

        logging.info("Reading MEROPS data..")
        self.merops = pd.read_csv(self.datafolder / self.merops_filename)
        self.merops_name = pd.read_csv(self.datafolder / self.merops_name_filename)
        self.merops_name = self.merops_name[self.merops_name.type == "real"]

    def read_protein_atlas(self):
        """Read Protein Atlas data from TSV file."""

        logging.info("Reading Protein Atlas data..")
        self.protein_atlas = pd.read_csv(self.datafolder / self.protein_atlas_filename, sep='\t')
        logging.info("Read Protein Atlas data.")

    def read_available_models(self):
        # read available alphafold models
        logging.info("Reading available AlphaFold models...")
        available_models = annutils.read_alphafold_accessions(self.datafolder / self.alphafold_models_filename)
        logging.info(f"Read available AlphaFold models.")

        self.available_models = available_models

    def initialize_annotation(self, length: int):
        """Initialize a dataframe with empty annotation columns, same size as
        input df."""

        self.annot = pd.DataFrame(
            columns=[
                "query_sequence",
                "query_accession",
                "name",
                "full_sequence",
                "description",
                "keywords",
                "go_codes",
                "go_names",
                "proteoform_certainty%",
                "start_pep",
                "end_pep",
                "p1_position",
                "cleavage_site",
                "p4_p4prime",
                "nterm_annot",
                "protease_uniprot",
                "protease_merops_code",
                "protease_merops_name",
            ],
            index=range(length),
        )

        if self.nomerops:
            self.annot.drop(["protease_merops_code", "protease_merops_name"], axis=1, inplace=True)

    def read_file(self):
        """Reads input file, returns dataframe object."""
        try:
            if self.infile_type == "csv":
                logging.info("Input is csv")
                try:
                    df = pd.read_csv(self.infile, sep=",")
                except pd.errors.ParserError:
                    logging.info("Failed to parse with ',', trying with ';'")
                    df = pd.read_csv(self.infile, sep=";")
            elif self.infile_type == "excel":
                logging.info("Input is excel")
                df = pd.read_excel(self.infile, engine="openpyxl")
            else:
                raise ValueError(f"Unsupported file type: {self.infile_type}")
        except (OSError, Exception) as err:
            self.handle_file_error(err)

        self.df = df

    def read_condition_file(self):
        """Parses and stores information about conditions and corresponding channels."""
        with open(self.conditionfile, "r") as fh:
            self.conditions = {
                line.split()[0]: line.split()[1:] for line in fh.readlines()
            }

    def handle_file_error(self, err):
        """Handles file reading errors."""

        logging.critical(f"Could not read file due to error: {err}")
        logging.critical("Exit with code 2")
        raise TypeError(
            f"Could not read file. Make sure the path {self.infile} is correct, "
            f"file type {self.infile_type} is supported, and try again."
        )

    def process_columns(self, pat):
        
        quant = self.df.columns[self.df.columns.str.contains(pat=pat)]

        if len(quant) > 0:
            try:
                columns = self.df.columns[self.df.columns.str.contains(pat)]
                for col in columns:
                    self.df[col] = self.df[col].astype(str).str.replace(",", ".").str.strip()

                    self.df[col] = pd.to_numeric(self.df[col], errors='coerce')
                    logging.info(f"Converted values in {col} to numeric type")

                    mask = (self.df[col].notna()) & pd.to_numeric(self.df[col], errors='coerce').isna()
                    if mask.any():
                        logging.warning(f"Could not convert the following values in column {col}")

                    if self.fillna is not None:
                        # Fill NaN values with the user-specified value
                        self.df[col].fillna(float(self.fillna), inplace=True)
                        logging.info(f"Filled NaN values in column '{col}' with {float(self.fillna)}")
                    
            except:
                logging.critical("Invalid input. Exiting with code 4.")
                raise TypeError(
                    f"Invalid input. Could not convert values to float. Make sure input format {self.software} is correct and there are no string literals in quant columns, and try again."
                    )
            return pat
        else:
            return None

    def get_patterns_sm(self):
        
        patterns = {}

        patterns['acc'] = "PG.ProteinAccessions"
        patterns['seq'] = "PEP.StrippedSequence"
        patterns['amino'] = "B|J|O|U|X|Z"

        try:
            annutils.parse_acc(self.df.loc[0, patterns['acc']])
            self.df.loc[0, patterns['seq']]
        except:
            logging.critical("Invalid input. Exiting with code 4.")
            raise TypeError(
                f"Invalid input. Please make sure input format {self.software} \
                is correct and contains sequence columns with default names, \
                and try again."
            )

        # Identify modification column
        if "P.MoleculeID" in self.df.columns:
            patterns['mod'] = "P.MoleculeID"
        elif "EG.PrecursorId" in self.df.columns:
            patterns['mod'] = "EG.PrecursorId"
        else:
            logging.critical("Invalid input. Exiting with code 4.")
            raise TypeError(
                f"Invalid input. Please make sure input format {self.software} \
                contains valid modification column (P.MoleculeID or EG.PrecursorId), \
                and try again."
            )

        # Check for the presence of columns and process if present
        pat_tmt = r"PEP\.TMT"
        pat_tot = r"EG\.TotalQuantity"
        patterns['quant'] = self.process_columns(pat_tmt) or self.process_columns(pat_tot)

        # Check modification type
        pat_tmt_mod = r"\[TMT"
        pat_dim_mod = r"Dimeth"

        mod_tmt = len(self.df[self.df[patterns['mod']].str.contains(pat_tmt_mod, na=False)])
        mod_dim = len(self.df[self.df[patterns['mod']].str.contains(pat_dim_mod, na=False)])

        if mod_tmt > 0:
            patterns['label'] = r"\[TMT"
            patterns['nterm'] = r"N-?ter"
            patterns['nterm_label'] = r"TMT.*_Nter"
            patterns['lysine_label'] = r"K\[TMT.{0,3}_Lys\]"
        elif mod_dim > 0:
            patterns['label'] = pat_dim_mod
            patterns['nterm'] = r"DimethNter0"
            patterns['nterm_label'] = r"\[DimethNter0\]"
            patterns['lysine_label'] = r"K\[DimethLys0\]"
        else:
            logging.critical("Invalid input. Exiting with code 4.")
            raise TypeError(
                f"Invalid input. Please make sure input format {self.software} \
                contains valid modification types (TMT or Dimethyl), \
                and try again."
            )

        return patterns

    def get_patterns_pd(self):

        patterns = {}

        patterns['acc'] = "Master Protein Accessions"
        patterns['mod'] = "Modifications"
        patterns['nterm'] = r"\[N-Term\]"
        patterns['seq'] = "Sequence"
        patterns['amino'] = "B|J|O|U|X|Z"

        try:
            # check if sequence column is present
            annutils.parse_acc(self.df.loc[0, patterns['acc']])
            self.df.loc[0, patterns['seq']]
        except KeyError:
            try:
                # if sequence column is not present, check if modifications column is present
                annutils.parse_acc(self.df.loc[0, patterns['acc']])
                patterns['seq'] = "Annotated Sequence"
                annutils.parse_sequence(self.df.loc[0, patterns['mod']])
                patterns['amino'] = "\.[A-Z]*(B|J|O|U|X|Z)[A-Z]*\."
            except KeyError:
                logging.critical("Invalid input. Exiting with code 4.")
                raise TypeError(
                    f"Invalid input. Please make sure input \
                    format {self.software} is correct and contains \
                    sequence columns with default names, and try again."
                )

        # find the quant columns
        pat_scale = r'Abundances \(?Scaled\):.*'
        pat_norm = r'Abundances \(?Normalized\):.*'
        pat_grouped = r'Abundances \(Grouped\):.*'
        pat_raw = r'Abundance: .*'
        pat_other = r'Abundance.*'
        
        # Check for the presence of columns and process if present
        patterns['quant'] = self.process_columns(pat_scale) or \
                            self.process_columns(pat_norm) or \
                            self.process_columns(pat_grouped) or \
                            self.process_columns(pat_raw) or \
                            self.process_columns(pat_other)
        
        pat_label = r"TMT"
        pat_alt_label = r"Dimethyl"

        quant_tmt = len(self.df[self.df['Modifications'].str.contains(pat=pat_label, na=False)])
        quant_dimethyl = len(self.df[self.df['Modifications'].str.contains(pat=pat_alt_label, na=False)])

        if quant_tmt == 0:
            if quant_dimethyl == 0:
                patterns['label'] = None
                patterns['nterm_label'] = None
            else:
                patterns['label'] = pat_alt_label
                patterns['nterm_label'] = r"Dimethyl \[N-Term\]"
                patterns['lysine_label'] = r"Dimethyl \[K"

        else:
            patterns['label'] = pat_label
            patterns['nterm_label'] = r"TMT.* \[N-Term\]"
            patterns['lysine_label'] = r"TMT.{0,5} \[K"

        return patterns

    def get_patterns(self):
        """Returns column patterns to be used for indexing."""

        patterns = {}

        if self.software == 'sm':
            patterns = self.get_patterns_sm()
        elif self.software == 'pd':
            patterns = self.get_patterns_pd()
        else:
            logging.critical("Invalid software input. Exiting with code 4.")
            raise TypeError(f"Invalid software input. Please provide a valid software format and try again.")

        return patterns

    def proteoform_check(self):
        """Computes probability of proteoforms based on master accession column"""
        self.annot["proteoform_certainty%"] = self.df[self.patterns['acc']].apply(
            lambda x: 100 / len([i.strip() for i in x.split(';')])
        )

    def general_conditions(self):
        """General statistics for the conditions supplied."""

        if not self.conditions:
            self.conditions = {
                "all": ["126", "127", "128", "129", "130", "131", "132", "133", "134"]
            }

        def calc_stats(df, cols):
            mean = df[cols].mean(axis=1)
            std = df[cols].std(axis=1)
            return mean, std, std / mean

        def generate_condition_columns(pair, mean0, mean1):
            column_name = f"Fold_change: {pair[0]}/{pair[1]}"
            column_log = f"Log2_fold_change: {pair[0]}/{pair[1]}"
            fold_change = mean0 / mean1
            log_fold_change = np.log2(fold_change)
            return column_name, column_log, fold_change, log_fold_change

        for condition, channels in self.conditions.items():
            cols = self.df.columns[self.df.columns.str.contains("|".join(channels)) & self.df.columns.str.contains(self.patterns['quant'])]
            mean, std, cv = calc_stats(self.df, cols)
            self.annot[f"{condition}_mean"] = mean
            self.annot[f"{condition}_deviation"] = std
            self.annot[f"{condition}_CV"] = cv

        if len(self.conditions) > 1:
            for pair in permutations(self.conditions.keys(), 2):
                cols0 = self.df.columns[self.df.columns.str.contains("|".join(self.conditions[pair[0]])) & self.df.columns.str.contains(self.patterns['quant'])]
                cols1 = self.df.columns[self.df.columns.str.contains("|".join(self.conditions[pair[1]])) & self.df.columns.str.contains(self.patterns['quant'])]
                mean0, _, _ = calc_stats(self.df, cols0)
                mean1, _, _ = calc_stats(self.df, cols1)
                column_name, column_log, fold_change, log_fold_change = generate_condition_columns(pair, mean0, mean1)
                self.annot[column_name] = fold_change
                self.annot[column_log] = log_fold_change

    def percentile_fold(self, percentile):
        """Checks fold change distribution and marks rows above a certain percentile."""

        left_cutoff = percentile
        right_cutoff = 1 - percentile

        if len(self.conditions) > 1:
            conditions_iter = permutations(self.conditions.keys(), 2)

            for pair in conditions_iter:
                column = f"Fold_change: {pair[0]}/{pair[1]}"
                self.annot[f"Fold {pair[0]}/{pair[1]} significance"] = np.nan

                if self.significance == 'all':
                    subframe = self.annot
                elif self.significance == 'nterm':
                    is_internal = self.annot["nterm_annot"] == "Internal"
                    subframe = self.annot[~is_internal] if column.endswith("low") else self.annot[is_internal]
                else:
                    logging.info(f"Significance invalid argument {self.significance}, skipping")
                    continue

                hist = np.histogram(subframe[column].dropna())
                hist_dist = rv_histogram(hist)

                def classify_fold_change(value):
                    cd = hist_dist.cdf(value)
                    if cd > right_cutoff:
                        return "significant high"
                    elif cd < left_cutoff:
                        return "significant low"
                    return np.nan

                self.annot[f"Fold {pair[0]}/{pair[1]} significance"] = subframe[column].apply(classify_fold_change)

    def condition_statistics(self):
        """Perform a ttest or ANOVA statistical significance tests."""
        
        def perform_test(test_func, cols0, cols1, column_name, column_log):
            values0 = np.log2(self.df[cols0].values)
            values1 = np.log2(self.df[cols1].values)
            result = test_func(values0.T, values1.T)
            statistic, p_value = result[0], result[1]
            self.annot[column_name] = p_value
            self.annot[column_log] = np.log10(p_value)

        if self.pairwise:
            for pair in combinations(self.conditions.keys(), 2):
                column_name = f"Ttest: {pair[0]}_{pair[1]}"
                column_log = f"Log10_ttest: {pair[0]}_{pair[1]}"
                cols0 = self.df.columns[self.df.columns.str.contains("|".join(self.conditions[pair[0]])) & self.df.columns.str.contains(self.patterns['quant'])]
                cols1 = self.df.columns[self.df.columns.str.contains("|".join(self.conditions[pair[1]])) & self.df.columns.str.contains(self.patterns['quant'])]
                perform_test(ttest_ind, cols0, cols1, column_name, column_log)

        else:
            conditions = list(self.conditions.keys())
            if len(self.conditions) >= 2:
                test_func = ttest_ind if len(self.conditions) == 2 else f_oneway
                column_name = f"{'Ttest' if len(self.conditions) == 2 else 'ANOVA'}: {'_'.join(conditions)}"
                column_log = f"Log10_{column_name}"
                cols_per_condition = [self.df.columns[self.df.columns.str.contains("|".join(self.conditions[cond])) & self.df.columns.str.contains(self.patterns['quant'])] for cond in conditions]
                perform_test(test_func, *cols_per_condition, column_name, column_log)

    def correct_multiple_testing(self):
        """Correct p-values for multiple testing."""
            
        if not self.multiple_testing or len(self.conditions) < 2:
            logging.info("No multiple testing correction performed")
            return   

        def perform_correction(pvals, column_name, column_log, original_column_name):
            # Identify NaN values
            not_nan = ~np.isnan(pvals)

            # Remove NaN values before performing multiple testing correction
            pvals_no_nan = pvals[not_nan]
            corrected_pvals_no_nan = multipletests(pvals_no_nan, alpha=self.alpha, method=self.multiple_testing)[1]

            # Save the corrected p-values back to their original index positions
            corrected_pvals = np.empty_like(pvals)
            corrected_pvals[:] = np.nan
            corrected_pvals[not_nan] = corrected_pvals_no_nan

            # Insert the corrected p-value columns next to the original p-value columns
            original_column_idx = self.annot.columns.get_loc(original_column_name)
            self.annot.insert(original_column_idx + 2, column_name, corrected_pvals)
            self.annot.insert(original_column_idx + 3, column_log, np.log10(corrected_pvals))

            logging.info(f"Corrected p-values for {column_name} using {self.multiple_testing} method")
        
        if self.pairwise:
            col_stat = 'Ttest'
            for pair in combinations(self.conditions.keys(), 2):
                column_name = f"Corrected {col_stat}: {pair[0]}_{pair[1]}"
                column_log = f"Log10_{column_name}"
                original_column_name = f"{col_stat}: {pair[0]}_{pair[1]}"
                pvals = self.annot[original_column_name].values
                perform_correction(pvals, column_name, column_log, original_column_name)
        else:
            col_stat = 'Ttest' if len(self.conditions) == 2 else 'ANOVA'
            column_name = f"Corrected {col_stat}: {'_'.join(self.conditions.keys())}"
            column_log = f"Log10_{column_name}"
            original_column_name = f"{col_stat}: {'_'.join(self.conditions.keys())}"
            pvals = self.annot[original_column_name].values
            perform_correction(pvals, column_name, column_log, original_column_name)

    def process_entry(self, loc):
        """Process a single entry and return the annotation."""

        acc = annutils.parse_acc(self.df.loc[loc, self.patterns['acc']])
        if self.patterns['seq'] == 'Annotated Sequence':
            seq = annutils.parse_sequence(self.df.loc[loc, self.patterns['seq']])
        else:
            seq = self.df.loc[loc, self.patterns['seq']]

        ent = Entry(acc, seq)
        ent.get_record(self.sleeptime)

        if ent.record is not None:
            ent.parse_general()
            ent.parse_cleavage()

            if ent.cleavage_site is not None:
                ent.parse_protease()
                if self.nomerops is False:
                    ent.merops_protease(self.merops, self.merops_name)

            return annutils.map_dict(self.annot.loc[loc], ent.annot)
        else:
            return {"name": "HTTPError, not found"}
        
    def annotate(self):
        """Main function that calls all other functions apart from exopeptidase
        and write_file."""

        length = len(self.df)
        if self.nomerops is False:
            self.read_MEROPS()
            logging.info("Read MEROPS data.")

        self.initialize_annotation(length)
        logging.info("Initialized annotation dataframe.\n")

        for loc in tqdm(range(length)):
            self.annot.loc[loc] = self.process_entry(loc)
    
    def entry_annotate(self, loc):
        """Single entry annotation function used with multiple threading."""
        self.annot.loc[loc] = self.process_entry(loc)

    def threaded_annotate(self):
        """Annotation with multiple threading. Uses all available cores."""

        length = len(self.df)
        batch_length = min(os.cpu_count(), length)

        if self.nomerops is False:
            self.read_MEROPS()
            logging.info("Read MEROPS data")

        self.initialize_annotation(length)
        logging.info("Initialized annotation dataframe.\n")

        for i in tqdm(range(0, length, batch_length)):
            batch = list(range(i, i + batch_length))

            with concurrent.futures.ThreadPoolExecutor(
                max_workers=batch_length
            ) as executor:
                executor.map(self.entry_annotate, batch)

    def annotate_protein_atlas(self):
        """Annotate specific columns from Protein Atlas."""

        self.read_protein_atlas()
        
        protein_atlas_columns = ['Uniprot', 'RNA tissue specific nTPM', 'RNA single cell type specific nTPM', 'Chromosome', 'Position', 'Protein class', 'Biological process', 'Molecular function', 'Disease involvement']
        protein_atlas_sub = self.protein_atlas[protein_atlas_columns].add_prefix('ProteinAtlas_')
        protein_atlas_sub.rename(columns={"ProteinAtlas_Uniprot": "Uniprot"}, inplace=True)

        # Check for duplicates in Uniprot column of Protein Atlas dataframe and drop them
        if protein_atlas_sub['Uniprot'].duplicated().any():
            logging.warning("Duplicates found in 'Uniprot' column of 'protein_atlas_sub'. Dropping duplicates.")
            protein_atlas_sub = protein_atlas_sub.drop_duplicates(subset='Uniprot')

        self.annot = pd.merge(self.annot, protein_atlas_sub, left_on='query_accession', right_on='Uniprot', how='left')
        self.annot.drop(columns='Uniprot', inplace=True)

    def exopeptidase(self):
        """Annotate dipeptidase and aminopeptidase activity by checking
        sequences for rugging patterns."""

        # keep track of sequences that have been checked
        cleared = set()
        # initialize column in the annotation dataframe
        self.annot["exopeptidase"] = np.nan
        # remove nan values and sort by length, so that longer sequences are checked first and cleared
        sequences = self.annot["query_sequence"].dropna()
        sequences.sort_values(key=lambda x: x.str.len(), kind="mergesort", ascending=False, inplace=True)

        for seq in tqdm(sequences):
            if seq not in cleared:
                # check if sequence ends with ragged pattern. If so, check if the same sequence
                # with the last amino acid removed is also in the dataframe. If so, annotate.
                rag_flag = False
                cleared.add(seq)
                char_match = seq[-5:]
                matching_peptides = sequences[sequences.str.endswith(char_match)]

                # if there are matches with 5 amino acids from the carboxy terminus, check if there is a ragged pattern
                if len(matching_peptides) > 1:
                    compare = seq
                    lpep = len(seq)

                    # for each matching peptide, check if the same sequence with the last amino acid removed is also in the dataframe
                    for ind in matching_peptides.index:
                        pep = matching_peptides[ind]
                        same_seq_indices = self.annot[self.annot["query_sequence"] == pep].index
                        
                        # if there is a ragged pattern, annotate as such
                        if pep == compare[1:]:
                            cleared.add(pep)
                            compare = pep
                            logging.info(f"1 {seq} {pep}")
                            # if the ragged pattern originated from dipetidase activity, annotate as such
                            if rag_flag and len(pep) == lpep - 1:
                                for i in same_seq_indices:
                                    self.annot.loc[i, "exopeptidase"] = "Dipeptidase_seed_Aminopeptidase_activity"
                            # if the ragged pattern exists, annotate as aminopeptidase
                            else:
                                for i in same_seq_indices:
                                    self.annot.loc[i, "exopeptidase"] = "Aminopeptidase_activity"
                                rag_flag = False

                        elif pep == compare[2:]:
                            cleared.add(pep)
                            compare = pep
                            rag_flag = True
                            lpep = len(pep)
                            logging.info(f"2 {seq} {pep}")
                            for i in same_seq_indices:
                                self.annot.loc[i, "exopeptidase"] = "Dipeptidase_activity"

    def annotate_structure(self, cutoff=0.05):
        """Annotates secondary structure and solvent accessibility for the cleavage site"""

        if self.available_models is None:
            self.read_available_models()

        self.annot["secondary_structure p4_p4prime"] = np.nan
        self.annot["solvent_accessibility p4_p4prime"] = np.nan

        if self.calcstructure == "all":
            for i in tqdm(range(len(self.annot))):
                # get the accession and cleavage site
                acc = self.annot.loc[i, "query_accession"]
                cleavage_site = self.annot.loc[i, "p1_position"]

                # if the cleavage site is not nan, annotate
                if isinstance(cleavage_site, int):
                    # get the secondary structure and solvent accessibility of the cleavage site
                    ss, sa = annutils.get_structure_properties(acc, cleavage_site, 4, self.available_models)
                    # assign to the annotation dataframe
                    self.annot.loc[i, "secondary_structure p4_p4prime"] = ss
                    self.annot.loc[i, "solvent_accessibility p4_p4prime"] = sa

        elif self.calcstructure == "sig":
            cols = []
            if len(self.conditions) > 1:
                if self.stat:
                    if self.pairwise or len(self.conditions) == 2:
                        conditions_iter = combinations(self.conditions.keys(), 2)
                        for pair in conditions_iter:
                            column_name = f"Ttest: {pair[0]}_{pair[1]}"
                            cols.append(column_name)
                    else:
                        column_name = "ANOVA: " + "_".join(self.conditions.keys())
                        cols.append(column_name)

                    # iterate over all columns and entries in the dataframe
                    for column_name in cols:
                        for i in tqdm(range(len(self.annot))):
                            # get the accession and cleavage site
                            acc = self.annot.loc[i, "query_accession"]
                            cleavage_site = self.annot.loc[i, "p1_position"]
                            p_value = self.annot.loc[i, column_name]

                            # if the cleavage site is not nan, annotate
                            if p_value <= cutoff and isinstance(cleavage_site, int) and pd.isnull(self.annot.loc[i, "secondary_structure p4_p4prime"]) and pd.isnull(self.annot.loc[i, "solvent_accessibility p4_p4prime"]):
                                # get the secondary structure and solvent accessibility of the cleavage site
                                ss, sa = annutils.get_structure_properties(acc, cleavage_site, 4, self.available_models)
                                # assign to the annotation dataframe
                                self.annot.loc[i, "secondary_structure p4_p4prime"] = ss
                                self.annot.loc[i, "solvent_accessibility p4_p4prime"] = sa
        
        else:
            raise ValueError("calcstructure argument must be either 'all' or 'sig'")

    def visualize(self):
        """Calls Visualizer class and stores figure objects."""

        # initialize Visualizer class, and generate figures for general statistics, CV plot, pie charts, heatmap and clustermap
        vis = Visualizer(self.df, self.annot, self.conditions, self.software, self.patterns, self.pairwise)
        
        self.figures["General"] = vis.general()
        self.figures["CV"] = vis.cv_plot()
        self.figures["Piechart"] = vis.generate_pie_charts()
        self.figures["Heatmap"] = vis.heatmap()
        self.figures["Clustermap"] = vis.clustermap()
        self.figures["PCA"]  = vis.pca_visualization()
        self.figures["UMAP"]  = vis.umap_visualization()

        if self.stat and self.enrichment:
            self.figures["Enrichment"] = vis.plot_functional_enrichment(cutoff=0.05)

        if self.stat and self.pathway:
            vis.plot_pathway_enrichment(cutoff=0.05, folder=self.pathway_folder)

        # if there are more than one condition, generate volcano, fold change and fold change at termini plots, and gallery of significant peptides
        if len(self.conditions) > 1:
            
            self.figures["Volcano"] = vis.volcano()
            self.figures["Fold"] = vis.fold_plot()
            self.figures["Fold_nterm"] = vis.fold_termini()

            logging.info("Starting gallery generation...")
            vis.gallery(stat=self.stat, cutoff=0.05, folder=self.general_folder)
            logging.info("Finished gallery generation.")
            
            if self.stat and self.cleavagevis:
                if self.available_models is None:
                    self.read_available_models()

                logging.info("Starting protein plotting...")
                if self.nomerops is False:
                    vis.plot_protein(cutoff=0.05, folder=self.protein_folder, merops=self.merops, alphafold=self.available_models, level=self.cleavagevis)
                    logging.info("Finished protein plotting.")
                else:
                    vis.plot_protein(cutoff=0.05, folder=self.protein_folder, alphafold=self.available_models, level=self.cleavagevis)
                logging.info("Finished protein plotting.")


    def create_logos(self):
        """Create sequence logos.

        Based on logomaker package, bioconductor matrix calculation
        manual and algorithms in bioinformatics DTU course for PSSM
        construction
        """

        if len(self.conditions) > 1:
            conditions_iter = permutations(self.conditions.keys(), 2)
            for pair in conditions_iter:
                if self.stat: 
                    try:
                        column_name_test = f"Log10_ttest: {pair[0]}_{pair[1]}"
                        column_name_fold = f"Log2_fold_change: {pair[0]}/{pair[1]}"
                        column_test = self.annot[column_name_test]
                        column_fold = self.annot[column_name_fold]
                        condition = column_name_test.split()[1].strip()

                        data = self.annot[(column_test < -1.5) & (column_fold > 1.5)]
                        self.figures[f"Logo_{condition}_high"] = create_logo_helper(data, condition, self.pseudocounts, self.logo)

                        data = self.annot[(column_test < -1.5) & (column_fold < -1.5)]
                        self.figures[f"Logo_{condition}_low"] = create_logo_helper(data, condition, self.pseudocounts, self.logo)            
                    except KeyError:
                        continue
                else:
                    column = f"Fold {pair[0]}/{pair[1]} significance"
                    condition = column.split()[1].strip().replace("/", "_")

                    data = self.annot[self.annot[column] == "significant high"]
                    self.figures[f"Logo_{pair[0]}_high"] = create_logo_helper(data, condition, self.pseudocounts, self.logo)

                    data = self.annot[self.annot[column] == "significant low"]
                    self.figures[f"Logo_{pair[0]}_low"] = create_logo_helper(data, condition, self.pseudocounts, self.logo)

        elif len(self.conditions) == 1:
            condition = list(self.conditions.keys())[0]
            self.figures[f"Logo_{condition}"] = create_logo_helper(self.annot, condition, self.pseudocounts, self.logo)

    def write_files(self):
        """Writes ouput files."""

        outfile = self.outfolder / self.outname

        if self.separate:
            final_df = self.annot
        else:
            final_df = self.df.join(self.annot)

        # Define a mapping of output types to saving methods
        saving_methods = {
            "csv": lambda df, path: df.to_csv(path, sep=",", index=False),
            "tsv": lambda df, path: df.to_csv(path, sep="\t", index=False),
            "xlsx": lambda df, path: df.to_excel(path, engine="openpyxl", index=False),
            "json": lambda df, path: df.to_json(path),
            "pkl": lambda df, path: df.to_pickle(path, compression="infer"),
        }

        # Save the dataframe using the appropriate method
        saving_methods[self.outfile_type](final_df, outfile)

        # Save figures
        if len(self.figures) > 0:
            annutils.save_figures(self.figures, self.folders)

        logging.info(f"Finished. Wrote results to {self.outfolder}.")

        log_basename = os.path.basename(self.logfile)
        shutil.copy(self.logfile, self.outfolder / log_basename)

        shutil.make_archive(self.outfolder, "zip", self.outfolder)

        return None
