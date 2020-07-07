#!/usr/bin/env python
"""Forward model for connecting ERT with the Pyscal command line client"""
import logging
import sys
import os
import argparse

import six

from semeio.jobs.design_kw.design_kw import extract_key_value

from pyscal import pyscalcli

_logger = logging.getLogger("FM_PYSCAL")

# The string used here must match what is used as the DEFAULT
# parameter in semeio/jobs/config_jobs/PYSCAL. It is not used elsewhere.
MAGIC_NONE = "__NONE__"

# These key-values are added to the dictionary parsed from
# parameters.txt, and allow supplying magic interpolation values
# directly from the ert config file.
MAGIC_CASES = {
    "__BASE__": 0,
    "__LOW__": -1,
    "__PESS__": -1,
    "__PESSIMISTIC__": -1,
    "__HIGH__": 1,
    "__OPT__": 1,
    "__OPTIMISTIC__": 1,
}


def main_entry_point(args=None):
    """This mimics the pyscal command line client, but differs because
    all arguments are required (but can be defaulted using MAGIC_NONE)"""
    parser = _get_args_parser()
    options = parser.parse_args(args)
    run(
        options.relperm_parameters_file,
        options.output_filename,
        options.sheet_name,
        options.int_param_wo_name,
        options.int_param_go_name,
        options.slgof,
        options.family,
    )


description = (
    "ERT forward model wrapping around the pyscal command line client. "
    "In the forward model context, this gives access to interpolation "
    "parameters in parameters.txt which the command line client is "
    "not aware of. For other uses, head to the pyscal client from "
    "the pyscal package."
)

category = "modeling.reservoir"


def _get_args_parser():
    """Construct an argparse parser for fm_pyscal"""

    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "relperm_parameters_file",
        type=str,
        help=(
            "CSV or XLSX filename with relperm parameters. "
            "See pyscal documentation for table format."
        ),
    )
    parser.add_argument(
        "output_filename",
        type=str,
        help=("Location of Eclipse relperm include file to be written."),
        default="relperm.inc",
    )
    parser.add_argument(
        "sheet_name",
        type=str,
        help="XLSX sheetname to use. Will use the first sheet if not specified.",
        default=MAGIC_NONE,
    )
    parser.add_argument(
        "int_param_wo_name",
        type=str,
        help=(
            "Interpolation parameter name to be parsed from parameters.txt "
            "for WaterOil parameter if SCAL recommendation is given. "
            "You may also use the the mnemonics __OPT__, __BASE__ and __PESS__. "
            "The values in parameters.txt must be in the interval [-1,1]. "
            "For parameters generated by GEN_KW, do not include the namespace "
            "in front of the colon in the parameter name."
        ),
        default=MAGIC_NONE,
    )
    parser.add_argument(
        "int_param_go_name",
        type=str,
        help=(
            "Ditto for GasOil. If not supplied, the WaterOil parameter will be used."
        ),
        default=MAGIC_NONE,
    )
    parser.add_argument(
        "slgof",
        type=str,
        help="Set to slgof if SLGOF is wanted in place of SGOF. Case insensitive.",
        default="sgof",
    )
    parser.add_argument(
        "family",
        type=int,
        help=(
            "Family (i) (SWOF + SGOF) or family (ii) (SWFN + SOF3 + SGFN) "
            "for Eclipse keywords. Supply integer 1 or 2. Default family (i), 1."
        ),
        default=1,
    )
    return parser


