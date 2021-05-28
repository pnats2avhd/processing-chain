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
import logging
import lib.test_config as cfg
import lib.parse_args as parse_args
import lib.log as log
import lib.cmd_utils as cmd_utils
import lib.ffmpeg as ffmpeg
import lib.check_requirements as check_requirements

logger = log.setup_custom_logger('main')


def run(cli_args):
    test_config = cfg.TestConfig(cli_args.test_config, cli_args.filter_src, cli_args.filter_hrc, cli_args.filter_pvs)

    # get all required segments to be encoded
    required_segments = test_config.get_required_segments()

    # encode in parallel
    logger.info("will generate " + str(len(required_segments)) + " segments")

    import lib.downloader as downloader
    dload = downloader.Downloader(
                folder=test_config.get_video_segments_path(),
                bitmovin_key_file=os.path.join(check_requirements.get_processing_chain_dir(), "bitmovin_settings", "keyfile.txt"),
                input_details=os.path.join(check_requirements.get_processing_chain_dir(), "bitmovin_settings", "input_details.yaml"),
                output_details=os.path.join(check_requirements.get_processing_chain_dir(), "bitmovin_settings", "output_details.yaml"),
                overwrite=cli_args.force)

    cmd_runner = cmd_utils.ParallelRunner(cli_args.parallelism)

    for seg in required_segments:
        if seg.video_coding.is_online:
            if not cli_args.skip_online_services:
                if seg.video_coding.encoder == "youtube":
                    logger.debug("will download youtube-encoding for video " + seg.get_filename() + ".")
                    if not cli_args.dry_run:
                        dload.init_download(seg, cli_args.force, cli_args.verbose)
                elif seg.video_coding.encoder.casefold() == "bitmovin":
                    logger.debug("will encode " + seg.get_filename() + " using Bitmovin.")
                    if not cli_args.dry_run:
                        dload.encode_bitmovin(seg=seg)
            else:
                logger.debug("skipping " + seg.get_filename() + "because skipping online services is enabled.")
        else:
            cmd = ffmpeg.encode_segment(seg, overwrite=cli_args.force)
            cmd_runner.add_cmd(
                cmd,
                name=str(seg)
            )

            # only write logfile if command should run
            if cmd:
                logfile = seg.get_logfile_path()

                # replace all absolute paths
                seg_cmd = cmd.replace(test_config.get_video_segments_path() + "/", "")
                seg_cmd = seg_cmd.replace(check_requirements.get_processing_chain_dir() + "/logs/", "")
                seg_cmd = seg_cmd.replace(test_config.get_src_vid_path() + "/", "")

                logger.debug("writing segment logfile to " + logfile)
                if not cli_args.dry_run:
                    with open(logfile, "w") as lf:
                        lf.write("segmentFilename: " + seg.get_filename() + "\n")
                        lf.write("processingChain: " + check_requirements.get_processing_chain_version() + "\n")
                        lf.write("ffmpegCommand: " + seg_cmd + "\n")

    if cli_args.dry_run:
        cmd_runner.log_commands()
        return test_config

    logger.info("starting to process segments, please wait")
    if 'nvenc' in ''.join(cmd_runner.return_command_list()):
        cmd_runner.run_commands_on_multiple_gpus()
    else:
        cmd_runner.run_commands()

    return test_config


def main():
    cli_args = parse_args.parse_args(os.path.basename(__file__), 1)

    # initialize logger
    if cli_args.verbose:
        logger.setLevel(logging.DEBUG)

    check_requirements.check_requirements(skip=cli_args.skip_requirements)

    run(cli_args)


if __name__ == '__main__':
    main()
