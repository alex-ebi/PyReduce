"""
Wrapper for REDUCE C functions

This module provides access to the extraction algorithms in the
C libraries and sanitizes the input parameters.

"""
import ctypes
import io
import logging
import os
import sys
import tempfile
from contextlib import contextmanager

import matplotlib.pyplot as plt
import numpy as np
from scipy.ndimage import median_filter

logger = logging.getLogger(__name__)

try:
    from .clib._slitfunc_bd import lib as slitfunclib
    from .clib._slitfunc_2d import lib as slitfunc_2dlib
    from .clib._slitfunc_bd import ffi
except ImportError:  # pragma: no cover
    logger.error(
        "C libraries could not be found. Compiling them by running build_extract.py"
    )
    from .clib import build_extract

    build_extract.build()
    del build_extract

    from .clib._slitfunc_bd import lib as slitfunclib
    from .clib._slitfunc_2d import lib as slitfunc_2dlib
    from .clib._slitfunc_2d import ffi


c_double = np.ctypeslib.ctypes.c_double
c_int = np.ctypeslib.ctypes.c_int


def slitfunc(img, ycen, lambda_sp=0, lambda_sf=0.1, osample=1):
    """Decompose image into spectrum and slitfunction

    This is for horizontal straight orders only, for curved orders use slitfunc_curved instead

    Parameters
    ----------
    img : array[n, m]
        image to decompose, should just contain a small part of the overall image
    ycen : array[n]
        traces the center of the order along the image, relative to the center of the image?
    lambda_sp : float, optional
        smoothing parameter of the spectrum (the default is 0, which no smoothing)
    lambda_sf : float, optional
        smoothing parameter of the slitfunction (the default is 0.1, which )
    osample : int, optional
        Subpixel ovsersampling factor (the default is 1, which no oversampling)

    Returns
    -------
    sp, sl, model, unc
        spectrum, slitfunction, model, spectrum uncertainties
    """

    # Convert input to expected datatypes
    lambda_sf = float(lambda_sf)
    lambda_sp = float(lambda_sp)
    osample = int(osample)
    img = np.asanyarray(img, dtype=c_double)
    ycen = np.asarray(ycen, dtype=c_double)

    assert img.ndim == 2, "Image must be 2 dimensional"
    assert ycen.ndim == 1, "Ycen must be 1 dimensional"

    assert (
        img.shape[1] == ycen.size
    ), f"Image and Ycen shapes are incompatible, got {img.shape} and {ycen.shape}"

    assert osample > 0, f"Oversample rate must be positive, but got {osample}"
    assert (
        lambda_sf >= 0
    ), f"Slitfunction smoothing must be positive, but got {lambda_sf}"
    assert lambda_sp >= 0, f"Spectrum smoothing must be positive, but got {lambda_sp}"

    # Get some derived values
    nrows, ncols = img.shape
    ny = osample * (nrows + 1) + 1
    ycen = ycen - ycen.astype(c_int)

    # Prepare all arrays
    # Inital guess for slit function and spectrum
    sp = np.ma.sum(img, axis=0)
    requirements = ["C", "A", "W", "O"]
    sp = np.require(sp, dtype=c_double, requirements=requirements)

    sl = np.zeros(ny, dtype=c_double)

    mask = ~np.ma.getmaskarray(img)
    mask = np.require(mask, dtype=c_int, requirements=requirements)

    img = np.ma.getdata(img)
    img = np.require(img, dtype=c_double, requirements=requirements)

    pix_unc = np.zeros_like(img)
    pix_unc = np.require(pix_unc, dtype=c_double, requirements=requirements)

    ycen = np.require(ycen, dtype=c_double, requirements=requirements)
    model = np.zeros((nrows, ncols), dtype=c_double)
    unc = np.zeros(ncols, dtype=c_double)

    # Call the C function
    slitfunclib.slit_func_vert(
        ffi.cast("int", ncols),
        ffi.cast("int", nrows),
        ffi.cast("double *", img.ctypes.data),
        ffi.cast("double *", pix_unc.ctypes.data),
        ffi.cast("int *", mask.ctypes.data),
        ffi.cast("double *", ycen.ctypes.data),
        ffi.cast("int", osample),
        ffi.cast("double", lambda_sp),
        ffi.cast("double", lambda_sf),
        ffi.cast("double *", sp.ctypes.data),
        ffi.cast("double *", sl.ctypes.data),
        ffi.cast("double *", model.ctypes.data),
        ffi.cast("double *", unc.ctypes.data),
    )
    mask = ~mask.astype(bool)

    return sp, sl, model, unc, mask


