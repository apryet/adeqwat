"""
Contains the MartheModel class
Designed for structured grid and
layered parameterization

"""
import os 
import numpy as np

import subprocess as sp
from shutil import which
import queue 

from .utils import marthe_utils
import pandas as pd 

from .mparam import MartheParam
from .mobs import MartheObs


# ----- from PyEMU ----------------


class MartheModel():
    """
    Python wrapper for Marthe
    """
    def __init__(self,rma_path):
        """
        Parameters
        ----------
        path_to_rma : string
            The path to the Marthe rma file from which the model name 
            and working directory will be identified.

        Examples
        --------

        mm = MartheModel('/Users/john/models/model/mymodel.rma')

        """
        # initialize grids dictionary
        self.grid_keys = ['permh','kepon']
        self.grids = { key : None for key in self.grid_keys }

        # initialize parameter list 
        self.param = {}
        self.obs = {}

        # get model working directory and rma file 
        self.mldir, self.rma_file = os.path.split(rma_path)

        # get model name 
        self.mlname = self.rma_file.split('.')[0]

        # read permh data
        self.x_vals, self.y_vals, self.grids['permh'] = self.read_grid('permh')

        # get nlay nrow, ncol
        self.nlay, self.nrow, self.ncol = self.grids['permh'].shape

        # set up mask of active/inactive cells.
        # value : 1 for active cells. 0 for inactive cells
        # imask is a 3D array (nlay,nrow,ncol)
        self.imask = (self.grids['permh'] != 0).astype(int)

        # set up izone
        # similarly to self.grids, based on a dic with parameter name as key
        # values for izone arrays 3D arrays : 
        # - int, zone of piecewise constancy
        # + int, zone with pilot points
        # 0, for inactive cells
        # default value from imask, -1 zone of piecewise constancy
        self.izone = { key : -1*self.imask for key in self.grid_keys } 

        # set up pilot point data frame 
        self.pp_df = pd.DataFrame({'name': pd.Series(None, dtype=str),
            'x': pd.Series(None, dtype=np.float32),
            'y': pd.Series(None, dtype=np.float32),
            'lay': pd.Series(None, dtype=np.float32),
            'zone' : pd.Series(None, dtype=np.float32),
            'parval': pd.Series(None, dtype=np.float32)
            })

        # init number of observation locations
        self.nobs_loc = 0

    def add_param(self, name, default_value = np.nan, izone = None, array = None) :

        # case an array is provided
        if isinstance(array, np.ndarray) :
            assert array.shape == (self.nlay, self.nrow, self.ncol)
            self.grids[name] = array
        else : 
            # fetch mask from mm
            self.grids[name] = np.array(self.imask, dtype=np.float)
            # fill array with nan within mask
            self.grids[name][ self.grids[name] != 0 ] = np.nan

        # create new instance of MartheParam
        self.param[name] = MartheParam(self, name, default_value, izone, array)       

    def add_obs(self, obs_file, loc_name = None) :
        
        self.nobs_loc += 1
        # prefix will be used to set individual obs name
        prefix = 'loc{0:02d}'.format(self.nobs_loc)

        # infer loc_name from file name if loc_name not provided
        if loc_name is None : 
            obs_dir, obs_filename = os.path.split(obs_file)
            loc_name = obs_filename.split('.')[0]

        self.obs[loc_name] = MartheObs(self, prefix, obs_file, loc_name)

    def load_grid(self,key) : 
        """
        Simple wrapper for read_grid.
        The grid is directly stored to grids dic

        Parameters
        ----------
        key : str
            grid data key

        Examples
        --------
        x_vals, y_vals, permh_grid = read_grid('permh')

        """
        x_vals, y_vals, self.grids[key] =  self.read_grid(key)
        
        return

    
    def read_grid(self,key):
        """
        Simple wrapper for read_grid file
        Builds up path to the file from the key

        Parameters
        ----------
        param : type
            text

        Examples
        --------
        x_vals, y_vals, permh_grid = read_grid('permh')

        """
        # get path to grid file 
        grid_path = os.path.join(self.mldir,self.mlname + '.' + key)

        # load grid file 
        x_vals, y_vals, grid = marthe_utils.read_grid_file(grid_path)

        return(x_vals,y_vals,grid)

    def write_grid(self,key):
        """
        Simple wrapper for write_grid file

        Parameters
        ----------
        key : str
            parameter key (ex. 'kepon')
            
        Examples
        --------
        mm.write_grid('permh')

        """
        # get path to grid file 
        grid_path = os.path.join(self.mldir,self.mlname + '.' + key)

        # load grid file 
        marthe_utils.write_grid_file(grid_path, self.x_vals, self.y_vals, grid = self.grids[key])

        return

    def write_grids(self) : 
        """
        write all available grids
        """
        for key in list(self.grids.keys()) : 
            write_grid(key)

        return

    def data_to_shp(self, key, lay, filepath ) :
        data = self.grids[key][lay,:,:]
        marthe_utils.grid_data_to_shp(self.x_vals, self.y_vals, data, file_path, field_name_list=[key])

    def extract_prn(self, prn_file = None, out_dir = None):
        if prn_file == None : 
            prn_file = os.path.join(self.mldir,'historiq.prn')
        if out_dir == None : 
            out_dir = os.path.join(self.mldir,'sim','')

        marthe_utils.extract_prn(prn_file, out_dir)


    def run_model(self,exe_name = 'marthe', rma_file = None, 
                  silent=False, pause=False, report=False,
                  cargs=None):
        """
        This function will run the model using subprocess.Popen.  It
        communicates with the model's stdout asynchronously and reports
        progress to the screen with timestamps
        Parameters
        ----------
        exe_name : str
            Executable name (with path, if necessary) to run.
        rma_file : str
            rma file of model to run. The rma_file must be the
            filename of the namefile without the path. Namefile can be None
            if it follows the syntax model_name.rma
        silent : boolean
            Echo run information to screen (default is True).
        pause : boolean, optional
            Pause upon completion (default is False).
        report : boolean, optional
            Save stdout lines to a list (buff) which is returned
            by the method . (default is False).
        cargs : str or list of strings
            additional command line arguments to pass to the executable.
            Default is None
        Returns
        -------
        (success, buff)
        success : boolean
        buff : list of lines of stdout
        """
        success = False
        buff = []
        normal_msg='normal termination'


        # Check to make sure that program and namefile exist
        exe = which(exe_name)
        if exe is None:
            import platform
            if platform.system() in 'Windows':
                    exe = which(exe_name + '.exe')
        if exe is None:
            s = 'The program {} does not exist or is not executable.'.format(
                exe_name)
            raise Exception(s)
        

        # Marthe rma file 
        if rma_file is None : 
            rma_file = os.path.join(self.mldir,self.mlname + '.rma')

        # simple little function for the thread to target
        def q_output(output, q):
            for line in iter(output.readline, b''):
                q.put(line)

        # create a list of arguments to pass to Popen
        argv = [exe_name]
        if rma_file is not None:
            argv.append(rma_file)

        # add additional arguments to Popen arguments
        if cargs is not None:
            if isinstance(cargs, str):
                cargs = [cargs]
            for t in cargs:
                argv.append(t)

        # run the model with Popen
        proc = sp.Popen(argv,
                        stdout=sp.PIPE, stderr=sp.STDOUT, cwd=self.mldir)

        # some tricks for the async stdout reading
        q = queue.Queue()
        thread = threading.Thread(target=q_output, args=(proc.stdout, q))
        thread.daemon = True
        thread.start()

        failed_words = ["fail", "error"]
        last = datetime.now()
        lastsec = 0.
        while True:
            try:
                line = q.get_nowait()
            except Queue.Empty:
                pass
            else:
                if line == '':
                    break
                line = line.decode().lower().strip()
                if line != '':
                    now = datetime.now()
                    dt = now - last
                    tsecs = dt.total_seconds() - lastsec
                    line = "(elapsed:{0})-->{1}".format(tsecs, line)
                    lastsec = tsecs + lastsec
                    buff.append(line)
                    if not silent:
                        print(line)
                    for fword in failed_words:
                        if fword in line:
                            success = False
                            break
            if proc.poll() is not None:
                break
        proc.wait()
        thread.join(timeout=1)
        buff.extend(proc.stdout.readlines())
        proc.stdout.close()

        for line in buff:
            if normal_msg in line:
                print("success")
                success = True
                break

        if pause:
            input('Press Enter to continue...')
        return success, buff


class SpatialReference():
    """
    Inspired from FloPy, for compatibility with PyEMU
    """
    def __init__(self,mm):
        """
        Parameters
        ----------
        ml : instance of MartheModel
        """
        self.nrow = mm.nrow
        self.ncol = mm.ncol
