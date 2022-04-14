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
Parse the CLI args, common to all scripts
"""

import argparse
import os


def parse_args(name, script=None):
    """Return CLI arguments as dic

    Arguments:
        name {string} -- name of the CLI script
    """

    parser = argparse.ArgumentParser(description=name,
                                     formatter_class=argparse.ArgumentDefaultsHelpFormatter)

    parser.add_argument(
        '-c', '--test-config',
        required=True,
        help='path to test config file at the root of the database folder'
    )
    parser.add_argument(
        '-f', '--force',
        action='store_true',
        help='force overwrite existing output files'
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='print more verbose output'
    )
    parser.add_argument(
        '-n', '--dry-run',
        action='store_true',
        help='only print commands, do not run them'
    )
    parser.add_argument(
        '--filter-src',
        help="Only create specified SRC-IDs. Separate multiple IDs by a '|'"
    )
    parser.add_argument(
        '--filter-hrc',
        help="Only create specified HRC-IDs. Separate multiple IDs by a '|'"
    )
    parser.add_argument(
        '--filter-pvs',
        help="Only create specified PVS-IDs. Separate multiple IDs by a '|'"
    )
    parser.add_argument(
        '-p', '--parallelism',
        default=4,
        type=int,
        help='number of processes to start in parallel (use more if you have more RAM/CPU cores)'
    )
    parser.add_argument(
        '-r', '--remove-intermediate',
        action='store_true',
        help='remove/delete intermediate files'
    )
    parser.add_argument(
        '-sos', '--skip-online-services',
        help='skip videos coded by online services',
        action='store_true'
    )
    parser.add_argument(
        '-str', '--scripts-to-run',
        help='define which scripts p00_processAll shall execute (e.g. "all", "1234", "34")',
        default='1234'
    )
    # Options for p03 only:
    if script == 3:
        parser.add_argument(
            '-s', '--spinner-path',
            default=os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'util', 'spinner-128-white.png')),
            help='optional path to a spinner animation to be used when creating stalling events. Default is pointing at: ../util/spinner-128-white.png from parse_args.py point of view.'
        )
        parser.add_argument(
            '-z', '--avpvs-src-fps',
            action='store_true',
            help='Use the SRC fps for the avpvs, (default is to use HRC framerate)'
        )
        parser.add_argument(
            '-f60', '--force-60-fps',
            action='store_true',
            help='Force avpvs framerate to 60 fps, (default is to use HRC framerate)'
            )
    # Options for p04 only:
    if script == 4:
        parser.add_argument(
            '-e', '--lightweight-preview',
            action='store_true',
            help='create lightweight preview files'
        )
        parser.add_argument(
            '-a', '--rawvideo',
            action='store_true',
            help='use rawvideo codec and MKV files as output for PC'
        )
        parser.add_argument(
            '-ccrf', '--nonraw-crf',
            default=17,
            help='Set CRF level for when using libx264 as CPVS encoder'
            )
    # Developer options:
    parser.add_argument(
        '--skip-requirements',
        help="continue running, even if requirements are not fulfilled",
        action='store_true'
    )

    args = parser.parse_args()
    return args
