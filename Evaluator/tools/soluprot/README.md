# SoluProt: prediction of soluble protein expression in *Escherichia coli*

## Installation

- Install Miniconda, see: https://docs.conda.io/en/latest/miniconda.html
- Create environment for SoluProt:
  1. `cd soluprot`
  2. `conda env create -f soluprot_environment.yml`
- Change paths to 3rd party tools (if needed) in class `Paths` located in file `soluprot.py` or set them by arguments see `soluprot.py --help`, default paths:

    ```python
    _USEARCH = '/path/to/usearch'
    _TMHMM = '/path/to/tmhmm'
    ```

## Run

Before running SoluProt, set envrionment to soluprot: `source activate soluprot`

Basic usage:
```
python soluprot.py --i_fa seqs.fasta --o_csv out.csv --tmp_dir tmp

  --i_fa - Input FASTA file
  --o_csv - Output CSV file
  --tmp_dir - Directory for temporary results of additional tools
```

Help:
```bash
python soluprot.py --help
```

Test example:
```bash
source activate soluprot
python soluprot.py --i_fa ./data/test.fa --o_csv test.csv --tmp_dir tmp
diff test.csv ./data/test.csv
```

## Additional tools links

1. USEARCH: https://www.drive5.com/usearch/
2. TMHMM: http://www.cbs.dtu.dk/cgi-bin/nph-sw_request?tmhmm or https://git.loschmidt.cz/misc/tmhmm

## Troubleshooting

In case SoluProt prints the following message "*Warning: feature tmhmm_pred_hel can not be calculated...*", you probably need to fix the `tmhmm` and `tmhmmformat.pl` scripts from the TMHMM `bin` directory as follows:

  - In the `tmhmm-2.0c/bin/tmhmm` file, replace the first line `#!/usr/local/bin/perl` by `#!/usr/bin/env perl`
  - In the `tmhmm-2.0c/bin/tmhmmformat.pl`, replace the first line `#!/usr/local/bin/perl -w` by `#!/usr/bin/env perl`
