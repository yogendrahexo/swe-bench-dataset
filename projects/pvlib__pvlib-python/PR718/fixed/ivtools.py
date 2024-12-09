# -*- coding: utf-8 -*-
"""
Created on Fri Mar 29 10:34:10 2019

@author: cwhanse
"""

import numpy as np


def fit_sdm_cec_sam(celltype, v_mp, i_mp, v_oc, i_sc, alpha_sc, beta_voc,
                    gamma_pmp, cells_in_series, temp_ref=25):
    """
    Estimates parameters for the CEC single diode model (SDM) using the SAM
    SDK.

    Parameters
    ----------
    celltype : str
        Value is one of 'monoSi', 'multiSi', 'polySi', 'cis', 'cigs', 'cdte',
        'amorphous'
    v_mp : float
        Voltage at maximum power point [V]
    i_mp : float
        Current at maximum power point [A]
    v_oc : float
        Open circuit voltage [V]
    i_sc : float
        Short circuit current [A]
    alpha_sc : float
        Temperature coefficient of short circuit current [A/C]
    beta_voc : float
        Temperature coefficient of open circuit voltage [V/C]
    gamma_pmp : float
        Temperature coefficient of power at maximum point point [%/C]
    cells_in_series : int
        Number of cells in series
    temp_ref : float, default 25
        Reference temperature condition [C]

    Returns
    -------
    tuple of the following elements:

        * I_L_ref : float
            The light-generated current (or photocurrent) at reference
            conditions [A]

        * I_o_ref : float
            The dark or diode reverse saturation current at reference
            conditions [A]

        * R_sh_ref : float
            The shunt resistance at reference conditions, in ohms.

        * R_s : float
            The series resistance at reference conditions, in ohms.

        * a_ref : float
            The product of the usual diode ideality factor ``n`` (unitless),
            number of cells in series ``Ns``, and cell thermal voltage at
            reference conditions [V]

        * Adjust : float
            The adjustment to the temperature coefficient for short circuit
            current, in percent.

    Raises
    ------
        ImportError if NREL-PySAM is not installed.

        RuntimeError if parameter extraction is not successful.

    Notes
    -----
    Inputs ``v_mp``, ``v_oc``, ``i_mp`` and ``i_sc`` are assumed to be from a
    single IV curve at constant irradiance and cell temperature. Irradiance is
    not explicitly used by the fitting procedure. The irradiance level at which
    the input IV curve is determined and the specified cell temperature
    ``temp_ref`` are the reference conditions for the output parameters
    ``I_L_ref``, ``I_o_ref``, ``R_sh_ref``, ``R_s``, ``a_ref`` and ``Adjust``.

    References
    ----------
    [1] A. Dobos, "An Improved Coefficient Calculator for the California
    Energy Commission 6 Parameter Photovoltaic Module Model", Journal of
    Solar Energy Engineering, vol 134, 2012.
    """

    try:
        from PySAM import PySSC
    except ImportError:
        raise ImportError("Requires NREL's PySAM package at "
                          "https://pypi.org/project/NREL-PySAM/.")

    datadict = {'tech_model': '6parsolve', 'financial_model': 'none',
                'celltype': celltype, 'Vmp': v_mp,
                'Imp': i_mp, 'Voc': v_oc, 'Isc': i_sc, 'alpha_isc': alpha_sc,
                'beta_voc': beta_voc, 'gamma_pmp': gamma_pmp,
                'Nser': cells_in_series, 'Tref': temp_ref}

    result = PySSC.ssc_sim_from_dict(datadict)
    if result['cmod_success'] == 1:
        return tuple([result[k] for k in ['Il', 'Io', 'Rsh', 'Rs', 'a',
                      'Adj']])
    else:
        raise RuntimeError('Parameter estimation failed')


