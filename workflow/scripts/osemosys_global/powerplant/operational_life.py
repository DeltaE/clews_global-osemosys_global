"""Function to set operational life."""

import pandas as pd

from utils import apply_dtypes

def set_op_life(tech_code_dict, df_iar_final, df_oar_final, 
                op_life_dict, region_name):

    # Create Operational Life data
    tech_code_dict_reverse = dict((v,k) for k,v in tech_code_dict.items())
    op_life_techs = list(set(list(df_iar_final['TECHNOLOGY'].unique()) + list(df_oar_final['TECHNOLOGY'].unique())))
    op_life_pwr = [tech for tech in op_life_techs if (tech[0:3] == 'PWR') and (len(tech) == 13)]
    
    op_life_out = []
    
    # power generation technologies 
    for op_life_tech in op_life_pwr:
        op_life_tech_name = tech_code_dict_reverse[op_life_tech[3:6]]
        op_life_out.append([
            region_name, 
            op_life_tech,
            op_life_dict[op_life_tech_name]])
        
    op_life_base = pd.DataFrame(op_life_out, columns = ['REGION', 'TECHNOLOGY', 'VALUE'])

    op_life_base = apply_dtypes(op_life_base, "OperationalLife")
        
    return op_life_base