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

"""
Create .info and .md5 files for each SRC video. If md5-file already exists, perform check. 
"""
import hashlib
import glob
import io
import os
import sys
import yaml
sys.path.append('/processing-chain/')
from multiprocessing import Pool
import argparse
from lib.ffmpeg import get_stream_size, get_segment_info, get_src_info


def md5sum(src, ordernum, length=io.DEFAULT_BUFFER_SIZE):
    md5 = hashlib.md5()

    total = os.path.getsize(src)/length
    with io.open(src, mode="rb") as fd:
        for chunk in iter(lambda: fd.read(length), b''):
            md5.update(chunk)
    basename_src = os.path.basename(src)
    ordernum = str(ordernum).zfill(2)
    print("#{ordernum} is done, name: {basename_src}".format(**locals()))
    return md5


def parse_args(name):
    """Return CLI arguments as dict"""

    parser = argparse.ArgumentParser(description=name)

    parser.add_argument(
        'input',
        nargs='+',
        help='path to input file(s) or folder'
    )
    parser.add_argument(
        '-p', '--concurrency',
        type=int,
        default=4,
        help='number of parallel processes'
    )
    parser.add_argument(
        '-m',  '--skip-md5',
        action='store_true',
        help='Do not calculate or verify the md5-sums'
    )
    parser.add_argument(
        '-s','--skip-src',
        action='store_true',
        help='Do not parse or do SRC analysis'
    )

    parser.add_argument(
        '-f', '--force-overwrite',
        action='store_true',
        help='Force overwrite of existing yamlfiles'
    )

    args = parser.parse_args()
    return args


def sum_file(videofile, ordernum):
    videofile_basename = os.path.basename(videofile)
    md5sum_file = os.path.abspath(videofile) + '.md5'

    md5sum_existing = None
    if os.path.isfile(md5sum_file):
        with open(md5sum_file, 'r') as f:
            # read MD5 sum directly or as given in the format of "md5sum" CLI call
            md5sum_existing = f.readlines()[0].strip().split(" ")[0]
    md5sum_current = md5sum(videofile, ordernum)

    returntext = ''
    if md5sum_existing:
        if md5sum_existing == md5sum_current.hexdigest():
            returntext = "ok    -- File: {videofile_basename} has a correct md5sum".format(**locals())
        else:
            returntext = "BAD!! -- File: {videofile_basename} has an erroneous md5sum".format(**locals())
    else:
        with open(md5sum_file, 'w+') as f:
            f.write(str(md5sum_current.hexdigest()) + " " + videofile_basename + "\n")
        returntext = "md5sum file written for file: {videofile_basename}".format(**locals())
    return(returntext)


class Src:
    def __init__(self, path):
        self.file_path = path
        self.info_path = False


class Segment:
    def __init__(self, path, src):
        self.file_path = path
        self.src = src
        self.info_path = False


def analyse_src(videofile, ordernum):
    returntext = {}

    src = Src(videofile)
    seg = Segment(videofile, src)

    videoinfo = get_src_info(src)
    videosize = get_stream_size(seg)
    audiosize = get_stream_size(seg, 'audio')

    md5filename = videofile + '.md5'

    if not os.path.isfile(md5filename):
        calcmd5 = md5sum(videofile, ordernum)
        md5hash = str(calcmd5.hexdigest())
    else:
        with open(md5filename, 'r') as f:
            md5hash = f.readlines()[0].strip().split(" ")[0]

    returntext['md5sum'] = md5hash
    returntext['get_stream_size'] = {"v": videosize, "a": audiosize}
    returntext['get_src_info'] = videoinfo

    yaml_path = videofile + '.yaml'
    with open(yaml_path, 'w') as outfile:
        yaml.dump(returntext, outfile, default_flow_style=False)

    return(yaml_path)


def dump_log(listofdata, output_name):
    outfile_h = open(output_name, 'w+')
    for ii in listofdata:
        outfile_h.write(ii)
    outfile_h.close()


def main():
    cli_args = parse_args("SRC analysis")
    videofiles = []
    for entry in cli_args.input:
        if os.path.isdir(entry):
            video_ext = ["mp4", "avi", "mov", "mkv", "y4m"]
            for extension in video_ext:
                videofiles.extend(glob.glob(os.path.join(entry, "*." + extension)))
        elif os.path.isfile(entry):
            videofiles.append(entry)
        else:
            print("Meh: " + str(entry) + " is not a file or folder")

    if not(cli_args.force_overwrite):
        videofiles = [ii for ii in videofiles if not(os.path.isfile(ii + '.yaml'))]

    print(str(len(videofiles)) + ' files will be processed ...')

    call_args = [(f, x) for f, x in zip(videofiles, list(range(len(videofiles))))]

    if not cli_args.skip_md5:
        if cli_args.concurrency == 1:
            # single-threaded for debugging
            output_md5 = ""
            for it, file in enumerate(videofiles):
                output_md5 = output_md5 + sum_file(file, it) + "\n"
            print(output_md5)
        else:
            pool = Pool(cli_args.concurrency)
            output_md5 = pool.starmap(sum_file, call_args)
            print()
            print("MD5 Results:")
            print("\n".join(output_md5))
            print()

        dump_log(output_md5, './outsummary_md5.txt')

    if not cli_args.skip_src:

        if cli_args.concurrency == 1:
            # single threaded for debugging
            for it, v_file in enumerate(videofiles):
                output_src = analyse_src(v_file, it)
                print(output_src)
        else:
            pool = Pool(cli_args.concurrency)
            output_src = pool.starmap(analyse_src, call_args)
            print()
            print("INFO Results:")
            print("\n".join(output_src))
            print()


if __name__ == '__main__':
    main()
