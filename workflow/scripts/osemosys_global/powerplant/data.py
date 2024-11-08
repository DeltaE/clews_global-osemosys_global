"""Functions to extract and format relevent data."""

import pandas as pd
from datetime import datetime
import logging

from constants import (
    NODES_EXTRA_LIST,
    AVG_CSP_EFF,
    AVG_URN_EFF
)

def get_years(start: int, end: int) -> range:
    return range(start, end + 1)

def set_generator_table(plexos_prop: pd.DataFrame, plexos_memb: pd.DataFrame, 
                        op_life_dict: dict[str, int], tech_code_dict: dict[str, str],
                        start_year: int, end_year: int) -> pd.DataFrame:
    """Sets the main generator table derived from the PLEXOS-World model.    
    """

    # Create main generator table
    gen_cols_1 = ["child_class", "child_object", "property", "value"]
    df_gen = plexos_prop.copy()[gen_cols_1]
    
    df_gen = df_gen[df_gen["child_class"] == "Generator"]
    df_gen.rename(columns={"child_object": "powerplant"}, inplace=True)
    df_gen.drop("child_class", axis=1, inplace=True)
    df_gen = pd.pivot_table(df_gen,
                            index="powerplant",
                            columns="property",
                            values="value",
                            aggfunc='sum',
                            fill_value=0,
                           )
    df_gen["total_capacity"] = (df_gen["Max Capacity"].astype(float)) * (
        df_gen["Units"].astype(int)
    )

    gen_cols_base = ["Commission Date", "Heat Rate", "Max Capacity", "total_capacity"]
    df_gen_base = df_gen[gen_cols_base]

    df_dict = plexos_memb[plexos_memb["parent_class"] == "Generator"].rename(
        {"parent_object": "powerplant"}, axis=1
        )

    ## Compile dataframe with powerplants, nodes, and fuels
    df_dict_fuel = df_dict[df_dict["collection"] == "Fuels"]
    df_dict_fuel = df_dict_fuel[["powerplant", "child_object"]]
    df_dict_nodes = df_dict[df_dict["collection"] == "Nodes"]
    df_dict_nodes = df_dict_nodes[["powerplant", "child_object"]]
    df_dict_2 = pd.merge(df_dict_fuel, df_dict_nodes, how="outer", on="powerplant")
    
    
    ## Merge original generator dataframe with nodes and fuels
    df_gen_base = pd.merge(df_gen_base, df_dict_2, how="outer", on="powerplant")
    df_gen_base.rename(
        {"child_object_x": "fuel", "child_object_y": "node"}, axis=1, inplace=True
    )
    
    ## Extract start year from Commission Date
    df_gen_base["Commission Date"] = (pd.to_timedelta(df_gen_base["Commission Date"].astype(int),
                                                unit='d') + 
                               datetime(1900, 1, 1))
    
    df_gen_base["start_year"] = df_gen_base["Commission Date"].dt.year
    df_gen_base.drop("Commission Date", axis=1, inplace=True)
    
    ## Calculate efficiency from heat rate. Units of heat rate in MJ/kWh
    df_gen_base["efficiency"] = 3.6 / df_gen_base["Heat Rate"].astype(float)
    df_gen_base.drop("Heat Rate", axis=1, inplace=True)
    
    ## Calcluate years of operation from start year
    df_gen_base["years_of_operation"] = start_year - df_gen_base["start_year"]
    
    ## Fix blank spaces in 'fuels' columns. Appearing for 'Oil' powerplants in certain countries
    df_gen_base.loc[df_gen_base["fuel"].isna(), "fuel"] = (
        df_gen_base["node"].str.split("-").str[:2].str.join("-")
        + " "
        + df_gen_base["powerplant"].str.split("_", expand=True)[1]
    )

    ## Create column for technology
    df_gen_base["technology"] = df_gen_base["powerplant"].str.split("_").str[1]
    df_gen_base["technology"] = df_gen_base["technology"].str.title()

    ## Divide Gas into CCGT and OCGT based on max capacity
    df_gen_base.loc[
        (df_gen_base["technology"] == "Gas") & (df_gen_base["Max Capacity"].astype(float) > 130),
        "technology",
    ] = "Gas-CCGT"
    df_gen_base.loc[
        (df_gen_base["technology"] == "Gas") & (df_gen_base["Max Capacity"].astype(float) <= 130),
        "technology",
    ] = "Gas-OCGT"

    # Create table with aggregated capacity  
    df_gen_agg_node = df_gen_base[df_gen_base['start_year']<=start_year]
    df_gen_agg_node = df_gen_agg_node.groupby(['node', 'technology'], 
                                              as_index=False)['total_capacity'].sum()
    df_gen_agg_node = df_gen_agg_node.pivot(index='node', 
                                            columns='technology', 
                                            values='total_capacity').fillna(0).reset_index()

    df_gen_agg_node.drop('Sto', axis=1, inplace=True) # Drop 'Sto' technology. Only for USA.
        
    nodes_extra_df = pd.DataFrame(columns=['node'])
    
    nodes_extra_df['node'] = NODES_EXTRA_LIST

    df_gen_agg_node = pd.concat(
        [df_gen_agg_node,nodes_extra_df],
        ignore_index=True,
        sort=False,
    ).fillna(0).sort_values(by='node').set_index('node').round(2)

    # Add region and country code columns
    df_gen_base['region_code'] = df_gen_base['node'].str[:2]
    df_gen_base['country_code'] = df_gen_base['node'].str[3:]

    df_gen_base['operational_life'] = df_gen_base['technology'].map(op_life_dict)
    df_gen_base['retirement_year_data'] = (df_gen_base['operational_life'] 
                                        + df_gen_base['start_year'])
    df_gen_base['retirement_diff'] = ((df_gen_base['years_of_operation'] 
                                   - df_gen_base['operational_life'])/
                                   df_gen_base['operational_life'])

    ''' Set retirement year based on years of operation. 
    If (years of operation - operational life) is more than 50% of 
    operational life, set retirement year
    '''
    df_gen_base.loc[df_gen_base['retirement_diff'] >= 0.5, 
                 'retirement_year_model'] = 2028
    df_gen_base.loc[(df_gen_base['retirement_diff'] < 0.5) &
                 (df_gen_base['retirement_diff'] > 0), 
                 'retirement_year_model'] = 2033
    df_gen_base.loc[df_gen_base['retirement_diff'] <= 0, 
                 'retirement_year_model'] = df_gen_base['retirement_year_data']

    df_gen_base['tech_code'] = df_gen_base['technology'].map(tech_code_dict)

    df_gen_base.loc[df_gen_base['node'].str.len() <= 6, 
                 'node_code'] = (df_gen_base['node'].
                                 str.split('-').
                                 str[1:].
                                 str.join("") +
                                 'XX')
    df_gen_base.loc[df_gen_base['node'].str.len() > 6, 
                 'node_code'] = (df_gen_base['node'].
                                 str.split('-').
                                 str[1:].
                                 str.join("")
                                )

    df_gen_base = df_gen_base.loc[~df_gen_base['tech_code'].isna()]
    
    return df_gen_base

