#!/usr/bin/env python3
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

import os
import sys
import logging
import lib.test_config as cfg
import lib.parse_args as parse_args
import lib.log as log
import lib.check_requirements as check_requirements
import lib.cmd_utils as cmd_utils
import lib.ffmpeg as ffmpeg

logger = log.setup_custom_logger('main')


def run(cli_args, test_config=None):

    if not test_config:
        test_config = cfg.TestConfig(cli_args.test_config, cli_args.filter_src, cli_args.filter_hrc, cli_args.filter_pvs)

    cmd_runner = cmd_utils.ParallelRunner(cli_args.parallelism)

    # get all pvs to be processed
    pvs_to_process = []
    for pvs_id, pvs in test_config.pvses.items():
        if pvs.is_online() and cli_args.skip_online_services:
            continue
        pvs_to_process.append(pvs_id)

    logger.info("will re-convert " + str(len(pvs_to_process)) + " PVSes")
    if cli_args.lightweight_preview:
        logger.info("will create preview for " + str(len(pvs_to_process)) + " PVSes")

    # Collect all commands in one dict
    for pvs_name in pvs_to_process:
        pvs = test_config.pvses[pvs_name]

        if cli_args.skip_online_services and pvs.is_online():
            logger.warn("Skipping PVS {} because it is an online PVS".format(pvs))
            continue

        for post_processing in test_config.post_processings:
            logger.info("processing for " + str(post_processing))

            # create CPVS file
            cmd = ffmpeg.create_cpvs(
                pvs,
                post_processing,
                rawvideo=cli_args.rawvideo,
                overwrite=cli_args.force
            )
            cmd_runner.add_cmd(cmd, name=str(pvs_name))

            # create preview if requirested
            if cli_args.lightweight_preview:
                cmd = ffmpeg.create_preview(pvs, overwrite=cli_args.force)
                cmd_runner.add_cmd(cmd, name=str(pvs_name) + ' preview')

    # Print cli text for all commands in the command-list and quit without producing any files
    if cli_args.dry_run:
        cmd_runner.log_commands()
        sys.exit(0)

    # Run all commands in the command-list
    cmd_runner.run_commands()


def main():
    cli_args = parse_args.parse_args(os.path.basename(__file__), 4)

    # initialize logger
    if cli_args.verbose:
        logger.setLevel(logging.DEBUG)

    check_requirements.check_requirements(skip=cli_args.skip_requirements)

    run(cli_args)


if __name__ == '__main__':
    main()
