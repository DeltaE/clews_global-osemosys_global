"""Utility functions for dashboard"""

import pandas as pd
import numpy as np
import geopandas as gpd
from shapely.geometry import LineString
from pathlib import Path 
import os
from osemosys_global.configuration import ConfigFile, ConfigPaths
# from osemosys_global.visualisation.utils import (
#     load_node_data_demand_center, 
#     load_node_data_centroid, 
#     load_line_data, 
#     get_color_codes
# )
import osemosys_global.dashboard.constants as const
from dash import html, dcc
import plotly.express as px
from typing import Union, List, Dict
import warnings
from shapely.errors import ShapelyDeprecationWarning
warnings.filterwarnings("ignore", category=ShapelyDeprecationWarning) 

import logging 
logger = logging.getLogger(__name__)

def add_pts_to_line(x1: float, y1: float, x2: float, y2: float, n_points: int, name: str) -> List[Union[str, LineString]]:
    """Generate a straight line of coordinates between two input 2D coordinates"""
    
    x_coords = np.linspace(x1, x2, n_points)
    y_coords = np.linspace(y1, y2, n_points)
    return [name, LineString(zip(x_coords, y_coords))]

def geolocate_nodes(node_data_file: str, centroid: bool) -> gpd.GeoDataFrame:
    """Geolocates node data
    
    Arguments:
        node_data_file: str
            Path to datafile that holds node data  
        centroid: bool
            Get centroid data, else, demand center data
            
    Returns: 
        GeoDataframe with nodes and lats and lons
    """

    if centroid:
        logger.info("Geolocating nodes at centroid")
        nodes = load_node_data_centroid(node_data_file)
    else:
        logger.info(f"Geolocating nodes at demand center")
        nodes = load_node_data_demand_center(node_data_file)
        
    return gpd.GeoDataFrame(
        nodes, geometry=gpd.points_from_xy(nodes["LONGITUDE"], nodes["LATITUDE"])
    )
    
def geolocate_lines(cost_line_expansion_xlsx: str, nodes: gpd.GeoDataFrame, n_points: int = 20):
    """Gets transmission lines with lats and lons
    
    Arguments:
        cost_line_expansion_xlsx: str
            Path to 'Costs Line expansion.xlsx' file  
        geolocated_nodes: gpd.GeoDataFrame
            Geolocated nodes, formatted from geolocate_nodes()
        n_points: int
            Number of points to represent on the output line
            
    Returns: 
        GeoDataframe with start/end nodes and lats/lons
    """
    
    logger.info("Geolocating lines")
    
    trn = load_line_data(cost_line_expansion_xlsx)
    
    lats_lookup = dict(zip(nodes['NODE'], nodes['LATITUDE']))
    lons_lookup = dict(zip(nodes['NODE'], nodes['LONGITUDE']))
    data_to_expand = zip(trn["FROM"].to_list(), trn["TO"].to_list())
    
    data = []
    for from_region, to_region in data_to_expand:
        try:
            data.append(
                add_pts_to_line(
                    lons_lookup[from_region],
                    lats_lookup[from_region],
                    lons_lookup[to_region],
                    lats_lookup[to_region],
                    n_points,
                    f"TRN{from_region}{to_region}"
                )
            )
        except KeyError:
            logger.debug(f"Can not find {from_region} and/or {to_region} in node data")
    return gpd.GeoDataFrame(data, columns=["TECHNOLOGY", "geometry"])

def get_regions(
    input_data: Dict[str, pd.DataFrame],
    countries_only: bool = False,
) -> List[str]:
    """Gets all region codes"""
    
    def filter_region_codes(df:pd.DataFrame) -> list:
        techs = df.loc[
            (df["VALUE"].str.startswith("PWR")) &
            ~(df["VALUE"].str.startswith("PWRTRN"))]
        regions = techs["VALUE"].str[-7:-2]
        return regions.drop_duplicates().to_list()
    
    region_data = filter_region_codes(input_data["TECHNOLOGY"])
    if countries_only:
        return list(set([x[0:3] for x in region_data]))
    else:
        return region_data

def create_dropdown_options(options: List[str]) -> List[Dict[str,str]]:
    """Creates label name map for dropdown"""
    try:
        return [{"label":const.TECHS_CONFIG[x]["nicename"], "value":x} for x in options]
    except KeyError:
        return[{"label":x, "value":x} for x in options]

