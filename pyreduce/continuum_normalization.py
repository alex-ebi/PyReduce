"""
Find the continuum level

Currently only splices orders together
First guess of the continuum is provided by the flat field
"""

from itertools import chain

import matplotlib.pyplot as plt
import numpy as np

from . import util


def splice_orders(
    spec,
    wave,
    cont,
    sigm,
    column_range=None,
    order_range=None,
    scaling=True,
    plot=False,
):
    """
    Splice orders together so that they form a continous spectrum
    This is achieved by linearly combining the overlaping regions

    Parameters
    ----------
    spec : array[nord, ncol]
        Spectrum to splice, with seperate orders
    wave : array[nord, ncol]
        Wavelength solution for each point
    cont : array[nord, ncol]
        Continuum, blaze function will do fine as well
    sigm : array[nord, ncol]
        Errors on the spectrum
    column_range : array[nord, 2], optional
        range of each order that is to be used  (default: use whole range)
    order_range : tuple(int, int), optional
        range of orders to use for the splicing (default: use all orders)
    scaling : bool, optional
        If true, the spectrum/continuum will be scaled to 1 (default: False)
    plot : bool, optional
        If true, will plot the spliced spectrum (default: False)

    Raises
    ------
    NotImplementedError
        If neighbouring orders dont overlap

    Returns
    -------
    spec, wave, cont, sigm : array[nord, ncol]
        spliced spectrum
    """
    nord, ncol = spec.shape  # Number of sp. orders, Order length in pixels
    if column_range is None:
        column_range = np.tile([0, ncol], (nord, 1))

    if order_range is None:
        order_range = (0, nord - 1)

    # by using masked arrays we can stop worrying about column ranges
    mask = np.full(spec.shape, True)
    for iord in range(order_range[0], order_range[1] + 1):
        cr = column_range[iord]
        mask[iord, cr[0] : cr[1]] = False

    spec = np.ma.masked_array(spec[order_range[0] : order_range[1] + 1, :], mask=mask)
    wave = np.ma.masked_array(wave[order_range[0] : order_range[1] + 1, :], mask=mask)
    cont = np.ma.masked_array(cont[order_range[0] : order_range[1] + 1, :], mask=mask)
    sigm = np.ma.masked_array(sigm[order_range[0] : order_range[1] + 1, :], mask=mask)

    if scaling:
        # Scale everything to roughly the same size, around spec/blaze = 1
        scale = np.ma.median(spec / cont, axis=1)
        cont *= scale[:, None]

    if plot:
        plt.subplot(311)
        plt.title("Before")
        for i in range(spec.shape[0]):
            plt.plot(wave[i], spec[i] / cont[i])
        plt.ylim([0, 2])

    # Order with largest signal, everything is scaled relative to this order
    iord0 = np.argmax(np.ma.median(spec / cont, axis=1))

    # Loop from iord0 outwards, first to the top, then to the bottom
    tmp0 = chain(range(iord0, 0, -1), range(iord0, nord - 1))
    tmp1 = chain(range(iord0 - 1, -1, -1), range(iord0 + 1, nord))

    for iord0, iord1 in zip(tmp0, tmp1):
        # Get data for current order
        # Note that those are just references to parts of the original data
        # any changes will also affect spec, wave, cont, and sigm
        s0, s1 = spec[iord0], spec[iord1]
        w0, w1 = wave[iord0], wave[iord1]
        c0, c1 = cont[iord0], cont[iord1]
        u0, u1 = sigm[iord0], sigm[iord1]

        # Calculate Overlap
        i0 = np.where((w0 >= np.ma.min(w1)) & (w0 <= np.ma.max(w1)))
        i1 = np.where((w1 >= np.ma.min(w0)) & (w1 <= np.ma.max(w0)))

        # Orders overlap
        if i0[0].size > 0 and i1[0].size > 0:
            # Interpolate the overlapping region onto the wavelength grid of the other order
            tmpS0 = util.bezier_interp(w1, s1, w0[i0])
            tmpB0 = util.bezier_interp(w1, c1, w0[i0])
            tmpU0 = util.bezier_interp(w1, u1, w0[i0])

            tmpS1 = util.bezier_interp(w0, s0, w1[i1])
            tmpB1 = util.bezier_interp(w0, c0, w1[i1])
            tmpU1 = util.bezier_interp(w0, u0, w1[i1])

            # Combine the two orders weighted by the relative error
            wgt0 = np.ma.vstack([c0[i0] / u0[i0], tmpB0 / tmpU0]) ** 2
            wgt1 = np.ma.vstack([c1[i1] / u1[i1], tmpB1 / tmpU1]) ** 2

            s0[i0], utmp = np.ma.average(
                np.ma.vstack([s0[i0], tmpS0]), axis=0, weights=wgt0, returned=True
            )
            c0[i0] = np.ma.average([c0[i0], tmpB0], axis=0, weights=wgt0)
            u0[i0] = c0[i0] / utmp ** 0.5

            s1[i1], utmp = np.ma.average(
                np.ma.vstack([s1[i1], tmpS1]), axis=0, weights=wgt1, returned=True
            )
            c1[i1] = np.ma.average([c1[i1], tmpB1], axis=0, weights=wgt1)
            u1[i1] = c1[i1] / utmp ** 0.5
        else:  # Orders dont overlap
            raise NotImplementedError("Orders don't overlap, please test")
            c0 *= util.top(s0 / c0, 1, poly=True)
            scale0 = util.top(s0 / c0, 1, poly=True)
            scale0 = np.polyfit(w0, scale0, 1)

            scale1 = util.top(s1 / c1, 1, poly=True)
            scale1 = np.polyfit(w1, scale1, 1)

            xx = np.linspace(np.min(w0), np.max(w1), 100)

            # TODO test this
            # scale = np.sum(scale0[0] * scale1[0] * xx * xx + scale0[0] * scale1[1] * xx + scale1[0] * scale0[1] * xx + scale1[1] * scale0[1])
            scale = scale0[::-1, None] * scale1[None, ::-1]
            scale = np.sum(np.polynomial.polynomial.polyval2d(xx, xx, scale)) / np.sum(
                np.polyval(scale1, xx) ** 2
            )
            s1 *= scale

    if plot:
        plt.subplot(312)
        plt.title("After")
        for i in range(nord):
            plt.plot(wave[i], spec[i] / cont[i], label="order=%i" % i)

        plt.subplot(313)
        plt.title("Error")
        for i in range(nord):
            plt.plot(wave[i], sigm[i] / cont[i], label="order=%i" % i)
        plt.show()

    return spec, wave, cont, sigm


def continuum_normalize(spec, wave, cont, sigm, iterations=10, plot=True):
    # TODO

    nord, ncol = spec.shape

    for i in range(nord):
        m = np.ma.median(spec[i])

    if plot:
        order = 0
        plt.plot(wave[order], spec[order], label="spec")
        plt.plot(wave[order], cont[order], label="cont")
        # plt.legend(loc="best")
        plt.xlabel("Wavelength [A]")
        plt.ylabel("Flux")
        plt.show()

    return spec