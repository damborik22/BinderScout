import pandas as pd


def set_df_prefix(df: pd.DataFrame, prefix, exclude=["sid"], delim="_"):
    """
    Add prefix to dataframe columns.
    """
    cols = list(df.columns)
    f_cols = []
    for i, c in enumerate(cols):
        if c not in exclude:
            new = prefix + delim + c
            df.rename(columns={c: new}, inplace=True)
            f_cols.append(new)
    return f_cols