def get_transmission_lines(input_data: Dict[str, pd.DataFrame]) -> List[str]:
    """Gets names of all transmission lines in the model"""
    techs = input_data["TECHNOLOGY"]
    lines = get_transmission_techs(techs, column="VALUE")
    return lines["VALUE"].unique()

def get_transmission_techs(df: pd.DataFrame, column:str = "TECHNOLOGY") -> pd.DataFrame:
    """Filters out only the transmission technologies"""
    return df.loc[df[column].str.startswith("TRN")].reset_index(drop=True)

def get_generation_techs(df: pd.DataFrame, column:str = "TECHNOLOGY") -> pd.DataFrame:
    """Filters out only power generation technologies"""
    return df.loc[
        (df[column].str.startswith("PWR")) & 
        ~(df[column].str.startswith("PWRTRN"))].reset_index(drop=True)

def get_mining_techs(df: pd.DataFrame, column:str = "TECHNOLOGY") -> pd.DataFrame:
    """Filters out only power generation technologies"""
    return df.loc[df[column].str.startswith("MIN")].reset_index(drop=True)

def parse_pwr_codes(df: pd.DataFrame) -> pd.DataFrame:
    """Strips out country/region/category tags from pwr codes"""

    def sort_columns(df: pd.DataFrame) -> pd.DataFrame:
        for column in ("REGION", "COUNTRY", "REGION_CODE", "CATEGORY"):
            data = df.pop(column)
            df.insert(0, column, data)
        return df
    
    if not df.empty:
        df = df.drop(columns=["REGION"])
        df["CATEGORY"] = df["TECHNOLOGY"].str[3:6]
        df["REGION_CODE"] = df["TECHNOLOGY"].str[6:11]
        df["COUNTRY"] = df["TECHNOLOGY"].str[6:9]
        df["REGION"] = df["TECHNOLOGY"].str[9:11]
        df = df.drop(columns=["TECHNOLOGY"])
        df = sort_columns(df)
    else:
        logger.info("Empty pwr codes dataframe")
        df = df.drop(columns=["REGION", "TECHNOLOGY"])
        columns = list(df)
        columns.insert(0, "CATEGORY")
        columns.insert(0, "REGION_CODE")
        columns.insert(0, "COUNTRY")
        columns.insert(0, "REGION")
        df = pd.DataFrame(columns=columns)
    return df

def parse_min_codes(df: pd.DataFrame) -> pd.DataFrame:
    """Strips out country/category tags from min codes"""

    def sort_columns(df: pd.DataFrame) -> pd.DataFrame:
        for column in ("COUNTRY", "REGION_CODE", "CATEGORY"):
            data = df.pop(column)
            df.insert(0, column, data)
        return df
    
    if not df.empty:
        df = df.drop(columns=["REGION"])
        df["CATEGORY"] = df["TECHNOLOGY"].str[3:6]
        df["COUNTRY"] = df["TECHNOLOGY"].str[6:9]
        df["REGION_CODE"] = df["TECHNOLOGY"].str[6:9]
        df = df.drop(columns=["TECHNOLOGY"])
        df = sort_columns(df)
    else:
        logger.info("Empty min codes dataframe")
        df = df.drop(columns=["REGION", "TECHNOLOGY"])
        columns = list(df)
        columns.insert(0, "CATEGORY")
        columns.insert(0, "COUNTRY")
        columns.insert(0, "REGION_CODE")
        df = pd.DataFrame(columns=columns)
    return df

def parse_fuel_codes(df: pd.DataFrame) -> pd.DataFrame:
    """Parses fuel codes into seperate columns"""
    def sort_columns(df: pd.DataFrame) -> pd.DataFrame:
        for column in ("REGION", "COUNTRY", "REGION_CODE", "CATEGORY"):
            data = df.pop(column)
            df.insert(0, column, data)
        return df
    
    df = df.loc[df["FUEL"].str[-2:]=="02"]
    if not df.empty:
        df = df.drop(columns=["REGION"])
        df["CATEGORY"] = df["FUEL"].str[0:3]
        df["REGION_CODE"] = df["FUEL"].str[3:8]
        df["COUNTRY"] = df["FUEL"].str[3:6]
        df["REGION"] = df["FUEL"].str[6:8]
        df = df.drop(columns=["FUEL"])
        df = sort_columns(df)
    else:
        logger.info("Empty fuel codes dataframe")
        df = df.drop(columns=["REGION", "TECHNOLOGY"])
        columns = list(df)
        columns.insert(0, "REGION")
        columns.insert(0, "COUNTRY")
        columns.insert(0, "REGION_CODE")
        columns.insert(0, "CATEGORY")
        df = pd.DataFrame(columns=columns)
    return df
    
