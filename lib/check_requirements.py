#
# This file is part of the AVHD-AS / P.NATS Phase 2 Processing Chain
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""
Check utility requirements
"""

import os
import sys
import logging
import lib.cmd_utils as cmd_utils
import pkg_resources

logger = logging.getLogger('main')


def get_processing_chain_dir():
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


def get_processing_chain_version():
    processing_chain_dir = get_processing_chain_dir()
    git_version, _ = cmd_utils.run_command('cd "' + processing_chain_dir + '" && git describe --always')
    with open(os.path.join(get_processing_chain_dir(), 'VERSION'), 'r') as version_f:
        major_version = version_f.readlines()[0].strip()
    version = git_version.strip() + " v" + major_version
    return version


def check_requirements(skip=False):
    """
    Check if all local packages are correctly installed

    skip: if True, just check but do not exit
    """
    fail = False

    # Check version of processing chain
    logger.info("processing chain version: " + get_processing_chain_version())

    if fail and not skip:
        logger.error("requirements for running processing chain are not met, please make sure you follow all the suggestions printed above. If you absolutely need to continue, add the '--skip-requirements' option.")
        sys.exit(1)
