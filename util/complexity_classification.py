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
import argparse
import sys
import math
import pandas as pd
import logging

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

import lib.log as log
from lib.cmd_utils import ParallelRunner
from lib.ffmpeg import get_segment_info

logger = log.setup_custom_logger("main")

# REFERENCE_BITRATE was arbitrarily chosen in order to get a maximum difficulty of around 10
REFERENCE_BITRATE = 2.75

# define thresholds for difficulty classes [~30fps, ~60fps]
DIFFICULTY_CLASS_THRESHOLDS = [[6, 4], [7, 6], [8, 8]]


class Segment:
    """
    Fake segment class to allow calls to get_segment_info
    """

    def __init__(self, path):
        self.filename = "random"
        self.file_path = path


def get_difficulty(output_file):
    info = get_segment_info(Segment(output_file))
    size = info["file_size"]
    duration = info["video_duration"]
    framerate = info["video_frame_rate"]
    nr_pixels = info["video_width"] * info["video_height"]

    # get the normalized bitrate. nr_pixels / 1000 -> prevent norm_bitrate to get too close to zero
    norm_bitrate = size / framerate / duration / (nr_pixels / 1000)

    return {
        "file": os.path.basename(output_file),
        "norm_bitrate": norm_bitrate,
        "complexity": 20 * math.log(norm_bitrate, 10) / REFERENCE_BITRATE,
        "framerate": float(framerate),
        "width": int(info["video_width"]),
        "height": int(info["video_height"]),
        "size": int(size),
        "duration": float(duration),
    }


def classify_complexity(complexity, framerate, quantiles):
    if framerate <= 30:
        curr_quants = quantiles["low"]
    else:
        curr_quants = quantiles["high"]

    comp_class = 0
    if complexity > curr_quants[0.50]:
        if complexity > curr_quants[0.75]:
            comp_class = 3
        else:
            comp_class = 2
    else:
        if complexity > curr_quants[0.25]:
            comp_class = 1

    return comp_class


def parse_args():
    parser = argparse.ArgumentParser(
        description="Complexity classification",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "-i", "--input", required=True, nargs="+", help="Input files (SRCs)"
    )
    parser.add_argument(
        "-t",
        "--tmp-dir",
        default=os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "complexityAnalysis"
        ),
        help="Path to (temporary) complexity analysis folder",
    )
    parser.add_argument(
        "-p", "--parallelism", default=1, help="Number of parallel encodes"
    )
    parser.add_argument(
        "-o",
        "--output-file",
        default="complexity_classification.csv",
        help="Filename of CSV output file",
    )
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Force overwriting (re-analyzing) existing files",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Print debug messages"
    )
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Show what would be run instead of running it",
    )
    return parser.parse_args()


def encode_file(input_file, output_file):
    """
    Encode file with CRF 23
    """
    cmd = "ffmpeg -nostdin -y -i '{input_file}' -pix_fmt yuv420p -an -c:v libx264 -crf 23 '{output_file}'".format(
        **locals()
    )
    return cmd


def main():
    cli_args = parse_args()

    # initialize logger
    if cli_args.verbose:
        logger.setLevel(logging.DEBUG)

    if not os.path.isdir(cli_args.tmp_dir):
        logger.info(
            "temporary directory " + str(cli_args.tmp_dir) + " does not exist, creating"
        )
        os.mkdir(cli_args.tmp_dir)

    if not cli_args.output_file.endswith(".csv"):
        logger.error("Output file must be .csv!")
        sys.exit(1)

    # filter out non-AVI files
    input_files = []
    for f in cli_args.input:
        if f.endswith(".avi"):
            input_files.append(f)
        else:
            logger.warn("Skipping file " + str(f) + " because it is not an .avi file")

    all_data = []

    parallel_runner = ParallelRunner(max_parallel=cli_args.parallelism)

    # handle all input files
    logger.info("Handling " + str(len(cli_args.input)) + " input files")
    output_files = []
    for input_file in input_files:

        # encode file if necessary
        input_file_basename = os.path.splitext(os.path.basename(input_file))[0]
        output_file = os.path.join(cli_args.tmp_dir, input_file_basename + "_crf23.avi")
        if os.path.isfile(output_file) and not cli_args.force:
            logger.warn(
                "Output file "
                + str(output_file)
                + " already exists, use -f to force overwriting"
            )
        else:
            logger.info(
                "Will encode file " + str(input_file) + " to " + str(output_file)
            )
            parallel_runner.add_cmd(encode_file(input_file, output_file))
        output_files.append(output_file)

    if cli_args.dry_run:
        parallel_runner.log_commands()
        sys.exit(0)

    # run encodes
    if parallel_runner.num_commands() > 0:
        logger.info("Starting encoding, this may take a while ...")
        parallel_runner.run_commands()
        logger.info("All encodings completed, will analyze complexity")

    # assemble output data

    for output_file in output_files:
        # get complexity data
        data = get_difficulty(output_file)
        all_data.append(data)

    # write data to output file
    if len(all_data) == 0:
        logger.error("No info calculated, exiting")
        sys.exit(1)

    all_data = pd.DataFrame(all_data)
    all_data = all_data[
        [
            "file",
            "norm_bitrate",
            "complexity",
            "framerate",
            "width",
            "height",
            "size",
            "duration",
        ]
    ].sort_values("file")

    quant_lowfr = all_data[all_data["framerate"] <= 30]["complexity"].quantile(
        [0.25, 0.5, 0.75]
    )
    quant_highfr = all_data[all_data["framerate"] > 30]["complexity"].quantile(
        [0.25, 0.5, 0.75]
    )
    quants = {}
    quants["low"] = quant_lowfr
    quants["high"] = quant_highfr

    all_data["complexity_class"] = all_data.apply(
        lambda x: classify_complexity(x["complexity"], x["framerate"], quants), axis=1
    )

    # write stats to CSV file
    csv_file = os.path.join(cli_args.tmp_dir, cli_args.output_file)
    logger.info("Writing complexity data to " + str(csv_file))
    all_data.to_csv(csv_file, index=False)


if __name__ == "__main__":
    main()