def plot_by_region(
    df: pd.DataFrame, 
    plot_type: str, 
    x: str,
    y: str,
    color: str,
    plot_theme: str = "plotly",
    **kwargs
) -> Union[px.bar, px.line, px.area]:
    """Plots a chart based on geography filtered data"""
    
    if plot_type == "Bar (Grouped)":
        return px.bar(df, x=x, y=y, color=color, barmode='group', template=plot_theme, **kwargs)
    elif plot_type == "Bar (Stacked)":
        return px.bar(df, x=x, y=y, color=color, template=plot_theme, **kwargs)
    elif plot_type == "Line":
        return px.line(df, x=x, y=y, color=color, template=plot_theme, **kwargs)
    elif plot_type == "Area":
        return px.area(df, x=x, y=y, color=color, template=plot_theme, **kwargs)

def plot_by_system(
    df: pd.DataFrame, 
    plot_type: str, 
    x: str,
    y: str,
    plot_theme: str = "plotly",
    **kwargs,
) -> Union[px.bar, px.line, px.area]:
    """Plots a chart based on system wide data"""

    if plot_type == "Bar (Grouped)":
        return px.bar(df, x=x, y=y, barmode='group', template=plot_theme, **kwargs)
    elif plot_type == "Bar (Stacked)":
        return px.bar(df, x=x, y=y, template=plot_theme, **kwargs)
    elif plot_type == "Line":
        return px.line(df, x=x, y=y, template=plot_theme, **kwargs)
    elif plot_type == "Area":
        return px.area(df, x=x, y=y, template=plot_theme, **kwargs)
    
def get_unique_techs(df: pd.DataFrame, parse_type: str = "PWR") -> List[str]:
    """Gets unique 3 letter tech codes
    
    Arguments:
        df: pd.DataFrame
            DataFrame to search through 
            
    Returns:
        List[str]
            Unique codes without region identifier. 
    """
    if parse_type == "PWR":
        techs = get_generation_techs(df)
    elif parse_type == "MIN":
        techs = get_mining_techs(df)
    techs["CATEGORY"] = techs["TECHNOLOGY"].str[3:6]
    return techs["CATEGORY"].unique()

def get_unique_fuels(df: pd.DataFrame) -> List[str]:
    """Gets unique 3 letter tech codes
    
    Arguments:
        df: pd.DataFrame
            DataFrame to search through 
            
    Returns:
        List[str]
            Unique codes without region identifier. 
    """
    fuels = df["FUEL"]
    return fuels.str[0:3].unique()


def filter_data(data: pd.DataFrame, region_filter_column: str, regions: List[str], years: List[int]) -> pd.DataFrame:
    """Filter data by geography and time

    Arguments:
        data: pd.DataFrame
            Data to filter
        region_filter_column: str, 
            Column to filter regions on. Must be in set ("COUNTRY", "REGION")
        regions: List[str]
            Regions to filter over
        years: List[int]
            years to filter over
    """
    
    if len(years) == 1:
        return data.loc[
                (data[region_filter_column].isin(regions)) &
                (data["YEAR"] == years[0])
            ]
    else:
        return data.loc[
                (data[region_filter_column].isin(regions)) &
                (data["YEAR"].isin(range(years[0],(years[-1]+1))))
            ]

def group_data(data: pd.DataFrame, groupby_columns: List[str], groupby_method: str) -> pd.DataFrame:
    """Aggregates data based on spatial scope
    
    Arguments:
        data: pd.DataFrame
            Data to filter
        groupby_columns = List[str]
            columns to group on 
    """
    if groupby_method == "sum":
        return data.groupby(by=groupby_columns).sum(numeric_only=True).reset_index()
    elif groupby_method == "mean":
        return data.groupby(by=groupby_columns).mean(numeric_only=True).reset_index()
    else:
        logger.debug(f"{groupby_method} is not valid. Returning empty dataframe")
        return pd.DataFrame()

