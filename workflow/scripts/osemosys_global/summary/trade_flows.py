"""Calcualtes Transmission Flows"""

import pandas as pd
import itertools
from constants import MONTH_NAMES, DAYS_PER_MONTH


def apply_timeshift(x: int, timeshift: int) -> int:
    """Applies timeshift to organize dayparts.

    Arguments:
        x = Value between 0-24
        timeshift = value offset from UTC (-11 -> +12)
    """

    x += timeshift
    if x > 23:
        return x - 24
    elif x < 0:
        return x + 24
    else:
        return x


def get_trade_flows_node(
    activity_by_mode: pd.DataFrame,
    seasons_raw: dict[str, list[int]],
    dayparts_raw: dict[str, list[int]],
    timeshift: int,
) -> pd.DataFrame:

    abm = activity_by_mode.copy()

    interconnections = (
        abm[abm.index.get_level_values("TECHNOLOGY").str.startswith("TRN")]
        .index.get_level_values("TECHNOLOGY")
        .unique()
        .tolist()
    )

    years = abm.index.get_level_values("YEAR").unique().tolist()

    if len(interconnections) > 0:

        seasonsData = []

        for s, months in seasons_raw.items():
            for month in months:
                seasonsData.append([month, s])
        seasons_df = pd.DataFrame(seasonsData, columns=["month", "season"])
        seasons_df = seasons_df.sort_values(by=["month"]).reset_index(drop=True)

        daypartData = []
        for dp, hr in dayparts_raw.items():
            daypartData.append([dp, hr[0], hr[1]])
        dayparts_df = pd.DataFrame(
            daypartData, columns=["daypart", "start_hour", "end_hour"]
        )

        dayparts_df["start_hour"] = dayparts_df["start_hour"].map(
            lambda x: apply_timeshift(x, timeshift)
        )
        dayparts_df["end_hour"] = dayparts_df["end_hour"].map(
            lambda x: apply_timeshift(x, timeshift)
        )

        month_names = MONTH_NAMES
        days_per_month = DAYS_PER_MONTH

        seasons_df["month_name"] = seasons_df["month"].map(month_names)
        seasons_df["days"] = seasons_df["month_name"].map(days_per_month)
        seasons_df_grouped = seasons_df.groupby(["season"], as_index=False)[
            "days"
        ].sum()
        days_dict = dict(
            zip(list(seasons_df_grouped["season"]), list(seasons_df_grouped["days"]))
        )
        seasons_df["days"] = seasons_df["season"].map(days_dict)

        seasons_dict = dict(zip(list(seasons_df["month"]), list(seasons_df["season"])))

        dayparts_dict = {
            i: [j, k]
            for i, j, k in zip(
                list(dayparts_df["daypart"]),
                list(dayparts_df["start_hour"]),
                list(dayparts_df["end_hour"]),
            )
        }

        hours_dict = {
            i: abs(k - j)
            for i, j, k in zip(
                list(dayparts_df["daypart"]),
                list(dayparts_df["start_hour"]),
                list(dayparts_df["end_hour"]),
            )
        }

        months = list(seasons_dict)
        hours = list(range(1, 25))

        # APPLY TRANSFORMATION

        df_ts_template = pd.DataFrame(
            list(itertools.product(interconnections, months, hours, years)),
            columns=["TECHNOLOGY", "MONTH", "HOUR", "YEAR"],
        )

        df_ts_template = df_ts_template.sort_values(by=["TECHNOLOGY", "YEAR"])
        df_ts_template["SEASON"] = df_ts_template["MONTH"].map(seasons_dict)
        df_ts_template["DAYS"] = df_ts_template["SEASON"].map(days_dict)
        df_ts_template["YEAR"] = df_ts_template["YEAR"].astype(int)

        for daypart in dayparts_dict:
            if (
                dayparts_dict[daypart][0] > dayparts_dict[daypart][1]
            ):  # loops over 24hrs
                df_ts_template.loc[
                    (df_ts_template["HOUR"] >= dayparts_dict[daypart][0])
                    | (df_ts_template["HOUR"] < dayparts_dict[daypart][1]),
                    "DAYPART",
                ] = daypart
            else:
                df_ts_template.loc[
                    (df_ts_template["HOUR"] >= dayparts_dict[daypart][0])
                    & (df_ts_template["HOUR"] < dayparts_dict[daypart][1]),
                    "DAYPART",
                ] = daypart

        df_ts_template = df_ts_template.drop_duplicates()

        # Trade flows
        df = abm.copy().reset_index()

        df["SEASON"] = df["TIMESLICE"].str[0:2]
        df["DAYPART"] = df["TIMESLICE"].str[2:]
        df["YEAR"] = df["YEAR"].astype(int)
        df.drop(["REGION", "TIMESLICE"], axis=1, inplace=True)

        df = pd.merge(
            df,
            df_ts_template,
            how="left",
            on=["TECHNOLOGY", "SEASON", "DAYPART", "YEAR"],
        ).dropna()

        df["HOUR_COUNT"] = df["DAYPART"].map(hours_dict)
        df["VALUE"] = (df["VALUE"].mul(1e6)) / (df["DAYS"] * df["HOUR_COUNT"].mul(3600))

        df = df[["YEAR", "MONTH", "HOUR", "TECHNOLOGY", "MODE_OF_OPERATION", "VALUE"]]
        df["MODE_OF_OPERATION"] = df["MODE_OF_OPERATION"].astype(int)
        df.loc[df["MODE_OF_OPERATION"] == 2, "VALUE"] *= -1

        df["NODE_1"] = df.TECHNOLOGY.str[3:8]
        df["NODE_2"] = df.TECHNOLOGY.str[8:13]
        df.drop(columns=["TECHNOLOGY", "MODE_OF_OPERATION"], axis=1, inplace=True)

        df["MONTH"] = pd.Categorical(df["MONTH"], categories=months, ordered=True)
        df = df.sort_values(by=["MONTH", "HOUR"])
        df["VALUE"] = df["VALUE"].round(2)
        df = df[["YEAR", "MONTH", "HOUR", "NODE_1", "NODE_2", "VALUE"]]
    else:
        df = pd.DataFrame(
            columns=["YEAR", "MONTH", "HOUR", "NODE_1", "NODE_2", "VALUE"]
        )
    return df