def run(
    relperm_parameters_file,
    output_filename,
    sheet_name,  # string, use 0 or __NONE__ when irrelevant or default
    int_param_wo_name,  # string or __NONE__
    int_param_go_name,  # string or __NONE__
    slgof,  # sgof or slgof, default sgof
    family,  # int: 1 or 2, default 1
    parameters_file_name="parameters.txt",
):
    """This function is a wrapper around the Pyscal command
    line tool. The command line tool is designed around argparse
    and this function wraps around that design.

    In contrast with the command line tool where interpolation
    parameters are explicit, they are implicit here, and gathered
    from parameters.txt"""
    if not os.path.exists(relperm_parameters_file):
        _logger.error("%s does not exist", relperm_parameters_file)
        sys.exit(1)

    # Always remove GEN_KW prefix from interpolation parameters,
    # reduces to noop if equal to MAGIC_NONE.
    assert ":" not in MAGIC_NONE
    int_param_wo_name = rm_genkw_prefix(int_param_wo_name)
    int_param_go_name = rm_genkw_prefix(int_param_go_name)

    # Determine which interpolation scenario the user has requested:
    if int_param_wo_name != MAGIC_NONE and int_param_go_name != MAGIC_NONE:
        # Separate interpolation parameter for WaterOil and GasOil
        do_interpolation = True
    elif int_param_wo_name != MAGIC_NONE and int_param_go_name == MAGIC_NONE:
        # In this scenario, the WaterOil interpolation parameter
        # should be used for GasOil as well.
        do_interpolation = True
        int_param_go_name = int_param_wo_name
    elif int_param_wo_name == MAGIC_NONE and int_param_go_name == MAGIC_NONE:
        do_interpolation = False
    else:
        # Something is wrong if we end here
        _logger.error("WaterOil interpolation parameter missing")
        sys.exit(1)

    slgof = slgof.lower()
    if slgof not in ["sgof", "slgof"]:
        _logger.error("Only supports sgof or slgof")
        sys.exit(1)

    if family not in [1, 2]:
        _logger.error("Family must be either 1 or 2")
        sys.exit(1)

    if do_interpolation:
        (int_param_wo, int_param_go) = _get_interpolation_values(
            int_param_wo_name, int_param_go_name, parameters_file_name
        )
    else:
        int_param_wo = None
        int_param_go = None

    if sheet_name in ["0", MAGIC_NONE]:
        # Limitation: If the user names an xls sheet with the string "0"
        # and it is not the first sheet, it will not be accessible with this
        # forward model
        sheet_name = None

    try:
        pyscalcli.pyscal_main(
            parametertable=relperm_parameters_file,
            verbose=True,
            output=output_filename,
            sheet_name=sheet_name,
            int_param_wo=int_param_wo,
            int_param_go=int_param_go,
            slgof=slgof == "slgof",
            family2=family == 2,
        )
    except ValueError as e_msg:
        _logger.error(str(e_msg))
        raise e_msg


def _get_interpolation_values(
    int_param_wo_name, int_param_go_name, parameters_file_name="parameters.txt"
):
    """"
    Given parameter names, obtain values to interpolate through from parameters.txt

    If only WaterOil is supplied, the GasOil interpolation value will
    be copied from the WaterOil value.

    Args:
        int_param_wo_name (string): parameter name (no genkw_prefix) for WaterOil
        int_param_go_name (string): parameter name (no genkw_prefix) for GasOil
        parameters_file_name (string): Text file to look for parameters in.

    Returns:
        tuple with two values, one for WaterOil and one for GasOil
    """
    # Read all key-value pairs from parameters.txt
    if not os.path.exists(parameters_file_name):
        _logger.error("%s does not exists", parameters_file_name)
        raise IOError
    with open(parameters_file_name) as parameters_file:
        parameters = parameters_file.readlines()
    parameter_dict = rm_genkw_prefix(extract_key_value(parameters))

    # Add some magic parameters:
    parameter_dict.update(MAGIC_CASES)
    if int_param_wo_name not in parameter_dict:
        _logger.error(
            "Requested parameter name %s not found in %s",
            int_param_wo_name,
            parameters_file_name,
        )
        raise ValueError("Parameter name not found")
    int_param_wo = float(parameter_dict[int_param_wo_name])
    _logger.info(
        "Collected %s from parameter.txt with value %f",
        int_param_wo_name,
        int_param_wo,
    )
    int_param_go = int_param_wo

    if int_param_go_name not in parameter_dict:
        _logger.error(
            "Requested parameter name %s not found in %s",
            int_param_go_name,
            parameters_file_name,
        )
        raise ValueError("Parameter name not found")
    int_param_go = float(parameter_dict[int_param_go_name])
    if int_param_go_name != int_param_wo_name:
        _logger.info(
            "Collected %s from parameter.txt with value %f",
            int_param_go_name,
            int_param_go,
        )
    return (int_param_wo, int_param_go)


def rm_genkw_prefix(str_or_dict):
    """Remove anything before the first colon in a string, or remove
    the same before every key in a dict"""
    if isinstance(str_or_dict, six.string_types):
        if ":" in str_or_dict:
            parts = str_or_dict.split(":")
            return ":".join(parts[1:])
        return str_or_dict
    if isinstance(str_or_dict, dict):
        return {rm_genkw_prefix(key): value for key, value in str_or_dict.items()}
    raise TypeError("rm_genkw_prefix() can only handle str or dict as argument")


if __name__ == "__main__":
    main_entry_point()