def plot_data(
    data: pd.DataFrame,
    countries: List[str],
    regions: List[str],
    plot_theme: str,
    geographic_scope: str,
    years: List[int], 
    plot_type: str,
    parameter: str,
    tech_fuel_filter: str,
    config: Dict[str,Dict],
    div_id: str,
) -> html.Div:
    """Generic function for plotting data"""
    
    # Mining techs need modified country labels 
    min_flag = False
    
    # parse input data codes 
    if config[parameter]["groupby"] == "TECHNOLOGY":
        
        if config[parameter]["filterby"] == "PWR":
            data = get_generation_techs(data)
            data = parse_pwr_codes(data)
            
        elif config[parameter]["filterby"] == "MIN":
            data = get_mining_techs(data)
            data = parse_min_codes(data)
            min_flag = True
            
            # Mining not tracked at regional level 
            if geographic_scope == "Region":
                geographic_scope = "Country"
                
        else:
            logger.debug(
                f"filterby for {parameter} is {config[parameter]['filterby']}")
            
        if tech_fuel_filter != "all":
            data = data.loc[data["CATEGORY"] == tech_fuel_filter]
            
    elif config[parameter]["groupby"] == "FUEL":
        data = parse_fuel_codes(data)
        if tech_fuel_filter != "all":
            data = data.loc[data["CATEGORY"] == tech_fuel_filter]
    else: # no further processing needed
        data = data

    # determine filetering options 
    if geographic_scope == "Country":
        region_filter_column = "COUNTRY"
        region_filters = countries
        plot_color = "COUNTRY"
        groupby_columns = ["CATEGORY", region_filter_column, config[parameter]["xaxis"]]
        if tech_fuel_filter != "all":
            groupby_columns = ["CATEGORY", region_filter_column, config[parameter]["xaxis"]]
        else: 
            groupby_columns = [region_filter_column, config[parameter]["xaxis"]]
    elif geographic_scope == "Region":
        region_filter_column = "REGION_CODE"
        region_filters = regions
        plot_color = "REGION_CODE"
        if tech_fuel_filter != "all":
            groupby_columns = ["CATEGORY", region_filter_column, config[parameter]["xaxis"]]
        else: 
            groupby_columns = [region_filter_column, config[parameter]["xaxis"]]
    else: # system level
        region_filter_column = "REGION_CODE"
        region_filters = regions
        groupby_columns = ["CATEGORY", config[parameter]["xaxis"]]
        color_map = get_color_codes()
        if tech_fuel_filter != "all":
            plot_color = config[parameter]["groupby"]
        else: 
            plot_color = "CATEGORY"
        
    groupby_method = config[parameter]["groupby_method"]
    
    if min_flag:
        region_filters = countries
        region_filters.append("INT")
    
    # get regional and temporal filtered dataframe 
    filtered_data = filter_data(
        data = data,
        region_filter_column = region_filter_column,
        regions = region_filters, 
        years = years
    )

    if filtered_data.shape[0] == 0:
        return html.Div("No Data Selected")
    
    # aggregate data
    grouped_data = group_data(data=filtered_data, groupby_columns=groupby_columns, groupby_method=groupby_method)
    
    # plot data
    if geographic_scope in ["Country", "Region"]:
        fig = plot_by_region(
            df=grouped_data,
            plot_type=plot_type,
            x=config[parameter]["xaxis"],
            y="VALUE",
            color=plot_color,
            plot_theme=plot_theme,
            labels={"VALUE":config[parameter]["ylabel"]}
        )
    else:
        if tech_fuel_filter != "all":
            fig = plot_by_system(
                df=grouped_data,
                plot_type=plot_type,
                x=config[parameter]["xaxis"],
                y="VALUE",
                plot_theme=plot_theme,
                labels={"VALUE":config[parameter]["ylabel"]}
            )
        else:
            fig = plot_by_system(
                df=grouped_data,
                plot_type=plot_type,
                x=config[parameter]["xaxis"],
                y="VALUE",
                color=plot_color,
                color_discrete_map=color_map,
                plot_theme=plot_theme,
                labels={"VALUE":config[parameter]["ylabel"]}
            )

    return html.Div(children=[dcc.Graph(figure=fig)], id=div_id)