def get_trade_flows_country(
    trade_flows_node: pd.DataFrame,
) -> pd.DataFrame:
    
    df = trade_flows_node.copy()
    
    df["NODE_1"] = df['NODE_1'].str[0:3] + 'XX'
    df["NODE_2"] = df['NODE_2'].str[0:3] + 'XX'
    df = df.loc[df["NODE_1"] != df["NODE_2"]]  # intercountry
    
    return(df.groupby(["YEAR", "MONTH", "HOUR", "NODE_1", "NODE_2"], as_index = False, 
                      observed = False).sum())

def get_net_annual_flows(
    trade_flows_ts: pd.DataFrame,
) -> pd.DataFrame:
    
    df = trade_flows_ts.copy()
    
    return(df.groupby(["YEAR", "NODE_1", "NODE_2"], as_index = False, 
                      observed = False)['VALUE'].sum())

def get_import_annual_flows(
    trade_flows_ts: pd.DataFrame,
) -> pd.DataFrame:
    
    df = trade_flows_ts.copy()
    df = df.loc[df['VALUE'] < 0]
    df['VALUE']  = df['VALUE']  * -1
    
    return(df.groupby(["YEAR", "NODE_1", "NODE_2"], as_index = False, 
                      observed = False)['VALUE'].sum())

def get_export_annual_flows(
    trade_flows_ts: pd.DataFrame,
) -> pd.DataFrame:
    
    df = trade_flows_ts.copy()
    df = df.loc[df['VALUE'] > 0]
    
    return(df.groupby(["YEAR", "NODE_1", "NODE_2"], as_index = False, 
                      observed = False)['VALUE'].sum())

def get_total_annual_flows(
    trade_flows_ts: pd.DataFrame,
) -> pd.DataFrame:
    
    df = trade_flows_ts.copy()
    df['VALUE'] = df['VALUE'].abs()
    
    return(df.groupby(["YEAR", "NODE_1", "NODE_2"], as_index = False, 
                      observed = False)['VALUE'].sum())

