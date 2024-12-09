import inspect
import os
import platform

import numpy as np
import pandas as pd
from pkg_resources import parse_version
import pytest

import pvlib

pvlib_base_version = \
    parse_version(parse_version(pvlib.__version__).base_version)


# decorator takes one argument: the base version for which it should fail
# for example @fail_on_pvlib_version('0.7') will cause a test to fail
# on pvlib versions 0.7a, 0.7b, 0.7rc1, etc.
# test function may not take args, kwargs, or fixtures.
def fail_on_pvlib_version(version):
    # second level of decorator takes the function under consideration
    def wrapper(func):
        # third level defers computation until the test is called
        # this allows the specific test to fail at test runtime,
        # rather than at decoration time (when the module is imported)
        def inner():
            # fail if the version is too high
            if pvlib_base_version >= parse_version(version):
                pytest.fail('the tested function is scheduled to be '
                            'removed in %s' % version)
            # otherwise return the function to be executed
            else:
                return func()
        return inner
    return wrapper


# commonly used directories in the tests
test_dir = os.path.dirname(
    os.path.abspath(inspect.getfile(inspect.currentframe())))
data_dir = os.path.join(test_dir, os.pardir, 'data')


platform_is_windows = platform.system() == 'Windows'
skip_windows = pytest.mark.skipif(platform_is_windows,
                                  reason='does not run on windows')

try:
    import scipy
    has_scipy = True
except ImportError:
    has_scipy = False

requires_scipy = pytest.mark.skipif(not has_scipy, reason='requires scipy')


try:
    import tables
    has_tables = True
except ImportError:
    has_tables = False

requires_tables = pytest.mark.skipif(not has_tables, reason='requires tables')


try:
    import ephem
    has_ephem = True
except ImportError:
    has_ephem = False

requires_ephem = pytest.mark.skipif(not has_ephem, reason='requires ephem')


def pandas_0_17():
    return parse_version(pd.__version__) >= parse_version('0.17.0')


needs_pandas_0_17 = pytest.mark.skipif(
    not pandas_0_17(), reason='requires pandas 0.17 or greater')


def numpy_1_10():
    return parse_version(np.__version__) >= parse_version('1.10.0')


needs_numpy_1_10 = pytest.mark.skipif(
    not numpy_1_10(), reason='requires numpy 1.10 or greater')


def pandas_0_22():
    return parse_version(pd.__version__) >= parse_version('0.22.0')


needs_pandas_0_22 = pytest.mark.skipif(
    not pandas_0_22(), reason='requires pandas 0.22 or greater')


def has_spa_c():
    try:
        from pvlib.spa_c_files.spa_py import spa_calc
    except ImportError:
        return False
    else:
        return True


requires_spa_c = pytest.mark.skipif(not has_spa_c(), reason="requires spa_c")


def has_numba():
    try:
        import numba
    except ImportError:
        return False
    else:
        vers = numba.__version__.split('.')
        if int(vers[0] + vers[1]) < 17:
            return False
        else:
            return True


requires_numba = pytest.mark.skipif(not has_numba(), reason="requires numba")

try:
    import siphon
    has_siphon = True
except ImportError:
    has_siphon = False

requires_siphon = pytest.mark.skipif(not has_siphon,
                                     reason='requires siphon')

try:
    import netCDF4  # noqa: F401
    has_netCDF4 = True
except ImportError:
    has_netCDF4 = False

requires_netCDF4 = pytest.mark.skipif(not has_netCDF4,
                                      reason='requires netCDF4')

try:
    import pvfactors  # noqa: F401
    has_pvfactors = True
except ImportError:
    has_pvfactors = False

requires_pvfactors = pytest.mark.skipif(not has_pvfactors,
                                        reason='requires pvfactors')


@pytest.fixture(scope="session")
def sam_data():
    data = {}
    data['sandiamod'] = pvlib.pvsystem.retrieve_sam('sandiamod')
    data['adrinverter'] = pvlib.pvsystem.retrieve_sam('adrinverter')
    return data


@pytest.fixture(scope="function")
def pvsyst_module_params():
    """
    Define some PVSyst module parameters for testing.

    The scope of the fixture is set to ``'function'`` to allow tests to modify
    parameters if required without affecting other tests.
    """
    parameters = {
        'gamma_ref': 1.05,
        'mu_gamma': 0.001,
        'I_L_ref': 6.0,
        'I_o_ref': 5e-9,
        'EgRef': 1.121,
        'R_sh_ref': 300,
        'R_sh_0': 1000,
        'R_s': 0.5,
        'R_sh_exp': 5.5,
        'cells_in_series': 60,
        'alpha_sc': 0.001,
    }
    return parameters