def add_default_values(
    df: pd.DataFrame, 
    column: str, 
    default_indices: List[Union[str, int]],
    default_value: Union[int, float],
) -> pd.DataFrame:
    """Adds default values to populate dataframe
    
    This function is useful for plotting purposes. For example, if a timeslice
    has no production, we want to display that as zero, not as a skipped row. 
    """
    
    indices = {x:df[x].unique() for x in list(df) if x not in [column, "VALUE"]}
    indices[column] = default_indices
    
    # Create template default data 
    if len(indices) > 1:
        new_index = pd.MultiIndex.from_product(
            list(indices.values()), names=list(indices.keys())
        )
    else:
        new_index = pd.Index(
            list(indices.values())[0], name=list(indices.keys())[0]
        )
    df_default = pd.DataFrame(index=new_index)
    df_default["VALUE"] = default_value
    df_default = df_default.reset_index()

    # combine result and default value dataframe
    df = pd.concat([df, df_default])
    df = df.drop_duplicates(subset=[x for x in indices])
    df = df.sort_values(by=[column])
    
    return df.reset_index(drop=True)

def get_production_by_mode(df: pd.DataFrame, year_split: pd.DataFrame, annual: bool = False) -> pd.DataFrame:
    """Gets production by technology by mode values
    
    Arguments:
        df: pd.DataFrame
            RateOfProductionByTechnologyByMode dataframe
        year_split: pd.Dataframe
            YearSplit dataframe    
        annual: bool
            Return ProductionByTechnologyByMode or ProductionByTechnologyByModeAnnual
    
    From the formulation
    
    r~REGION, l~TIMESLICE, t~TECHNOLOGY, f~FUEL, y~YEAR,
    sum{m in MODE_OF_OPERATION: OutputActivityRatio[r,t,f,m,y] <> 0}
        RateOfActivity[r,l,t,m,y] * OutputActivityRatio[r,t,f,m,y]
        * YearSplit[l,y] ~VALUE;
    """
    
    df = df.set_index(["REGION", "TIMESLICE", "TECHNOLOGY", "MODE_OF_OPERATION", "FUEL", "YEAR"])
    year_split = year_split.set_index(["TIMESLICE","YEAR"])
    
    data = df.mul(year_split, fill_value=0.0)

    if annual:
        return data.groupby(by=["REGION", "TECHNOLOGY", "MODE_OF_OPERATION", "FUEL", "YEAR"]).sum().reset_index()
    else:
        return data.reset_index()
    
    
############################################################################
## THESE ARE COPY/PASTE FROM VISULIZATION.UTILS TO GET AROUND IMPORT ISSUES
## FIX IMPORTS THEN DELETE THIS SECTION
############################################################################

def load_node_data_demand_center(cost_line_expansion_xlsx: str) -> pd.DataFrame:
    """Gets node names with lats and lons at demand center
    
    Arguments:
        cost_line_expansion_xlsx: str
            Path to 'Costs Line expansion.xlsx' file  
            
    Returns: 
        Dataframe with nodes and lats and lons
    """
    
    def parse_name(x: str) -> str:
        parts = x.split("-")
        if len(parts) > 2:
            return f"{parts[1]}{parts[2]}"
        else:
            return f"{parts[1]}XX"
        
    raw = pd.read_excel(cost_line_expansion_xlsx, sheet_name='Centerpoints')
    df = pd.DataFrame()
    
    df["NODE"] = raw["Node"].map(lambda x: parse_name(x))
    df["LATITUDE"] = raw["Latitude"]
    df["LONGITUDE"] = raw["Longitude"]
    
    # drop extra brazil codes 
    df = df.loc[
        (df["NODE"] != "BRAJ1") &
        (df["NODE"] != "BRAJ2") &
        (df["NODE"] != "BRAJ3")].reset_index(drop=True)
    
    return df