def fit_sde_sandia(voltage, current, v_oc=None, i_sc=None, v_mp_i_mp=None,
                   vlim=0.2, ilim=0.1):
    r"""
    Fits the single diode equation (SDE) to an IV curve.

    Parameters
    ----------
    voltage : ndarray
        1D array of `float` type containing voltage at each point on the IV
        curve, increasing from 0 to ``v_oc`` inclusive [V]

    current : ndarray
        1D array of `float` type containing current at each point on the IV
        curve, from ``i_sc`` to 0 inclusive [A]

    v_oc : float, default None
        Open circuit voltage [V]. If not provided, ``v_oc`` is taken as the
        last point in the ``voltage`` array.

    i_sc : float, default None
        Short circuit current [A]. If not provided, ``i_sc`` is taken as the
        first point in the ``current`` array.

    v_mp_i_mp : tuple of float, default None
        Voltage, current at maximum power point in units of [V], [A].
        If not provided, the maximum power point is found at the maximum of
        ``voltage`` \times ``current``.

    vlim : float, default 0.2
        Defines portion of IV curve where the exponential term in the single
        diode equation can be neglected, i.e.
        ``voltage`` <= ``vlim`` x ``v_oc`` [V]

    ilim : float, default 0.1
        Defines portion of the IV curve where the exponential term in the
        single diode equation is signficant, approximately defined by
        ``current`` < (1 - ``ilim``) x ``i_sc`` [A]

    Returns
    -------
    tuple of the following elements:

        * photocurrent : float
            photocurrent [A]
        * saturation_current : float
            dark (saturation) current [A]
        * resistance_shunt : float
            shunt (parallel) resistance, in ohms
        * resistance_series : float
            series resistance, in ohms
        * nNsVth : float
            product of thermal voltage ``Vth`` [V], diode ideality factor
            ``n``, and number of series cells ``Ns``

    Raises
    ------
    RuntimeError if parameter extraction is not successful.

    Notes
    -----
    Inputs ``voltage``, ``current``, ``v_oc``, ``i_sc`` and ``v_mp_i_mp`` are
    assumed to be from a single IV curve at constant irradiance and cell
    temperature.

    :py:func:`fit_single_diode_sandia` obtains values for the five parameters
    for the single diode equation [1]:

    .. math::

        I = I_{L} - I_{0} (\exp \frac{V + I R_{s}}{nNsVth} - 1)
        - \frac{V + I R_{s}}{R_{sh}}

    See :py:func:`pvsystem.singlediode` for definition of the parameters.

    The extraction method [2] proceeds in six steps.

    1. In the single diode equation, replace :math:`R_{sh} = 1/G_{p}` and
       re-arrange

    .. math::

        I = \frac{I_{L}}{1 + G_{p} R_{s}} - \frac{G_{p} V}{1 + G_{p} R_{s}}
        - \frac{I_{0}}{1 + G_{p} R_{s}} (\exp(\frac{V + I R_{s}}{nNsVth}) - 1)

    2. The linear portion of the IV curve is defined as
       :math:`V \le vlim \times v_oc`. Over this portion of the IV curve,

    .. math::

        \frac{I_{0}}{1 + G_{p} R_{s}} (\exp(\frac{V + I R_{s}}{nNsVth}) - 1)
        \approx 0

    3. Fit the linear portion of the IV curve with a line.

    .. math::

        I &\approx \frac{I_{L}}{1 + G_{p} R_{s}} - \frac{G_{p} V}{1 + G_{p}
        R_{s}} \\
        &= \beta_{0} + \beta_{1} V

    4. The exponential portion of the IV curve is defined by
       :math:`\beta_{0} + \beta_{1} \times V - I > ilim \times i_sc`.
       Over this portion of the curve, :math:`exp((V + IRs)/nNsVth) >> 1`
       so that

    .. math::

        \exp(\frac{V + I R_{s}}{nNsVth}) - 1 \approx
        \exp(\frac{V + I R_{s}}{nNsVth})

    5. Fit the exponential portion of the IV curve.

    .. math::

        \log(\beta_{0} - \beta_{1} V - I)
        &\approx \log(\frac{I_{0}}{1 + G_{p} R_{s}} + \frac{V}{nNsVth}
        + \frac{I R_{s}}{nNsVth} \\
        &= \beta_{2} + beta_{3} V + \beta_{4} I

    6. Calculate values for ``IL, I0, Rs, Rsh,`` and ``nNsVth`` from the
       regression coefficents :math:`\beta_{0}, \beta_{1}, \beta_{3}` and
       :math:`\beta_{4}`.


    References
    ----------
    [1] S.R. Wenham, M.A. Green, M.E. Watt, "Applied Photovoltaics" ISBN
    0 86758 909 4
    [2] C. B. Jones, C. W. Hansen, Single Diode Parameter Extraction from
    In-Field Photovoltaic I-V Curves on a Single Board Computer, 46th IEEE
    Photovoltaic Specialist Conference, Chicago, IL, 2019
    """

    # If not provided, extract v_oc, i_sc, v_mp and i_mp from the IV curve data
    if v_oc is None:
        v_oc = voltage[-1]
    if i_sc is None:
        i_sc = current[0]
    if v_mp_i_mp is not None:
        v_mp, i_mp = v_mp_i_mp
    else:
        v_mp, i_mp = _find_mp(voltage, current)

    # Find beta0 and beta1 from linear portion of the IV curve
    beta0, beta1 = _find_beta0_beta1(voltage, current, vlim, v_oc)

    # Find beta3 and beta4 from the exponential portion of the IV curve
    beta3, beta4 = _find_beta3_beta4(voltage, current, beta0, beta1, ilim,
                                     i_sc)

    # calculate single diode parameters from regression coefficients
    return _calculate_sde_parameters(beta0, beta1, beta3, beta4, v_mp, i_mp,
                                     v_oc)


