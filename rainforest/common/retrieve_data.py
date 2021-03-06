#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Functions to retrieve MeteoSwiss products from the archives

Daniel Wolfensberger
MeteoSwiss/EPFL
daniel.wolfensberger@epfl.ch
December 2019
"""


import numpy as np
import os
import zipfile
import datetime
import glob
import subprocess
import netCDF4
import logging
import fnmatch
import re
from textwrap import dedent

from . import constants 
from .lookup import get_lookup
from .utils import round_to_hour
from . import io_data as io # avoid circular

        
def get_COSMO_T(time, sweeps = None, radar = None):
    
    """Retrieves COSMO temperature data from the CSCS repository, and 
    interpolates them to the radar gates, using precomputed lookup tables

    Parameters
    ----------
    time : datetime.datetime instance
        the time at which to get the COSMO data in datetime format
    sweeps: list of integers
         specify which sweeps (elevations) need to be retrieved in the form
         of a list, if not specified, all 20 will be retrieved
    radar: list of chars
        list of radars for which to retrieve COSMO data, if not specified
        all 5 radars will be used ('A','L','D','W','P')
            
    Returns
    -------
    T_at_radar : dict
        A dict containing the temperature at the radar gates, in the following form:
        dict[radar]['T'][sweep_number]
    
    """
        
    if np.any(radar == None):
        radar = constants.RADARS['Abbrev']
 
    if np.any(sweeps == None):
        sweeps = range(1,21)
        
    if time > constants.COSMO1_START and time < constants.TIMES_COSMO1_T[0]:
        msg = """No temp file available for this timestep, using the slow 
        more exhaustive function instead
        """
        logging.warning(dedent(msg))
        return get_COSMO_variables(time, ['T'], sweeps, radar)
        
    elif time < constants.COSMO1_START:
        msg = """
        Currently all COSMO-2 files have been archived and it is not possible
        to retrieve them with this function, sorry
        """
        raise ValueError(dedent(msg))
        
    # Get the closest COSMO-1 or 2 file in time
    
    idx_closest = np.where(time >= constants.TIMES_COSMO1_T)[0][-1]
    file_COSMO = constants.FILES_COSMO1_T[idx_closest]
    dt = (time - constants.TIMES_COSMO1_T[idx_closest]).total_seconds()

    file_COSMO = netCDF4.Dataset(file_COSMO)
    idx_time = np.argmin(np.abs(dt - file_COSMO.variables['time'][:]))    
    T = file_COSMO.variables['T'][idx_time,:,:,:]

    T_at_radar = {}
    for r in radar:
        lut_rad = get_lookup('cosmo1T_to_rad', r)
        T_at_radar[r] = {'T':{}}
        for s in sweeps:
  
            # Finally get temperature at radar
            m1 = lut_rad[s]['idx0']
            m2 = lut_rad[s]['idx1']
            m3 = lut_rad[s]['idx2']
            mask = lut_rad[s]['mask']
            # Finally get variables at radar
            T_at_radar[r]['T'][s] = np.ma.array(T[m1, m2, m3], mask = mask)
    file_COSMO.close()        
    
    return T_at_radar

def get_COSMO_variables(time, variables, sweeps = None, radar = None,
                        tmp_folder = '/tmp/', cleanup = True):
    
    """Retrieves COSMO data from the CSCS repository, and 
    interpolates them to the radar gates, using precomputed lookup tables
    This is a more generic but much slower function than the previous one,
    as it reads all COSMO variables directly from the GRIB files

    Parameters
    ----------
    time : datetime.datetime instance
        the time at which to get the COSMO data in datetime format
    variables: list of strings
        List of COSMO variables to retrieve, ex. P, T, QV, QR, RH, etc...
    sweeps: list of integers (optional)
         specify which sweeps (elevations) need to be retrieved in the form
         of a list, if not specified, all 20 will be retrieved
    radar = list of chars (optional)
        list of radars for which to retrieve COSMO data, if not specified
        all 5 radars will be used ('A','L','D','W','P')
    tmp_folder = str (optional)
        Directory where to store the extracted files
    cleanup = boolean (optional)
        If true all extracted files will be deleted before returning the output
        (recommended)
        
    Returns
    -------
    A dict containing the COSMO variables at the radar gates, in the following
    form: dict[radar][variables][sweep_number]
    
    """
    
    if np.any(radar == None):
        radar = constants.RADARS['Abbrev']
 
    if np.any(sweeps == None):
        sweeps = range(1,21)
        
    if time < constants.COSMO1_START:
        msg = """
        Currently all COSMO-2 files have been archived and it is not possible
        to retrieve them with this function, sorry
        """
        raise ValueError(dedent(msg))
        
    # Round time to nearest hour
    t_near = round_to_hour(time)
    
    # Get the closest COSMO-1 or 2 file in time
    grb = constants.FOLDER_COSMO1 + 'ANA{:s}/laf{:s}'.format(str(t_near.year)[2:],
                                datetime.datetime.strftime(t_near,'%Y%m%d%H')) 
    
    # Extract fields and convert to netCDF
    list_variables = ','.join(variables)
    tmp_name = tmp_folder + os.path.basename(grb) + '_filtered'
    
    cmd_filter = {'{:s} {:s} --force -s {:s} -o {:s}'.format(
                constants.FILTER_COMMAND, grb, list_variables, tmp_name)}

    subprocess.call(cmd_filter, shell = True)
    
    cmd_convert = {'{:s} --force -o {:s} nc {:s}'.format(
            constants.CONVERT_COMMAND, tmp_name + '.nc', tmp_name)}

    subprocess.call(cmd_convert, shell = True)
    
    # Finally interpolate to radar grid
    file_COSMO = netCDF4.Dataset(tmp_name + '.nc')
    
    # Interpolate for all radars and sweeps
    var_at_radar = {}
    for r in radar:
        lut_rad = get_lookup('cosmo1T_to_rad', r)
        var_at_radar[r] = {}
        for v in variables:
            data = np.squeeze(file_COSMO.variables[v][:])
            var_at_radar[r][v] = {}
            for s in sweeps:
                m1 = lut_rad[s]['idx0']
                m2 = lut_rad[s]['idx1']
                m3 = lut_rad[s]['idx2']
                mask = lut_rad[s]['mask']
                # Finally get variables at radar
                d = np.ma.array(data[m1, m2, m3], mask = mask)
                var_at_radar[r][v][s] = d
    file_COSMO.close() 
    if cleanup:
        os.remove(tmp_name)
        os.remove(tmp_name + '.nc')
        
    return var_at_radar


def retrieve_prod(folder_out, start_time, end_time, product_name,
                  pattern = None, pattern_type = 'shell', sweeps = None):
    
    """ Retrieves radar data from the CSCS repository for a specified
    time range, unzips them and places them in a specified folder

    Parameters
    ----------
    
    folder_out: str
        directory where to store the unzipped files
    start_time : datetime.datetime instance
        starting time of the time range
    end_time : datetime.datetime instance
        end time of the time range
    product_name: str
        name of the product, as stored on CSCS, e.g. RZC, CPCH, MZC, BZC...
    pattern: str
        pattern constraint on file names, can be used for products which contain 
        multiple filetypes, f.ex CPCH folders contain both rda and gif files,
        if only gifs are wanted : file_type = '*.gif'
    pattern_type: either 'shell' or 'regex' (optional)
        use 'shell' for standard shell patterns, which use * as wildcard
        use 'regex' for more advanced regex patterns
    sweeps: list of int (optional)
        For polar products, specifies which sweeps (elevations) must be
        retrieved, if not specified all available sweeps will be retrieved
                
    Returns
    -------
    A list containing all the filepaths of the retrieved files
   
    """
    
    if product_name == 'ZZW' or product_name == 'ZZP': # no vpr for PPM and WEI
        product_name = 'ZZA'
    
    dt = datetime.timedelta(minutes = 5)
    delta = end_time - start_time
    if delta.total_seconds()== 0:
        times = [start_time]
    else:
        times = start_time + np.arange(int(delta.total_seconds()/(5*60)) + 1) * dt
    dates = []
    for t in times:
        dates.append(datetime.datetime(year = t.year, month = t.month,
                                       day = t.day))
    dates = np.unique(dates)
    
    t0 = start_time
    t1 = end_time
    
    all_files = []
    for i, d in enumerate(dates):
        if i == 0:
            start_time = t0
        else:
            start_time = datetime.datetime(year = d.year, month = d.month,
                                           day = d.day)
        if i == len(dates) - 1:
            end_time = t1
        else:
            end_time = datetime.datetime(year = d.year, month = d.month,
                                           day = d.day, hour = 23, minute = 59)
        files = _retrieve_prod_daily(folder_out, start_time, end_time,
                                     product_name, pattern, pattern_type,
                                     sweeps)

        all_files.extend(files)
            
    return all_files


def _retrieve_prod_daily(folder_out, start_time, end_time, product_name,
                  pattern = None, pattern_type = 'shell', sweeps = None):
    
    """ This is a version that works only for a given day (i.e. start and end
    time on the same day)
    """
    
    folder_out += '/'
    
    suffix =  str(start_time.year)[-2:] + str(start_time.timetuple().tm_yday).zfill(3)
    folder_in = constants.FOLDER_RADAR + str(start_time.year) + '/' +  suffix + '/'
    name_zipfile = product_name + suffix+'.zip'
    
    # Get list of files in zipfile
    zipp = zipfile.ZipFile(folder_in + name_zipfile)
    content_zip = np.array(zipp.namelist())
    
    if pattern != None:
        if pattern_type == 'shell':
            content_zip = [c for c in content_zip 
                           if fnmatch.fnmatch(os.path.basename(c), pattern)]
        elif pattern_type == 'regex':
            content_zip = [c for c in content_zip 
                           if re.match(os.path.basename(c), pattern) != None]
        else:
            raise ValueError('Unknown pattern_type, must be either "shell" or "regex".')
            
    content_zip = np.array(content_zip)
        
    times_zip = np.array([datetime.datetime.strptime(c[3:12],
                          '%y%j%H%M') for c in content_zip])
  
    # Get a list of all files to retrieve
    conditions = np.array([np.logical_and(t >= start_time, t <= end_time)
        for t in times_zip])
    
    # Filter on sweeps:
    if sweeps != None:
        sweeps_zip = np.array([int(c[-3:]) for c in content_zip])
            # Get a list of all files to retrieve
        conditions_sweep = np.array([s in sweeps for s in sweeps_zip])
        conditions = np.logical_and(conditions, conditions_sweep)

    if not np.any(conditions):
        msg = '''
        No file was found corresponding to this format, verify pattern and product_name
        '''
        raise ValueError(msg)
        
    files_to_retrieve = ' '.join(content_zip[conditions])
   
    cmd = 'unzip -j -o -qq "{:s}" {:s} -d {:s}'.format(folder_in + name_zipfile,
         files_to_retrieve , folder_out)
    subprocess.call(cmd, shell=True)
        
    
    files = sorted(np.array([folder_out + c for c in
                                  content_zip[conditions]]))    
    
    return files


def retrieve_CPCCV(time, stations):
    
    """ Retrieves cross-validation CPC data for a set of stations from
    the xls files prepared by Yanni

    Parameters
    ----------

    time : datetime.datetime instance
        starting time of the time range
    stations : list of str
        list of weather stations at which to retrieve the CPC.CV data
    
    Returns
    -------
    A numpy array corresponding at the CPC.CV estimations at every specified 
    station
    """
    
    year = time.year

    folder = constants.FOLDER_CPCCV + str(year) + '/'
    
    files = sorted([f for f in glob.glob(folder + '*.xls') if '.s' not in f])
    
    def _start_time(fname):
        bname = os.path.basename(fname)
        times = bname.split('.')[1]
        tend = times.split('_')[1]
        return datetime.datetime.strptime(tend,'%Y%m%d%H%M')

    tend = np.array([_start_time(f) for f in files])
    
    match = np.where(time < tend)[0]
    
    if not len(match):
        logging.warn('Could not find CPC CV file for time {:s}'.format(time))
        return np.zeros((len(stations))) + np.nan
    
    data = io.read_xls(files[match[0]])
    
    hour = int(datetime.datetime.strftime(time, '%Y%m%d%H%M'))
    idx = np.where(np.array(data['time.stamp']) == hour)[0]
    data_hour = data.iloc[idx]
    data_hour_stations = data_hour.iloc[np.isin(np.array(data_hour['nat.abbr']), 
                                                stations)]
    cpc_cv = []
    for sta in stations:
        if sta in np.array(data_hour_stations['nat.abbr']):
            cpc_cv.append(float(data_hour_stations.loc[data_hour_stations['nat.abbr'] 
                == sta]['CPC.CV']))
        else:
            cpc_cv.append(np.nan)
            
    return np.array(cpc_cv)