def load_node_data_centroid(plexos_world_softlink_xlsx: str) -> pd.DataFrame:
    """Gets node names with lats and lons at centroid
    
    Arguments:
        plexos_world_softlink_xlsx: str
            Path to 'PLEXOS_World_MESSAGEix_GLOBIOM_Softlink.xlsx' file  
            
    Returns: 
        Dataframe with nodes and lats and lons
    """
    
    def parse_name(x: str) -> str:
        parts = x.split("-")
        if len(parts) > 2:
            return f"{parts[1]}{parts[2]}"
        else:
            return f"{parts[1]}XX"
        
    raw = pd.read_excel(plexos_world_softlink_xlsx, sheet_name='Attributes')
    temp = raw.loc[raw["class"] == "Node"]

    temp = temp.loc[
        (temp["name"] != "SA-BRA-J1") &
        (temp["name"] != "SA-BRA-J2") &
        (temp["name"] != "SA-BRA-J3")]
    
    temp["NODE"] = temp["name"].map(lambda x: parse_name(x))
    
    df_lats = temp.loc[temp["attribute"] == "Latitude"]
    df_lons = temp.loc[temp["attribute"] == "Longitude"]
    
    lats = dict(zip(df_lats["NODE"], df_lats["value"]))
    lons = dict(zip(df_lons["NODE"], df_lons["value"]))
    
    return pd.DataFrame(
        [[x, lats[x], lons[x]] for x in temp["NODE"].unique().tolist()],
        columns=["NODE", "LATITUDE", "LONGITUDE"])

def load_line_data(cost_line_expansion_xlsx: str) -> pd.DataFrame:
    """Gets line names with to/from nodes
    
    Arguments:
        cost_line_expansion_xlsx: str
            Path to 'Costs Line expansion.xlsx' file  
    
    Returns:
        pd.DataFrame     
    """
    def parse_transmission_codes(techs: List[str]) -> pd.DataFrame:
        """Parses transmission techs to add start/end info"""
        
        parsed_data = []
        for tech in techs:
            parsed_data.append([
                tech,
                tech[3:8],
                tech[8:]
            ])
        return pd.DataFrame(parsed_data, columns=["TECHNOLOGY", "FROM", "TO"])
    
    # get all transmission lines
    raw = pd.read_excel(cost_line_expansion_xlsx, sheet_name='Interface')
    trn = raw.dropna(subset=["From"])
    trn = format_transmission_name(trn)
    
    # drop extra brazil codes 
    trn = trn.loc[
        (trn["TECHNOLOGY"].str[3:8] != "BRAJ1") &
        (trn["TECHNOLOGY"].str[3:8] != "BRAJ2") &
        (trn["TECHNOLOGY"].str[3:8] != "BRAJ3") &
        (trn["TECHNOLOGY"].str[8:] != "BRAJ1") &
        (trn["TECHNOLOGY"].str[8:] != "BRAJ2") &
        (trn["TECHNOLOGY"].str[8:] != "BRAJ3")].reset_index(drop=True)
    
    return parse_transmission_codes(trn["TECHNOLOGY"].to_list())

def format_transmission_name(df):
    # If from column has length 6 then it's the last three chars plus XX
    df.loc[df["From"].str.len() == 6, "From"] = (df["From"].str[3:6] + "XX")

    # If from column has length 9 then it's the 3:6 and 7:9 three chars plus XX
    df.loc[df["From"].str.len() == 9, "From"] = (
        df["From"].str[3:6] + df["From"].str[7:9])

    # If to column has length 6 then it's the last three chars plus XX
    df.loc[df["To"].str.len() == 6, "To"] = (df["To"].str[3:6] + "XX")

    # If to column has length 9 then it's the 3:6 and 7:9 three chars plus XX
    df.loc[df["To"].str.len() == 9, "To"] = (
        df["To"].str[3:6] + df["To"].str[7:9])

    # Combine From and To columns.
    df["TECHNOLOGY"] = ("TRN" + df["From"] + df["To"])

    # Drop to and from columns
    df = df.drop(["From", "To"], axis=1)

    return df

def get_color_codes() -> Dict:
    """Get color naming dictionary.
    
    Return:
        Dictionary with tech and color name map
    """
    try:
        config_paths = ConfigPaths()
        input_data_dir = config_paths.input_data_dir
    except FileNotFoundError:
        input_data_dir = str(Path("resources", "data"))
    name_colour_codes = pd.read_csv(os.path.join(input_data_dir,
                                                'color_codes.csv'
                                                ),
                                   encoding='latin-1')

    # Get colour mapping dictionary
    color_dict = dict([(n, c) for n, c
                   in zip(name_colour_codes.tech_id,
                          name_colour_codes.colour)])
    return color_dict