def _find_mp(voltage, current):
    """
    Finds voltage and current at maximum power point.

    Parameters
    ----------
    voltage : ndarray
        1D array containing voltage at each point on the IV curve, increasing
        from 0 to v_oc inclusive, of `float` type [V]

    current : ndarray
        1D array containing current at each point on the IV curve, decreasing
        from i_sc to 0 inclusive, of `float` type [A]

    Returns
    -------
    v_mp, i_mp : tuple
        voltage ``v_mp`` and current ``i_mp`` at the maximum power point [V],
        [A]
    """
    p = voltage * current
    idx = np.argmax(p)
    return voltage[idx], current[idx]


def _calc_I0(IL, I, V, Gp, Rs, nNsVth):
    return (IL - I - Gp * V - Gp * Rs * I) / np.exp((V + Rs * I) / nNsVth)


def _find_beta0_beta1(v, i, vlim, v_oc):
    # Get intercept and slope of linear portion of IV curve.
    # Start with V =< vlim * v_oc, extend by adding points until slope is
    # negative (downward).
    beta0 = np.nan
    beta1 = np.nan
    first_idx = np.searchsorted(v, vlim * v_oc)
    for idx in range(first_idx, len(v)):
        coef = np.polyfit(v[:idx], i[:idx], deg=1)
        if coef[0] < 0:
            # intercept term
            beta0 = coef[1].item()
            # sign change of slope to get positive parameter value
            beta1 = -coef[0].item()
            break
    if any(np.isnan([beta0, beta1])):
        raise RuntimeError("Parameter extraction failed: beta0={}, beta1={}"
                           .format(beta0, beta1))
    else:
        return beta0, beta1


def _find_beta3_beta4(voltage, current, beta0, beta1, ilim, i_sc):
    # Subtract the IV curve from the linear fit.
    y = beta0 - beta1 * voltage - current
    x = np.array([np.ones_like(voltage), voltage, current]).T
    # Select points where y > ilim * i_sc to regress log(y) onto x
    idx = (y > ilim * i_sc)
    result = np.linalg.lstsq(x[idx], np.log(y[idx]), rcond=None)
    coef = result[0]
    beta3 = coef[1].item()
    beta4 = coef[2].item()
    if any(np.isnan([beta3, beta4])):
        raise RuntimeError("Parameter extraction failed: beta3={}, beta4={}"
                           .format(beta3, beta4))
    else:
        return beta3, beta4


def _calculate_sde_parameters(beta0, beta1, beta3, beta4, v_mp, i_mp, v_oc):
    nNsVth = 1.0 / beta3
    Rs = beta4 / beta3
    Gp = beta1 / (1.0 - Rs * beta1)
    Rsh = 1.0 / Gp
    IL = (1 + Gp * Rs) * beta0
    # calculate I0
    I0_vmp = _calc_I0(IL, i_mp, v_mp, Gp, Rs, nNsVth)
    I0_voc = _calc_I0(IL, 0, v_oc, Gp, Rs, nNsVth)
    if any(np.isnan([I0_vmp, I0_voc])) or ((I0_vmp <= 0) and (I0_voc <= 0)):
        raise RuntimeError("Parameter extraction failed: I0 is undetermined.")
    elif (I0_vmp > 0) and (I0_voc > 0):
        I0 = 0.5 * (I0_vmp + I0_voc)
    elif (I0_vmp > 0):
        I0 = I0_vmp
    else:  # I0_voc > 0
        I0 = I0_voc
    return (IL, I0, Rsh, Rs, nNsVth)
