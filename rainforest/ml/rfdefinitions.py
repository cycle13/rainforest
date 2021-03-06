#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Class declarations and reading functions
required to unpickle trained RandomForest models

Daniel Wolfensberger
MeteoSwiss/EPFL
daniel.wolfensberger@epfl.ch
December 2019
"""

# Global imports
import pickle
import numpy as np
from sklearn.ensemble import RandomForestRegressor
import os
from scipy.interpolate import UnivariateSpline
from pathlib import Path

current_file = os.path.abspath(__file__)
current_folder = os.path.dirname(current_file)

FOLDER_RF = str(Path(current_folder,  'rf_models'))


    
##################
# Add here all classes/functions used in the construction of the pickled 
# instances
##################
    
def _polyfit_no_inter(x,y, degree):
    """linear regression with zero intercept"""
    X = []
    for i in range(1,degree+1):
        X.append(x**i)
    X = np.array(X).T
    p, _, _, _ = np.linalg.lstsq(X, y[:,None])
    p = np.insert(p,0,0) # Add zero intercept at beginning for compatibility with polyval
    return p[::-1] # Reverse because that's how it is in polyfit (high degree first)
    
class RandomForestRegressorBC(RandomForestRegressor):
    '''
    This is an extension of the RandomForestRegressor regressor class of
    sklearn that does additional bias correction, is able
    to apply a rounding function to the outputs on the fly and adds a 
    bit of metadata:
    
        *bctype* : type of bias correction method
        *variables* : name of input features
        *beta* : weighting factor in vertical aggregation
        *degree* : order of the polyfit used in some bias-correction methods
    
    For *bc_type* tHe available methods are currently "raw":
    simple linear fit between prediction and observation, "cdf": linear fit
    between sorted predictions and sorted observations and "spline" :
    spline fit between sorted predictions and sorted observations. Any
    new method should be added in this class in order to be used.
    
    For any information regarding the sklearn parent class see
    
    https://github.com/scikit-learn/scikit-learn/blob/b194674c4/sklearn/ensemble/_forest.py#L1150
    '''
    def __init__(self, 
                 variables, 
                 beta, 
                 degree = 1, 
                 bctype = 'cdf', 
                 n_estimators=100,
                 criterion="mse",
                 max_depth=None,
                 min_samples_split=2,
                 min_samples_leaf=1,
                 min_weight_fraction_leaf=0.,
                 max_features="auto",
                 max_leaf_nodes=None,
                 min_impurity_decrease=0.,
                 min_impurity_split=None,
                 bootstrap=True,
                 oob_score=False,
                 n_jobs=None,
                 random_state=None,
                 verbose=0,
                 warm_start=False):
        super().__init__(n_estimators, criterion, max_depth, min_samples_split,
                 min_samples_leaf, min_weight_fraction_leaf, max_features,
                 max_leaf_nodes, min_impurity_decrease, min_impurity_split,
                 bootstrap, oob_score, n_jobs, random_state, verbose, warm_start)
        
        self.degree = degree
        self.bctype = bctype
        self.variables = variables
        self.beta = beta

    def fit(self, X,y, sample_weight = None):
        """
        Fit both estimator and a-posteriori bias correction
        Parameters
        ----------
        X : array-like or sparse matrix, shape=(n_samples, n_features)
            The input samples. Use ``dtype=np.float32`` for maximum
            efficiency. Sparse matrices are also supported, use sparse
            ``csc_matrix`` for maximum efficiency.
        sample_weight : array-like of shape (n_samples,), default=None
            Sample weights. If None, then samples are equally weighted. Splits
            that would create child nodes with net zero or negative weight are
            ignored while searching for a split in each node. In the case of
            classification, splits are also ignored if they would result in any
            single class carrying a negative weight in either child node.
        Returns
        -------
        self : object
        """
        
        super().fit(X,y, sample_weight)
        y_pred = super().predict(X)
        if self.bctype in ['cdf','raw']:
            if self.bctype == 'cdf':
                x_ = np.sort(y_pred)
                y_ = np.sort(y)
            elif self.bctype == 'raw':
                x_ = y_pred
                y_ = y
            self.p = _polyfit_no_inter(x_,y_,self.degree)
        elif self.bctype == 'spline':
            x_ = np.sort(y_pred)
            y_ = np.sort(y)
            _,idx = np.unique(x_, return_index = True)
            self.p = UnivariateSpline(x_[idx], y_[idx])
        else:
            self.p = 1
            
        return 
    
    def predict(self, X, round_func = None, bc = True):
        """
        Predict regression target for X.
        The predicted regression target of an input sample is computed as the
        mean predicted regression targets of the trees in the forest.
        Parameters
        ----------
        X : array-like or sparse matrix of shape (n_samples, n_features)
            The input samples. Internally, its dtype will be converted to
            ``dtype=np.float32``. If a sparse matrix is provided, it will be
            converted into a sparse ``csr_matrix``.
        round_func : lambda function
            Optional function to apply to outputs (for example to discretize them
            using MCH lookup tables). If not provided f(x) = x will be applied
            (i.e. no function)
        bc : bool
            if True the bias correction function will be applied
            
        Returns
        -------
        y : array-like of shape (n_samples,) or (n_samples, n_outputs)
            The predicted values.
        """
        pred = super().predict(X)
        
        if round_func == None:
            round_func = lambda x: x
        
        func = lambda x: x
        if bc:
            if self.bctype in ['cdf','raw']:
                func = lambda x : np.polyval(self.p,x)
            elif self.bctype == 'spline':
                func = lambda x : self.p(x)
        out = func(pred)
        out[out < 0] = 0
        return round_func(out)
    
##################
        
class MyCustomUnpickler(pickle.Unpickler):
    """
    This is an extension of the pickle Unpickler that handles the 
    bookeeeping references to the RandomForestRegressorBC class
    """
    import __main__
    __main__.RandomForestRegressorBC = RandomForestRegressorBC
    def find_class(self, module, name):
        print(module,name)
        return super().find_class(module, name)
    
    
def read_rf(rf_name):
    """
    Reads a randomForest model from the RF models folder using pickle. All custom
    classes and functions used in the construction of these pickled models
    must be defined in the script ml/rf_definitions.py
    
    Parameters
    ----------
    rf_name : str
        Name of the randomForest model, it must be stored in the folder
        /ml/rf_models and computed with the rf:RFTraining.fit_model function
 
        
    Returns
    -------
    A trained sklearn randomForest instance that has the predict() method, 
    that allows to predict precipitation intensities for new points
    """
    
    if rf_name[-2:] != '.p':
        rf_name += '.p'
    
    if os.path.dirname(rf_name) == '':
        rf_name = str(Path(FOLDER_RF, rf_name))
    
    unpickler = MyCustomUnpickler(open(rf_name, 'rb'))
    if not os.path.exists(rf_name):
        raise IOError('RF model {:s} does not exist!'.format(rf_name))
    else:
        return unpickler.load()
      
