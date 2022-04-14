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
import lib.cmd_utils as cmd_utils
import lib.ffmpeg as ffmpeg
import lib.check_requirements as check_requirements

logger = log.setup_custom_logger('main')


def flatten(input_list):
    for x in input_list:
        if hasattr(x, '__iter__') and not isinstance(x, str):
            for y in flatten(x):
                yield y
        else:
            yield x


def write_to_p03_logfile(pvs, cmd_list):
    logfile = pvs.get_logfile_path()
    logger.debug("Writing PVS logfile to " + logfile)

    cmd_list = flatten(cmd_list)

    with open(logfile, "w") as lf:
        lf.write("segmentFilename: " + pvs.pvs_id + "\n")
        lf.write("processingChain: " + check_requirements.get_processing_chain_version() + "\n")
        for cmd in cmd_list:
            if cmd is not None:
                seg_cmd = cmd.replace(pvs.test_config.get_video_segments_path() + "/", "")
                seg_cmd = seg_cmd.replace(check_requirements.get_processing_chain_dir() + "/logs/", "")
                seg_cmd = seg_cmd.replace(pvs.test_config.get_src_vid_path() + "/", "")
                lf.write("ffmpegCommand: " + seg_cmd + "\n")


def run(cli_args, test_config=None):

    if not test_config:
        test_config = cfg.TestConfig(cli_args.test_config, cli_args.filter_src, cli_args.filter_hrc, cli_args.filter_pvs)

    # get all pvs to be processed
    pvs_to_complete = []
    for pvs_id, pvs in test_config.pvses.items():
        if pvs.is_online() and cli_args.skip_online_services:
            continue
        pvs_to_complete.append(pvs)

    # aggregate/decode in parallel
    logger.info("will aggregate " + str(len(pvs_to_complete)) + " PVSes")
    cmd_list = []

    # concatenate segments if the test type is "long"
    if test_config.is_long():
        cmd_runner_concat = cmd_utils.ParallelRunner(cli_args.parallelism)

        pvs_commands = {}

        for pvs in pvs_to_complete:
            pvs_commands[pvs.pvs_id] = []
            # decode segments
            cmd_runner_segments = cmd_utils.ParallelRunner(cli_args.parallelism)

            segment_iter = 0
            for seg in pvs.segments:
                cmd = ffmpeg.create_avpvs_segment(
                    seg,
                    pvs,
                    overwrite=cli_args.force,
                    scale_avpvs_tosource=cli_args.avpvs_src_fps)
                cmd_name = "create AVPVS segment nr: " + str(segment_iter) + " for " + str(pvs)
                cmd_runner_segments.add_cmd(
                    cmd,
                    name=str(cmd_name)
                    )
                segment_iter += 1

            pvs_commands[pvs.pvs_id].append(cmd_runner_segments.return_command_list())

            # concatenate segments
            cmd_concat = ffmpeg.create_avpvs_long_concat(
                pvs,
                overwrite=cli_args.force,
                scale_avpvs_tosource=cli_args.avpvs_src_fps)
            cmd_concat_name = "create AVPVS long for " + str(pvs)
            pvs_commands[pvs.pvs_id].append(cmd_concat)

            # add audio
            cmd_audio = ffmpeg.audio_mux(
                pvs,
                overwrite=cli_args.force
                )
            cmd_audio_name = "Muxing audio and video for " + str(pvs)
            pvs_commands[pvs.pvs_id].append(cmd_audio)

            # run or log all commands
            logger.debug(cmd_concat)
            logger.debug(cmd_audio)
            if cli_args.dry_run:
                cmd_runner_segments.log_commands()
            else:
                cmd_runner_segments.run_commands()
                cmd_utils.run_command(
                    cmd_concat,
                    name=str(cmd_concat_name)
                    )
                cmd_utils.run_command(
                    cmd_audio,
                    name=str(cmd_audio_name)
                    )

            # delete avpvs segments
            logger.info("Removing " + str(len(pvs.segments)) + " avpvs segments")
            if not cli_args.dry_run:
                os.remove(pvs.get_avpvs_file_list())
                os.remove(pvs.get_tmp_wo_audio_path())
                for seg in pvs.segments:
                    os.remove(seg.get_tmp_path())

        # add stalling if needed
        pvs_with_buffering = [pvs for pvs in pvs_to_complete if pvs.has_buffering()]
        cmd_runner_add_buffer = cmd_utils.ParallelRunner(cli_args.parallelism)
        if len(pvs_with_buffering):
            logger.info("will add stalling to " + str(len(pvs_with_buffering)) + " PVSes")
            for pvs in pvs_with_buffering:
                input_file = pvs.get_avpvs_wo_buffer_file_path()
                output_file = pvs.get_avpvs_file_path()

                bufferstring = str(pvs.get_buff_events_media_time()).replace(' ', '')

                pix_fmt = pvs.get_pix_fmt_for_avpvs()

                if cli_args.force:
                    overwrite_spec = "-f"
                else:
                    overwrite_spec = ""

                cmd = 'bufferer -i {input_file} -o {output_file} -b {bufferstring} --force-framerate --black-frame' \
                      '-v ffv1 -a pcm_s16le -x {pix_fmt} -s {cli_args.spinner_path} {overwrite_spec}'.format(**locals())
                cmd_name = str(pvs) + ' buffering'

                cmd_runner_add_buffer.add_cmd(
                    cmd,
                    name=str(cmd_name)
                )
                pvs_commands[pvs.pvs_id].append(cmd)

        if cli_args.dry_run:
            cmd_runner_add_buffer.log_commands()
            sys.exit(0)
        else:
            for pvs in pvs_to_complete:
                write_to_p03_logfile(pvs, pvs_commands[pvs.pvs_id])

        cmd_runner_add_buffer.run_commands()

        if cli_args.remove_intermediate:
            logger.info("removing " + str(len(pvs_with_buffering)) + " intermediate video files")
            for pvs_name in pvs_with_buffering:
                os.remove(pvs.get_avpvs_wo_buffer_file_path())

    # Only run decoding if the test type is "short", only one segment assumed
    else:
        cmd_runner = cmd_utils.ParallelRunner(cli_args.parallelism)
        for pvs in pvs_to_complete:
            if cli_args.skip_online_services and pvs.is_online():
                logger.warn("Skipping PVS {} because it is an online PVS".format(pvs))
                continue
            # add for-loop for post-processing here. What about naming convention? Not necessary for bbqcg
            current_command = ffmpeg.create_avpvs_short(
                    pvs,
                    overwrite=cli_args.force,
                    scale_avpvs_tosource=cli_args.avpvs_src_fps,
                    force_60_fps=cli_args.force_60_fps,
                    post_proc_id=0)
            cmd_runner.add_cmd(current_command,
                               name="Create AVPVS short for " + str(pvs)
                               )

            if not cli_args.dry_run and current_command is not None:
                write_to_p03_logfile(pvs, [current_command, ])

        if cli_args.dry_run:
            cmd_runner.log_commands()
            return test_config

        cmd_runner.run_commands()

    return test_config


def main():
    cli_args = parse_args.parse_args(os.path.basename(__file__), 3)

    # initialize logger
    if cli_args.verbose:
        logger.setLevel(logging.DEBUG)

    check_requirements.check_requirements(skip=cli_args.skip_requirements)

    run(cli_args)


if __name__ == '__main__':
    main()