@pytest.fixture(scope='function')
def cec_inverter_parameters():
    """
    Define some CEC inverter parameters for testing.

    The scope of the fixture is set to ``'function'`` to allow tests to modify
    parameters if required without affecting other tests.
    """
    parameters = {
        'Name': 'ABB: MICRO-0.25-I-OUTD-US-208 208V [CEC 2014]',
        'Vac': 208.0,
        'Paco': 250.0,
        'Pdco': 259.5220505,
        'Vdco': 40.24260317,
        'Pso': 1.771614224,
        'C0': -2.48e-5,
        'C1': -9.01e-5,
        'C2': 6.69e-4,
        'C3': -0.0189,
        'Pnt': 0.02,
        'Vdcmax': 65.0,
        'Idcmax': 10.0,
        'Mppt_low': 20.0,
        'Mppt_high': 50.0,
    }
    return parameters


@pytest.fixture(scope='function')
def cec_module_params():
    """
    Define some CEC module parameters for testing.

    The scope of the fixture is set to ``'function'`` to allow tests to modify
    parameters if required without affecting other tests.
    """
    parameters = {
        'Name': 'Example Module',
        'BIPV': 'Y',
        'Date': '4/28/2008',
        'T_NOCT': 65,
        'A_c': 0.67,
        'N_s': 18,
        'I_sc_ref': 7.5,
        'V_oc_ref': 10.4,
        'I_mp_ref': 6.6,
        'V_mp_ref': 8.4,
        'alpha_sc': 0.003,
        'beta_oc': -0.04,
        'a_ref': 0.473,
        'I_L_ref': 7.545,
        'I_o_ref': 1.94e-09,
        'R_s': 0.094,
        'R_sh_ref': 15.72,
        'Adjust': 10.6,
        'gamma_r': -0.5,
        'Version': 'MM105',
        'PTC': 48.9,
        'Technology': 'Multi-c-Si',
    }
    return parameters


@pytest.fixture(scope='function')
def cec_module_cs5p_220m():
    """
    Define Canadian Solar CS5P-220M module parameters for testing.

    The scope of the fixture is set to ``'function'`` to allow tests to modify
    parameters if required without affecting other tests.
    """
    parameters = {
        'Name': 'Canadian Solar CS5P-220M',
        'BIPV': 'N',
        'Date': '10/5/2009',
        'T_NOCT': 42.4,
        'A_c': 1.7,
        'N_s': 96,
        'I_sc_ref': 5.1,
        'V_oc_ref': 59.4,
        'I_mp_ref': 4.69,
        'V_mp_ref': 46.9,
        'alpha_sc': 0.004539,
        'beta_oc': -0.22216,
        'a_ref': 2.6373,
        'I_L_ref': 5.114,
        'I_o_ref': 8.196e-10,
        'R_s': 1.065,
        'R_sh_ref': 381.68,
        'Adjust': 8.7,
        'gamma_r': -0.476,
        'Version': 'MM106',
        'PTC': 200.1,
        'Technology': 'Mono-c-Si',
    }
    return parameters


@pytest.fixture(scope='function')
def cec_module_spr_e20_327():
    """
    Define SunPower SPR-E20-327 module parameters for testing.

    The scope of the fixture is set to ``'function'`` to allow tests to modify
    parameters if required without affecting other tests.
    """
    parameters = {
        'Name': 'SunPower SPR-E20-327',
        'BIPV': 'N',
        'Date': '1/14/2013',
        'T_NOCT': 46,
        'A_c': 1.631,
        'N_s': 96,
        'I_sc_ref': 6.46,
        'V_oc_ref': 65.1,
        'I_mp_ref': 5.98,
        'V_mp_ref': 54.7,
        'alpha_sc': 0.004522,
        'beta_oc': -0.23176,
        'a_ref': 2.6868,
        'I_L_ref': 6.468,
        'I_o_ref': 1.88e-10,
        'R_s': 0.37,
        'R_sh_ref': 298.13,
        'Adjust': -0.1862,
        'gamma_r': -0.386,
        'Version': 'NRELv1',
        'PTC': 301.4,
        'Technology': 'Mono-c-Si',
    }
    return parameters


@pytest.fixture(scope='function')
def cec_module_fs_495():
    """
    Define First Solar FS-495 module parameters for testing.

    The scope of the fixture is set to ``'function'`` to allow tests to modify
    parameters if required without affecting other tests.
    """
    parameters = {
        'Name': 'First Solar FS-495',
        'BIPV': 'N',
        'Date': '9/18/2014',
        'T_NOCT': 44.6,
        'A_c': 0.72,
        'N_s': 216,
        'I_sc_ref': 1.55,
        'V_oc_ref': 86.5,
        'I_mp_ref': 1.4,
        'V_mp_ref': 67.9,
        'alpha_sc': 0.000924,
        'beta_oc': -0.22741,
        'a_ref': 2.9482,
        'I_L_ref': 1.563,
        'I_o_ref': 2.64e-13,
        'R_s': 6.804,
        'R_sh_ref': 806.27,
        'Adjust': -10.65,
        'gamma_r': -0.264,
        'Version': 'NRELv1',
        'PTC': 89.7,
        'Technology': 'CdTe',
    }
    return parameters


@pytest.fixture(scope='function')
def sapm_temperature_cs5p_220m():
    # SAPM temperature model parameters for Canadian_Solar_CS5P_220M
    # (glass/polymer) in open rack
    return {'a': -3.40641, 'b': -0.0842075, 'deltaT': 3}
