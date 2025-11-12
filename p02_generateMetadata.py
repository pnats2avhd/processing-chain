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
import lib.get_framesize as get_framesize

import pandas as pd

logger = log.setup_custom_logger('main')


def run(cli_args, test_config=None):
    if not test_config:
        test_config = cfg.TestConfig(cli_args.test_config, cli_args.filter_src, cli_args.filter_hrc,
                                     cli_args.filter_pvs)

    for pvs_id, pvs in test_config.pvses.items():

        if cli_args.skip_online_services and pvs.is_online():
            logger.warning("Skipping PVS {} because it is an online service".format(pvs))
            continue

        # ---------------------------------------------------------
        # get qchanges info
        # for each seqment, get encoded segment infor and write to qchanges
        pvs_qchanges = []

        for segment in pvs.segments:
            if not segment.exists():
                logger.error("segment " + segment.get_filename() + " does not exist!")
                sys.exit(1)
            pvs_qchanges.append(segment.get_segment_info())

        qchanges_file = os.path.join(test_config.get_quality_change_event_files_path(), pvs_id + '.qchanges')

        # ---------------------------------------------------------
        # write .buff file for PVS
        if pvs.has_buffering():
            buff_events = pvs.get_buff_events_media_time()
            buff_path = test_config.get_buff_event_files_path()
            buff_file = os.path.join(buff_path, pvs_id + '.buff')

            if not cli_args.force and os.path.isfile(buff_file):
                logger.warn(
                    "file " + buff_file + " already exists, not overwriting. Use -f/--force to force overwriting")
            else:
                logger.info("writing buff events to " + buff_file)
                with open(buff_file, 'w') as f:
                    f.write('\n'.join([str(b) for b in buff_events]))
                    f.write('\n')

        # ---------------------------------------------------------
        # collect VFI and AFI
        pvs_vfi = []
        pvs_afi = []

        for segment in pvs.segments:
            if not segment.exists():
                logger.error("segment " + segment.get_filename() + " does not exist!")
                sys.exit(1)
            pvs_vfi.extend(segment.get_video_frame_info())
            pvs_afi.extend(segment.get_audio_frame_info())

        # ---------------------------------------------------------
        # get frame sizes for video codecs, exact method
        cleaned_framesizes = []
        cleaned_segments = 0
        for segment in pvs.segments:
            # print(segment)
            cleaned_segment_size = 0
            segment_codec = segment.get_segment_info()["video_codec"].lower()
            get_framesize_args = (os.path.join(test_config.get_video_segments_path(), segment.get_filename()), cli_args.force)
            if segment_codec == "h264":
                segment_framesizes = get_framesize.get_framesize_h264(*get_framesize_args)
                cleaned_framesizes.extend(segment_framesizes)
            elif segment_codec in ["hevc", "h265"]:
                segment_framesizes = get_framesize.get_framesize_h265(*get_framesize_args)
                cleaned_framesizes.extend(segment_framesizes)
            elif segment_codec == "vp9":
                # delete extraneous packets
                get_framesize.delete_packets(pvs_vfi)
                segment_framesizes = get_framesize.get_framesize_vp9(*get_framesize_args)
                cleaned_framesizes.extend(segment_framesizes)
            elif segment_codec == "av1":
                # this does not work yet, get_framesize_av1 is not yet implemented. Will just return 0.0
                segment_framesizes = get_framesize.get_framesize_av1(*get_framesize_args)
                cleaned_framesizes.extend(segment_framesizes)
            else:
                logger.error("Invalid codec")
                sys.exit(1)
            # get segment size for .qchanges file
            for cur_framesize in segment_framesizes:
                cleaned_segment_size += cur_framesize
            pvs_qchanges[cleaned_segments]["video_bitrate"] = round(cleaned_segment_size/1024*8/pvs_qchanges[cleaned_segments]["video_duration"], 2)
            cleaned_segments += 1

        # ---------------------------------------------------------
        # replace ffprobe framesizes with computed framesizes for vfi file
        if len(pvs_vfi) != len(cleaned_framesizes):
            logger.error("Number of frames detected for " + segment.get_filename() + " does not match!".format(**locals()))
            sys.exit(1)
        for i in range(len(cleaned_framesizes)):
            pvs_vfi[i]["size"] = cleaned_framesizes[i]

        # ---------------------------------------------------------
        # write out .qchanges with adjusted videobitrate
        if not cli_args.force and os.path.isfile(qchanges_file):
            logger.warn(
                "file " + qchanges_file + " already exists, not overwriting. Use -f/--force to force overwriting")
        else:
            logger.info("writing .qchanges to " + qchanges_file)
            pd.DataFrame(pvs_qchanges).to_csv(qchanges_file, index=False)

        # ---------------------------------------------------------
        # write out data
        vfi_file = os.path.join(test_config.get_video_frame_information_path(), pvs_id + '.vfi')
        afi_file = os.path.join(test_config.get_audio_frame_information_path(), pvs_id + '.afi')

        if not cli_args.force and os.path.isfile(vfi_file):
            logger.warn("file " + vfi_file + " already exists, not overwriting. Use -f/--force to force overwriting")
        else:
            logger.info("writing VFI to " + vfi_file)
            pd.DataFrame(pvs_vfi).to_csv(vfi_file, index=False)

        if not cli_args.force and os.path.isfile(afi_file):
            logger.warn("file " + afi_file + " already exists, not overwriting. Use -f/--force to force overwriting")
        else:
            logger.info("writing AFI to " + afi_file)
            pd.DataFrame(pvs_afi).to_csv(afi_file, index=False)

    return test_config


def main():
    cli_args = parse_args.parse_args(os.path.basename(__file__), 2)

    # initialize logger
    if cli_args.verbose:
        logger.setLevel(logging.DEBUG)

    check_requirements.check_requirements(skip=cli_args.skip_requirements)

    run(cli_args)


if __name__ == '__main__':
    main()