def average_efficiency(df_gen_base):

    # ### Calculate average InputActivityRatio by node+technology and only by technology
    df_eff = df_gen_base[['node_code',
                       'efficiency',
                       'tech_code']]
    
    # Change IAR for CSP value taken from PLEXOS
    df_eff.loc[df_eff['tech_code']=='CSP', 'efficiency'] = AVG_CSP_EFF
    
    # Change IAR for URN value taken from PLEXOS
    df_eff.loc[df_eff['tech_code']=='URN', 'efficiency'] = AVG_URN_EFF
    
    # Average efficiency by node and technology
    df_eff_node = df_eff.groupby(['tech_code',
                                  'node_code'],
                                 as_index = False).mean()
    
    df_eff_node['node_average_iar'] = ((1 / df_eff_node['efficiency']).
                                       round(2))
    
    df_eff_node.drop('efficiency', 
                     axis = 1, 
                     inplace = True)
    
    # Average efficiency by technology
    df_eff_tech = df_eff.drop(columns="node_code").groupby('tech_code', as_index = False).mean()
    
    df_eff_tech['tech_average_iar'] = ((1 / df_eff_tech['efficiency']).
                                       round(2))
    
    df_eff_tech.drop('efficiency', 
                     axis = 1, 
                     inplace = True)

    return df_eff_node, df_eff_tech

