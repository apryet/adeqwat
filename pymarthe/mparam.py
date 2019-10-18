"""
Contains the MartheModel class
Designed for structured grid and
layered parameterization

"""
import os 
import numpy as np
from matplotlib import pyplot as plt 
from .utils import marthe_utils
from .utils import pest_utils
from .utils import pp_utils
import pandas as pd 
import pyemu

# ---  formatting

# NOTE : layer are written with 1-base format, unsigned zone for zpc
# name format zones of piecewise constancy
# example: kepon_l02_zpc03
ZPCFMT = lambda name, lay, zone: '{0}_l{1:02d}_zpc{2:02d}'.format(name,int(lay+1),int(abs(zone)))

# float and integer formats
FFMT = lambda x: "{0:<20.10E} ".format(float(x))
IFMT = lambda x: "{0:<10d} ".format(int(x))

# columns for pilot point df
PP_NAMES = ["name","x","y","zone","value"]

# string format
def SFMT(item):
    try:
        s = "{0:<20s} ".format(item.decode())
    except:
        s = "{0:<20s} ".format(str(item))
    return s

# name format for pilot points files  
PP_FMT = {"name": SFMT, "x": FFMT, "y": FFMT, "zone": IFMT, "tpl": SFMT, "value": FFMT}

class MartheParam() :
    """
    Class for handling Marthe parameters

    Parameters
    ----------
    name : str
        parameter name 
    default_value : int or np.array with shape (nlay,nrow,ncol)
        default values
    izone : (optional) array with shape (nlay,nrow,ncol))

    Examples
    --------
    """
    def __init__(self, mm, name, default_value, izone = None, array = None) :
        self.mm = mm # pointer to the instance of MartheModel
        self.name = name # parameter name
        self.array = mm.grids[self.name] # pointer to grid in MartheModel instance
        self.default_value = default_value 
        self.set_izone(izone)
      
    def set_izone(self,izone = None):
        """
        Set izone 3D array (nlay, nrow, ncol) of integer
        Former izone data for given parameter will be reset.

        Where mm.imask values are 0, izone data are fixed to 0

        izone value < 0, zone of piecewise constancy
        izone value > 0, zone with pilot points
        izone value = 0 for inactive cells

        If data is None, a single constant zone (-1) per layer is considered.

        Parameters
        ----------
        izone : None, int or np array of int, shape (nlay,nrow,ncol)

        Examples
        --------
        >> mm.param['kepon'].set_izone()

        >> izone = -1*np.ones( (nlay, nrow, ncol) )
        >> izone[0,:,:] = 1
        >> mm.param['kepon'].set_izone(izone)

        """
        # reset izone for current parameter from imask
        self.izone = self.mm.imask.copy()
        # index of active cells
        idx_active_cells = self.mm.imask == 1

        # case izone is not provided
        if izone is None :
            # a single zone is considered
            self.izone[idx_active_cells] = -1

        # case an izone array is provided
        elif isinstance(izone,np.ndarray) : 
            assert izone.shape == (self.mm.nlay, self.mm.nrow, self.mm.ncol) 
            # only update active cells  
            self.izone[idx_active_cells] = izone[idx_active_cells]

        # update zpc_df and pp_dic
        # this resets any modification applied to zpc_df and pp_df
        self.init_zpc_df()
        self.init_pp_dic()


    def init_pp_dic(self) :
        """
        Initialize the nested dic of pp_df
        Example format : 
        pp_dic = { 0:pp_df_0, 3:pp_df_3 }
        """
        nlay = self.mm.nlay
        self.pp_dic  = {}
      
        # append lay to pp_dic if it contains zones > 0
        for lay in range(nlay) :
            zones = np.unique(self.izone[lay,:,:])
            # number of zones > 0 
            if len( [zone for zone in zones if zone >0] ) > 0 :
                self.pp_dic[lay] = None

    def init_zpc_df(self) :
        """
        Set up dataframe of zones of piecewise constancy from izone
        """
        nlay = self.mm.nlay

        parnames = []
        parlays = []
        parzones = []

        for lay in range(nlay) :
            zones = np.unique(self.izone[lay,:,:])
            for zone in zones :
                if zone < 0 : 
                    parnames.append( ZPCFMT(self.name, lay, zone))
                    parlays.append(lay)
                    parzones.append(zone)

        self.zpc_df = pd.DataFrame({'name':parnames, 'lay':parlays, 'zone':parzones, 'value': self.default_value})
        self.zpc_df.set_index('name',inplace=True)

    def set_zpc_values(self,values) : 
        """
        Update value column inf zpc_df

        Parameters
        ---------
        values : int or dic
            if an int, is provided, the value is set to all zpc
            if a dic is provided, the value are updated accordingly
            ex :
            layer only value assignation : simple dic 
            {0:1e-2,1:2e-3,...}
            layer, zone value assignation : nested dicts
            {0:{1:1e-3,2:1e-2}} to update the values of zones 1 and 2 from the first layer. 

        Examples :
        >> # a single value is provided
        >> mm.set_zpc_values(1e-3)
        >> # layer based value assignement 
        >> mm.set_vpc_values({0:2e-3})
        >> # layer and zone assignement
        >> mm.set_zpc_values({0:{1:1e-3,2:1e-2}}
        """

        # case same value for all zones of all layers
        if isinstance(values,(int, float)) : 
            self.zpc_df['values'] = value
            return
        # if a dictionary is provided
        elif isinstance(values, dict) :
            for lay in list(values.keys()):
                # layer-based parameter assignement
                if isinstance(values[lay],(int,float)):
                    # index true for zones within lay
                    value = values[lay]
                    idx = [ name.startswith('{0}_l{1:02d}'.format(self.name,int(lay+1))) for name in self.zpc_df.index]
                    self.zpc_df.loc[idx,'value'] = value
                # layer, zone parameter assignement
                elif isinstance(values[lay],dict) : 
                    for zones in values[lay].keys() :
                        parname = ZPCFMT(self.name,lay,zone)
                        value = values[lay][zone]
                        self.zpc_df.loc[parname,'value'] = value
        else : 
            print('Invalid input, check the help')
            return

    
    def set_array(self, lay, zone, values) : 
        """
        Set parameter array for given lay and zone

        Parameters
        ----------
        lay : int
            layer, zero based 
        zone : int
            zone id (<0 or >0)
        values = int or np.ndarray
            int for zones < 0, ndarray for zone > 0 

        Example
        -------
        mm.param['kepon'].set_array(lay = 1,zone = -2, values = 12.4e-3)

        >> 
        """
        assert lay in range(self.mm.nlay), 'layer {0} is not valid.'.format(lay)
        assert zone in np.unique(self.izone), 'zone {0} is not valid'.format(zone)
        if zone < 0 :
            assert isinstance(values, float), 'A float should be provided for ZPC.'
        elif zone > 0 :
            assert isinstance(values, np.ndarray), 'An array should be provided for PP'

        # select zone 
        idx = self.izone[lay,:,:] == zone

        # update values within zone 
        self.array[lay,:,:][idx] = values

        return

    def set_array_from_zpc_df(self) :
        # check for missing values
        for lay, zone, value in zip(self.zpc_df.lay, self.zpc_df.zone, self.zpc_df.value) :
            if value is None :
                print('Parameter value is NA for ZPC zone {0} in lay {1}').format(abs(zone),int(lay)+1)
            self.set_array(lay,zone,value)

    def pp_df_from_shp(self, shp_path, lay, zone = 1, value = None , zone_field = None, value_field = None) :
        """
       Reads input shape file, builds up pilot dataframe, and insert into pp_dic 

        Parameters
        ----------
        path : full path to shp with pilot points
        lay : layer id (0-based)
        zone : zone id (>0)

        Examples
        --------
        mm.param['permh'].pp_df_from_shp('./data/points_pilotes_eponte2.shp', lay, zone)

        """
        if value is None : 
            value = self.default_value

        # init pp name prefix
        prefix = 'pp_{0}_l{1:02d}'.format(self.name,lay)
        # get data from shp and update pp_df for given layer
        # NOTE will be further extended for multi-zones
        # and allow update of current pp_d
        self.pp_dic[lay] = pp_utils.ppoints_from_shp(shp_path, prefix, zone, value, zone_field, value_field)
        
    def zone_interp_coords(self, lay, zone) :
        """
        Returns grid coordinates where interpolation
        should be performed for given lay and zone

        Parameters
        ----------
        lay: model layer (0-based)
            parameter
        zone : zone layer (>0 for pilot points)

        Examples
        --------
        x_coords, y_coords = mm.param['permh'].zone_interp_coords(lay=0,zone=1)
        
        """
        # set up index for current zone and lay

        # point where interpolation shall be conducted for current zone
        idx = self.izone[lay,:,:] == zone
        xx, yy = np.meshgrid(self.mm.x_vals, self.mm.y_vals)
        x_coords = xx[idx].ravel()
        y_coords = yy[idx].ravel()

        return(x_coords, y_coords)

    def write_zpc_tpl(self, filename = None):
        """
        Load izone array from data. 
        If data is None, a single constant zone is considered. 
        Former izone data for given parameter, will be reset. 

        Parameters
        ----------
        key : str
            filename, default value is name_zpc.tpl
            ex : permh_zpc.tpl

        """

        if filename is None : 
            filename = self.name + '_zpc.tpl'
        
        zpc_names = self.zpc_df.index

        if len(zpc_names) > 0 :
            tpl_entries = ["~  {0}  ~".format(parname) for parname in zpc_names]
            zpc_df = pd.DataFrame({'name' : zpc_names,'tpl' : tpl_entries})
            pest_utils.write_tpl_from_df(os.path.join(self.mm.mldir,'tpl',filename), zpc_df)

    def write_pp_tpl(self) : 
        """ 
        set up and write template files for pilot points
        one file per model layer

        """
        for lay in self.pp_dic.keys():
            pp_df = self.pp_dic[lay]
            tpl_filename = '{0}_pp_l{1:2d}.tpl'.format(self.name,lay+1)
            tpl_file = os.path.join(self.mm.mldir,'tpl',tpl_filename)
            tpl_entries = ["~  {0}  ~".format(parname) for parname in pp_df.index]
            pp_tpl_df = pd.DataFrame({
                'name' : pp_df.index ,
                'x': pp_df.x,
                'y': pp_df.y,
                'zone': pp_df.zone,
                'tpl' : tpl_entries
                })
            pest_utils.write_tpl_from_df(tpl_file, pp_tpl_df, columns = ["name", "x", "y", "zone", "tpl"] )

    def write_zpc_data(self, filename = None):
        """

        Parameters
        ----------
        key : str
            filename, default value is name_zpc.tpl
            ex : permh_zpc.tpl

        """

        if filename is None : 
            filename = self.name + '_zpc.dat'
        
        zpc_names = self.zpc_df.index

        if len(zpc_names) > 0 :
            f_param = open(os.path.join(self.mm.mldir,'param',filename),'w')
            f_param.write(self.zpc_df.to_string(col_space=0,
                              columns=["lay", "zone", "value"],
                              formatters={'value':FFMT},
                              justify="left",
                              header=False,
                              index=True,
                              index_names=False))

    def write_pp_df(self):
        """
        write pp_df to files
        """
        for lay in self.pp_dic.keys():
            # pointer to pp_df for current layer
            pp_df = self.pp_dic[lay]
            # set up output file 
            pp_df_filename = 'pp_{0}_l{1:02d}.dat'.format(self.name, lay+1)
            pp_df_file = os.path.join(self.mm.mldir,'param',pp_df_filename)
            # write output file 
            f_param = open(pp_df_file,'w')
            f_param.write(pp_df.to_string(col_space=0,
                              columns=["x", "y", "zone", "value"],
                              formatters=PP_FMT,
                              justify="left",
                              header=False,
                              index=True,
                              index_names=False))

    def pp_from_rgrid(self, lay, n_cell):
        '''
        Description
        -----------
        This function sets up a regular grid of pilot points 
        NOTE : current version does not handle zone 
       
        Parameters
        ----------
        lay (int) : layer for which pilot points should be placed
        zone (int) : zone of layer where pilot points should be placed 
        n_cell (int) : Number of cells between pilot points 
        x_vals (1d np.array) :  grid x coordinates 
        y_vals (1d np.array) :  grid y coordinates 
     
        Returns
        ------
        pp_x : 1d np.array pilot points x coordinates  
        pp_y : 1d np.array pilot points y coordinates 
        
        Example
        -----------
        pp_x, pp_y = pp_from_rgrid(lay, zone, n_cell)
        
        '''
        # current version does not handle zones
        zone = 1 

        izone_2d = self.izone[lay,:,:]

        x_vals = self.mm.x_vals
        y_vals = self.mm.y_vals
        xx, yy = np.meshgrid(x_vals,y_vals)

        nrow = self.mm.nrow
        ncol = self.mm.ncol
            
        rows = range(0,nrow,n_cell)
        cols = range(0,ncol,n_cell)
        
        srows, scols = np.meshgrid(rows,cols)

        pp_select = np.zeros((nrow,ncol))
        pp_select[srows,scols] = 1

        pp_select[izone_2d != zone] = 0

        pp_x  = xx[pp_select==1].ravel()
        pp_y  = yy[pp_select==1].ravel()

        # number of selected pilot points
        n_pp = len(pp_x)

        # name pilot points
        prefix = '{0}_l{1:02d}_z{2:02d}'.format(self.name,lay,zone)
        pp_names = [ '{0}_{1:03d}'.format(prefix,id) for id in range(n_pp)  ]
        
        # build up pp_df
        pp_df = pd.DataFrame({"name":pp_names,"x":pp_x,"y":pp_y, "zone":zone, "value":self.default_value})
        pp_df.set_index('name',inplace=True)
        pp_df['name'] = pp_df.index

        self.pp_dic[lay] = pp_df
        

    def read_zpc_df(self,filename = None) :
        """
        Reads dataframe with zones of piecewise constancy
        and sets self.zpc_df accordingly

        The file should be white-space-delimited, without header.
        First column : parameter name (with ZPCFMT format)
        Second column : parameter value
        Any additional column will not be considered
        ex : 
        kepon_l01_z01 0.01
        kepon_l02_z02 0.03
        ...

        Parameters
        ----------
        filename : str (optional)
            path to parameter file, default is permh_zpc.dat
            ex : permh_zpc.dat
        
        """

        if filename is None:
            filename = self.name + '_zpc.dat'

        # read dataframe
        df = pd.read_csv(os.path.join(self.mm.mldir,'param',filename), delim_whitespace=True,
                header=None,names=['name','value'], usecols=[0,1])
        df.set_index('name',inplace=True)
        
        # parse layer and zone from parameter name 
        parnames = []
        values = []
        not_found_parnames = []

        for parname in df.index :
            if parname in self.zpc_df.index : 
                parnames.append(parname)
                values.append(df.loc[parname,'value'])
            else :
                not_found_parnames.append(parname)

        # case not any parameter values found
        if len(parnames) == 0 :
            print('No parameter values could be found.\n'
            'Check compatibility with izone data.')
            return
        
        # case some parameter not found
        if len(not_found_parnames) >0 :
            print('Following names are not compatible with {0} parameter izone :\n'
            '{1}'.format(self.name, ' '.join(not_found_parnames))
                    )
        # merge new dataframe with existing zpc_df
        df = pd.DataFrame({'name':parnames, 'value':values})
        df.set_index('name', inplace=True)
        self.zpc_df = pd.merge(self.zpc_df, df, how='left', left_index=True, right_index=True)

        self.zpc_df['value'] = self.zpc_df.value_y

        self.zpc_df.drop(['value_x','value_y'],1, inplace=True)

        # check for missing parameters
        missing_parnames = self.zpc_df.index[ self.zpc_df.value == np.nan ]
        
        if len(missing_parnames) > 0 : 
            print('Following parameter values are missing in zpc parameter file:\n{0}'.format(' '.join(missing_parnames))
                    )

        return

    def read_pp_df(self):
        """
        Read pp_df for all layers and fill self.pp_dic
        """
        for lay in self.pp_dic.keys():
            # read dataframe
            filename = 'pp_{0}_l{1:02d}.dat'.format(self.name,lay+1)
            pp_file = os.path.join(self.mm.mldir,'param',filename)
            pp_df = pd.read_csv(pp_file, delim_whitespace=True,
                    header=None,names=PP_NAMES)
            #pp_df.set_index('name',inplace=True)
            # set pp_df for current layer
            self.pp_dic[lay]=pp_df


    def interp_from_factors(self):
        """
        Interpolate from pilot points df files with fac2real()
        and update parameter array
        """
        for lay in self.pp_dic.keys():
            zones = [zone for zone in np.unique(self.izone[lay,:,:]) if zone >0]
            for zone in zones : 
                # path to factor file
                kfac_filename = 'kfac_{0}_l{1:02d}.dat'.format(self.name,lay+1)
                kfac_file = os.path.join(self.mm.mldir,'param',kfac_filename)
                # fac2real
                kriged_values_df = pp_utils.fac2real(pp_file = self.pp_dic[lay] ,factors_file = kfac_file)
                # update parameter array
                idx = self.izone[lay,:,:] == zone
                # NOTE for some (welcome) reasons it seems that the order of values
                # from self.array[lay][idx] and kriged_value_df.vals do match
                self.array[lay][idx] = kriged_values_df.vals