def slitfunc_curved(img, ycen, tilt, shear, lambda_sp, lambda_sf, osample):
    """Decompose an image into a spectrum and a slitfunction, image may be curved

    Parameters
    ----------
    img : array[n, m]
        input image
    ycen : array[n]
        traces the center of the order
    shear : array[n]
        tilt of the order along the image ???, set to 0 if order straight
    osample : int, optional
        Subpixel ovsersampling factor (the default is 1, which no oversampling)
    lambda_sp : float, optional
        smoothing factor spectrum (the default is 0, which no smoothing)
    lambda_sl : float, optional
        smoothing factor slitfunction (the default is 0.1, which small)

    Returns
    -------
    sp, sl, model, unc
        spectrum, slitfunction, model, spectrum uncertainties
    """

    # Convert datatypes to expected values
    lambda_sf = float(lambda_sf)
    lambda_sp = float(lambda_sp)
    osample = int(osample)
    img = np.asanyarray(img, dtype=c_double)
    ycen = np.asarray(ycen, dtype=c_double)

    assert img.ndim == 2, "Image must be 2 dimensional"
    assert ycen.ndim == 1, "Ycen must be 1 dimensional"

    if np.isscalar(tilt):
        tilt = np.full(img.shape[1], tilt, dtype=c_double)
    else:
        tilt = np.asarray(tilt, dtype=c_double)
    if np.isscalar(shear):
        shear = np.full(img.shape[1], shear, dtype=c_double)
    else:
        shear = np.asarray(shear, dtype=c_double)

    assert (
        img.shape[1] == ycen.size
    ), "Image and Ycen shapes are incompatible, got %s and %s" % (img.shape, ycen.shape)
    assert (
        img.shape[1] == tilt.size
    ), "Image and Tilt shapes are incompatible, got %s and %s" % (img.shape, tilt.shape)
    assert img.shape[1] == shear.size, (
        "Image and Shear shapes are incompatible, got %s and %s"
        % (img.shape, shear.shape)
    )

    assert osample > 0, f"Oversample rate must be positive, but got {osample}"
    assert (
        lambda_sf >= 0
    ), f"Slitfunction smoothing must be positive, but got {lambda_sf}"
    assert lambda_sp >= 0, f"Spectrum smoothing must be positive, but got {lambda_sp}"

    # assert np.ma.all(np.isfinite(img)), "All values in the image must be finite"
    assert np.all(np.isfinite(ycen)), "All values in ycen must be finite"
    assert np.all(np.isfinite(tilt)), "All values in tilt must be finite"
    assert np.all(np.isfinite(shear)), "All values in shear must be finite"

    # Retrieve some derived values
    nrows, ncols = img.shape
    ny = osample * (nrows + 1) + 1

    ycen_offset = ycen.astype(c_int)
    ycen_int = ycen - ycen_offset
    y_lower_lim = np.min(ycen_offset)

    mask = np.ma.getmaskarray(img)
    mask |= ~np.isfinite(img)
    img = np.ma.getdata(img)
    img[mask] = 0


    # sp should never be all zero (thats a horrible guess) and leads to all nans
    # This is a simplified run of the algorithm without oversampling or curvature
    # But strong smoothing
    # To remove the most egregious outliers, which would ruin the fit
    sp = np.sum(img, axis=0)
    median_filter(sp, 5, output=sp)
    sl = np.median(img, axis=1)
    sl /= np.sum(sl)

    model = sl[:, None] * sp[None, :]
    dev = (model - img).std()
    mask[np.abs(model - img) > 6 * dev] = True
    img[mask] = 0
    sp = np.sum(img, axis=0)

    mask = np.where(mask, c_int(0), c_int(1))
    pix_unc = np.copy(img)
    np.sqrt(np.abs(pix_unc), where=np.isfinite(pix_unc), out=pix_unc)

    PSF_curve = np.zeros((ncols, 3), dtype=c_double)
    PSF_curve[:, 1] = tilt
    PSF_curve[:, 2] = shear

    yy = np.arange(-y_lower_lim, (nrows+1) - y_lower_lim)
    # calculate the curvature polynomial
    # Using Einsum is more efficient than polyval by several orders of magnitude
    dx = np.einsum("i,j", tilt, yy) + np.einsum("i,j", shear, yy**2)
    dx = int(np.ceil(np.max(np.abs(dx))))
    nx = dx * 2 + 1

    # Initialize arrays and ensure the correct datatype for C
    requirements = ["C", "A", "W", "O"]
    sp = np.require(sp, dtype=c_double, requirements=requirements)
    mask = np.require(mask, dtype=c_int, requirements=requirements)
    img = np.require(img, dtype=c_double, requirements=requirements)
    pix_unc = np.require(pix_unc, dtype=c_double, requirements=requirements)
    ycen_int = np.require(ycen_int, dtype=c_double, requirements=requirements)
    ycen_offset = np.require(ycen_offset, dtype=c_int, requirements=requirements)

    # This memory could be reused between swaths
    mask_out = np.ones((nrows, ncols), dtype=c_int)
    sl = np.zeros(ny, dtype=c_double)
    model = np.zeros((nrows, ncols), dtype=c_double)
    unc = np.zeros(ncols, dtype=c_double)
    l_aij = np.zeros((ny, 4 * osample + 1), dtype=c_double)
    l_bj = np.zeros(ny, dtype=c_double)
    p_aij = np.zeros((ncols, 5), dtype=c_double)
    p_bj = np.zeros(ncols, dtype=c_double)
    info = np.zeros(4, dtype=c_double)


    # Call the C function
    slitfunc_2dlib.slit_func_curved(
        ffi.cast("int", ncols),
        ffi.cast("int", nrows),
        ffi.cast("int", nx),
        ffi.cast("int", ny),
        ffi.cast("double *", img.ctypes.data),
        ffi.cast("double *", pix_unc.ctypes.data),
        ffi.cast("int *", mask.ctypes.data),
        ffi.cast("double *", ycen_int.ctypes.data),
        ffi.cast("int *", ycen_offset.ctypes.data),
        ffi.cast("int", y_lower_lim),
        ffi.cast("int", osample),
        ffi.cast("double", lambda_sp),
        ffi.cast("double", lambda_sf),
        ffi.cast("double *", PSF_curve.ctypes.data),
        ffi.cast("double *", sp.ctypes.data),
        ffi.cast("double *", sl.ctypes.data),
        ffi.cast("double *", model.ctypes.data),
        ffi.cast("double *", unc.ctypes.data),
        ffi.cast("int *", mask_out.ctypes.data),
        ffi.cast("double *", l_aij.ctypes.data),
        ffi.cast("double *", l_bj.ctypes.data),
        ffi.cast("double *", p_aij.ctypes.data),
        ffi.cast("double *", p_bj.ctypes.data),
        ffi.cast("double *", info.ctypes.data),
    )

    mask = mask_out == 0
    if dx > 0:
        sp[:dx] = 0
        sp[-dx:] = 0

    return sp, sl, model, unc, mask, info