def create_pwr_techs(df_in, techs):
    """Formats power generation technology name
    
    Adds a 'TECHNOLOGY' column to a dataframe with formatted power 
    generation technology (PWR) names. Names are formatted so the suffix 
    for plants in the 'techs' argument list will have 00, while everything 
    else will have an 01 suffix

    Arguments: 
        df_in = dataframe with a 'tech_codes' and 'node_codes' column
        tList = List of technology triads to have 00 suffix [CCG, HYD, ...]
    
    Returns: 
        df_out = same dataframe as df_in, except with a 'TECHNOLOGY' column added 
        to the end 
    
    Example:
        df_in['tech_code'] = ('CCG', SPV, 'OCG', 'HYD')
        df_in['node_code'] = ('AGOXX', AGOXX, 'INDNP', 'INDNP')
        df_out = createPwrTechs(df_in, ['CCG', 'OCG'])
        df_out['TECHNOLOGY'] = [PWRCCGAFGXX00, PWRSPVAFGXX01, PWROCGINDNP00, PWRHYDINDNP01]
    """
    df_out = df_in.copy()
    for t in techs:
        df_out.loc[df_out['tech_code'] == t, 'tech_suffix'] = '00'
    df_out['tech_suffix'] = df_out['tech_suffix'].fillna('01')
    df_out['TECHNOLOGY'] = ('PWR' + 
                            df_out['tech_code'] + 
                            df_out['node_code'] + 
                            df_out['tech_suffix']
                            )
    df_out = df_out.drop('tech_suffix', axis = 1)
    return df_out

def duplicate_plexos_techs(df_in, techs):
    """Creates new technologies to replace PLEXOS technolgoies.
    
    New technologies will end in '01', while historical ones end in '00'
    
    Arguments: 
        df_in = dataframe in otoole and og formatting with a TECHNOLOGY column
        techs = List of technology triads to duplicate [CCG, HYD, ...]
    
    Returns: 
        df_out = dataframe with same columns as df_in. All tech names that include
        techs values will be returned with updated naming. Remaining technologies 
        are deleted 
    
    Example:
        df_out = duplicatePlexosTechs(df_in, ['CCG', 'OCG'])
        df_in['TECHNOLOGY'] = [PWRCCGAFGXX01, PWROCGAFGXX01, PWRHYDAFGXX01]
        df_out['TECHNOLOGY'] = [PWRCCGAFGXX02, PWROCGAFGXX02]
    """
    df_out = df_in.copy()
    df_out = df_out.loc[(df_out['TECHNOLOGY'].str[3:6].isin(techs)) & 
                        ~(df_out['TECHNOLOGY'].str.startswith('MIN'))]
    df_out['TECHNOLOGY'] = df_out['TECHNOLOGY'].str.slice_replace(start=11,
                                                                  stop=13,
                                                                  repl='01')
    return df_out

def new_iar(df_in, tech, new_iar_ccg, 
           new_iar_ocg, new_iar_coa, new_iar_default):
    """Replaces the input activity ratio value with a hardcoded value 

    Arguments: 
        df = dataframe with a 'TECHNOLOGY' and 'VALUE' column
        tech = technology to replace iar for (CCG, HYD, SPV...)
    
    Returns: 
        df_out = same dataframe as df_in with a new values in 'VALUE'
    
    Example:
        df_out = newIar(df_in, 'CCG')
        df_out['TECHNOLOGY'] = [PWRCCGINDNP01, PWRCCGINDNW01]
        df_out['VALUE'] = [2, 2]
    """

    df_out = df_in.loc[df_in['TECHNOLOGY'].str[3:6] == tech]
    if tech == 'CCG':
        iar = new_iar_ccg
    elif tech == 'OCG':
        iar = new_iar_ocg
    elif tech == 'COA':
        iar = new_iar_coa
    else: 
        logging.warning(f'Default IAR used for new {tech} power plants')
        iar = new_iar_default
    df_out.loc[:,'VALUE'] = round(1/iar, 3)
    
    return df_out

def get_max_value_per_technology(df):
    """Gets the max value for each unique technology in a dataframe.

    This function will search through a 'TECHNOLOGY' column to identify each
    unique technology. The input dataframe will be filtered based on each
    unique technology and only keep one datapoint per technology - the
    datapoint cooresponding to the max value in the 'VALUE' column.

    Args:
        df: Dataframe with at minimum a 'TECHNOLOGY' and 'VALUE' columns

    Returns:
        df: Filtered dataframe giving max values per technology.
    """

    # Get list of techs to filter over
    techs = df["TECHNOLOGY"].unique().tolist()

    # output list to hold filtered data
    out_data = []

    # perform filtering
    for tech in techs:
        # for tech in ['PWRHYDCHNJS01']:
        df_tech_filter = df.loc[df["TECHNOLOGY"] == tech]
        df_value_filter = df_tech_filter.loc[
            df_tech_filter["VALUE"] == df_tech_filter["VALUE"].max()
        ].reset_index(drop=True)
        df_value_filter = df_value_filter.drop_duplicates(subset=["VALUE"])
        value_filter_data = df_value_filter.values.tolist()
        out_data.append(value_filter_data[0])

    # setup dataframe to return
    df_out = pd.DataFrame(out_data, columns=list(df))
    return df_out