if __name__ == "__main__":
    if "snakemake" in globals():
        activity_by_mode_csv = snakemake.input.activity_by_mode
        trade_flows_node_save = snakemake.output.node_trade_flows
        trade_flows_country_save = snakemake.output.country_trade_flows
        annual_net_trade_flows_node_save = snakemake.output.annual_net_node_trade_flows
        annual_net_trade_flows_country_save = snakemake.output.annual_net_country_trade_flows
        annual_import_trade_flows_node_save = snakemake.output.annual_import_node_trade_flows
        annual_import_trade_flows_country_save = snakemake.output.annual_import_country_trade_flows
        annual_export_trade_flows_node_save = snakemake.output.annual_export_node_trade_flows
        annual_export_trade_flows_country_save = snakemake.output.annual_export_country_trade_flows
        annual_total_trade_flows_node_save = snakemake.output.annual_total_node_trade_flows
        annual_total_trade_flows_country_save = snakemake.output.annual_total_country_trade_flows        
        seasons = snakemake.params.seasons
        dayparts = snakemake.params.dayparts
        timeshift = snakemake.params.timeshift
    else:
        activity_by_mode_csv = (
            "results/India/results/TotalAnnualTechnologyActivityByMode.csv"
        )
        trade_flows_node_save = "results/India/result_summaries/TradeFlowsNode.csv"
        trade_flows_country_save = "results/India/result_summaries/TradeFlowsCountry.csv"
        annual_net_trade_flows_node_save = "results/India/result_summaries/AnnualNetTradeFlowsNode.csv"
        annual_net_trade_flows_country_save = "results/India/result_summaries/AnnualNetTradeFlowsCountry.csv"
        annual_import_trade_flows_node_save = "results/India/result_summaries/AnnualImportTradeFlowsNode.csv"
        annual_import_trade_flows_country_save = "results/India/result_summaries/AnnualImportTradeFlowsCountry.csv"
        annual_export_trade_flows_node_save = "results/India/result_summaries/AnnualExportTradeFlowsNode.csv"
        annual_export_trade_flows_country_save = "results/India/result_summaries/AnnualExportTradeFlowsCountry.csv"
        annual_total_trade_flows_node_save = "results/India/result_summaries/AnnualTotalTradeFlowsNode.csv"
        annual_total_trade_flows_country_save = "results/India/result_summaries/AnnualTotalTradeFlowsCountry.csv"        
        seasons = {"S1": [1, 2, 3, 4, 5, 6], "S2": [7, 8, 9, 10, 11, 12]}
        dayparts = {"D1": [1, 7], "D2": [7, 13], "D3": [13, 19], "D4": [19, 25]}
        timeshift = 0

    activity_by_mode = pd.read_csv(activity_by_mode_csv, index_col=[0, 1, 2, 3, 4])

    trade_flows_node = get_trade_flows_node(activity_by_mode, seasons, dayparts, timeshift)
    trade_flows_country = get_trade_flows_country(trade_flows_node)
    annual_net_trade_flows_node = get_net_annual_flows(trade_flows_node)
    annual_net_trade_flows_country = get_net_annual_flows(trade_flows_country)
    annual_import_trade_flows_node = get_import_annual_flows(trade_flows_node)
    annual_import_trade_flows_country = get_import_annual_flows(trade_flows_country)
    annual_export_trade_flows_node = get_export_annual_flows(trade_flows_node)
    annual_export_trade_flows_country = get_export_annual_flows(trade_flows_country)
    annual_total_trade_flows_node = get_total_annual_flows(trade_flows_node)
    annual_total_trade_flows_country = get_total_annual_flows(trade_flows_country)    
    
    trade_flows_node.to_csv(trade_flows_node_save, index=False)
    trade_flows_country.to_csv(trade_flows_country_save, index=False)
    annual_net_trade_flows_node.to_csv(annual_net_trade_flows_node_save, index=False)
    annual_net_trade_flows_country.to_csv(annual_net_trade_flows_country_save, index=False)
    annual_import_trade_flows_node.to_csv(annual_import_trade_flows_node_save, index=False)
    annual_import_trade_flows_country.to_csv(annual_import_trade_flows_country_save, index=False)
    annual_export_trade_flows_node.to_csv(annual_export_trade_flows_node_save, index=False)
    annual_export_trade_flows_country.to_csv(annual_export_trade_flows_country_save, index=False)
    annual_total_trade_flows_node.to_csv(annual_total_trade_flows_node_save, index=False)
    annual_total_trade_flows_country.to_csv(annual_total_trade_flows_country_save, index=False)
