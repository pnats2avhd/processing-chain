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
FFmpeg helpers
"""

import os
import sys
import json
from fractions import Fraction
from collections import OrderedDict
import lib.cmd_utils as cmd_utils
import logging
import itertools
import yaml
logger = logging.getLogger('main')


def calculate_avpvs_video_dimensions(SRC_width, SRC_height, postproc_enc_width, postproc_enc_height):
    """
    Return the width and height that the avpvs-script will use to produce a suitable avpvs-file.

    Arguments:
        SRC_width, SRC_height: Encoding width and height for the SRC clip, in pixels
        postproc_enc_width, postproc_enc_height: Encoding width and height for the postprocessing, in pixels
        dims: List with [avpvs_width, avpvs_height] in pixels
    """

    dims = [postproc_enc_width, postproc_enc_height]

    if not(SRC_width == postproc_enc_width & SRC_height == postproc_enc_height):
        SRC_aspect_ratio = SRC_width / SRC_height
        postproc_aspect_ratio = postproc_enc_width / postproc_enc_height
        if postproc_enc_width < SRC_width:  # ismobile?
            if not(SRC_aspect_ratio == postproc_aspect_ratio):
                avpvs_height = int(float(postproc_enc_width) / SRC_aspect_ratio)
                if avpvs_height % 2 == 1:
                    avpvs_height += 1
                dims[1] = avpvs_height
        else:
            dims[1] = SRC_height

    return(dims)


def _get_video_encoder_command(segment, current_pass=1, total_passes=1, logfile=""):
    """
    Return the video encoder command needed for encoding a particular segment,
    depending on its encoding settings.

    Call this function twice, once with current_pass=1, once with
    current_pass=2, for two-pass. Set total_passes to 2.

    segment: Reference to Segment class
    current_pass: Number of pass to generate
    total_passes: Number of total passes
    logfile: filename path for passlogfile
    = segment.target_video_bitrate
    #bitrate = segment.quality_level.video_bitrate
    """

    if not segment.video_coding.crf:
        bitrate = segment.target_video_bitrate

    # settings that will already be defined
    encoder = segment.video_coding.encoder
    quality = segment.video_coding.quality
    speed = segment.video_coding.speed
    scenecut = segment.video_coding.scenecut
    pix_fmt = segment.target_pix_fmt
    # if segment.video_coding.forced_pix_fmt:
    #     pix_fmt = segment.video_coding.forced_pix_fmt

    # get target FPS
    _, target_fps = _get_fps(segment)
    if target_fps is None:
        target_fps = segment.src.get_fps()

    # optional settings
    preset = segment.video_coding.preset
    bframes = segment.video_coding.bframes

    iframe_interval = segment.video_coding.iframe_interval

    # set speed to 4 for first pass:
    if encoder == "libvpx-vp9" and total_passes == 2 and current_pass == 1:
        speed = 4

    # construct pass commands
    if total_passes == 1:
        pass_cmd = ""
        passlogfile_cmd = ""
    elif total_passes == 2 and current_pass <= total_passes:
        pass_cmd = "-pass " + str(current_pass)
        passlogfile_cmd = "-passlogfile '" + str(logfile) + "'"
    else:
        logger.error("incorrect 'pass' parameters")
        sys.exit(1)

    # general commands for all encoding types
    # preset
    if preset:
        preset_cmd = "-preset " + preset
    else:
        preset_cmd = ""

    if encoder in ["libx264", "h264_nvenc"]:
        # construct rate control commands
        if segment.video_coding.crf:
            rate_control_cmd = "-crf " + str(segment.quality_level.video_crf) + " "
        else:
            rate_control_cmd = "-b:v " + str(bitrate) + "k "

        if segment.video_coding.maxrate_factor:
            rate_control_cmd += "-maxrate " + str(segment.video_coding.maxrate_factor * bitrate) + "k "
        if segment.video_coding.bufsize_factor:
            rate_control_cmd += "-bufsize " + str(segment.video_coding.bufsize_factor * bitrate) + "k "
        if segment.video_coding.minrate_factor:
            rate_control_cmd += "-minrate " + str(segment.video_coding.minrate_factor * bitrate) + "k "

        # keyframe interval
        if iframe_interval:
            target_interval = int(target_fps * iframe_interval)
            iframe_interval_cmd = "-g " + str(target_interval) + " -keyint_min " + str(target_interval)

        nvenc_options = ""
        if segment.video_coding.nvenc_options:
            nvenc_options = segment.video_coding.nvenc_options

        x264_params = []
        x264_params_cmd = ""

        # scenecuts
        if not scenecut:
            x264_params.append("scenecut=-1")

        # bframes
        if bframes:
            x264_params.append("bframes=" + str(bframes))

        # join all params
        if len(x264_params) & (encoder == 'libx264'):
            x264_params_cmd = "-x264-params " + ":".join(x264_params)

        cmd = """
        -c:v {encoder}
        {rate_control_cmd}
        {iframe_interval_cmd}
        {x264_params_cmd}
        {preset_cmd}
        -pix_fmt {pix_fmt}
        {nvenc_options}
        {pass_cmd} {passlogfile_cmd}
        """.format(**locals())

    elif encoder in ["libx265", "hevc_nvenc"]:

        # Supported pixel formats: yuv420p nv12 p010le yuv444p p016le yuv444p16le bgr0 rgb0 cuda
        # For hevc_nvenc

        # construct rate control commands

        if segment.video_coding.crf:
            rate_control_cmd = "-crf " + str(segment.quality_level.video_crf) + " "
        else:
            rate_control_cmd = "-b:v " + str(bitrate) + "k "

        x265_params = []
        minrate_cmd = ""
        if segment.video_coding.maxrate_factor:
            if encoder == 'libx265':
                x265_params.append("vbv-maxrate=" + str(int(segment.video_coding.maxrate_factor * bitrate)))
            else:
                minrate_cmd += "-maxrate " + str(int(segment.video_coding.maxrate_factor * bitrate)) + "k "
        if segment.video_coding.bufsize_factor:
            if encoder == 'libx265':
                x265_params.append("vbv-bufsize=" + str(int(segment.video_coding.bufsize_factor * bitrate)))        
            else:
                minrate_cmd += "-bufsize " + str(int(segment.video_coding.bufsize_factor * bitrate)) + "k "
            # x265_params.append("vbv-bufsize=" + str(int(segment.video_coding.bufsize_factor * bitrate)))
        if segment.video_coding.minrate_factor:
            minrate_cmd += "-minrate " + str(int(segment.video_coding.minrate_factor * bitrate)) + "k "

        # keyframe interval
        if iframe_interval:
            target_interval = int(target_fps * iframe_interval)
            if encoder == 'libx265':
                x265_params.append("keyint=" + str(target_interval))
                x265_params.append("min-keyint=" + str(target_interval))
            else:
                preset_cmd += ' -g ' + str(target_interval)

        # scenecut
        if scenecut is not False:
            x265_params.append("scenecut=0")

        # bframes
        if bframes is not None:
            x265_params.append("bframes=" + str(bframes))

        # override pass command for libx265
        if total_passes == 2 and current_pass <= total_passes:
            x265_params.append("pass=" + str(current_pass))

        # override passlogfile command for libx265
        if total_passes == 2 and current_pass <= total_passes:
            x265_params.append("stats='" + str(logfile) + "'")

        x265_params_cmd = ""
        if len(x265_params) & (encoder == 'libx265'):
            x265_params_cmd = "-x265-params " + ":".join(x265_params)

        nvenc_options = ""
        if segment.video_coding.nvenc_options:
            nvenc_options = segment.video_coding.nvenc_options

        cmd = """
        -c:v {encoder}
        {rate_control_cmd}
        {minrate_cmd}
        {x265_params_cmd}
        {preset_cmd}
        {nvenc_options}
        -pix_fmt {pix_fmt}
        """.format(**locals())

    elif encoder == "libvpx-vp9":
        # construct rate control commands
        if segment.video_coding.crf:
            rate_control_cmd = "-b:v 0 -crf " + str(segment.quality_level.video_crf) + " "
        else:
            rate_control_cmd = "-b:v " + str(bitrate) + "k "

        if segment.video_coding.maxrate_factor:
            rate_control_cmd += "-maxrate " + str(segment.video_coding.maxrate_factor * bitrate) + "k "
        if segment.video_coding.bufsize_factor:
            rate_control_cmd += "-bufsize " + str(segment.video_coding.bufsize_factor * bitrate) + "k "
        if segment.video_coding.minrate_factor:
            rate_control_cmd += "-minrate " + str(segment.video_coding.minrate_factor * bitrate) + "k "

        # keyframe interval
        if iframe_interval:
            target_interval = int(target_fps * iframe_interval)
            iframe_interval_cmd = "-g " + str(target_interval) + " -keyint_min " + str(target_interval)
        else:
            iframe_interval_cmd = ""

        cmd = """
        -c:v {encoder}
        {rate_control_cmd}
        {iframe_interval_cmd}
        -strict -2
        -quality {quality}
        -speed {speed}
        -pix_fmt {pix_fmt}
        {pass_cmd} {passlogfile_cmd}
        """.format(**locals())

    elif encoder == "libaom-av1":
        # construct rate control commands
        if segment.video_coding.crf:
            rate_control_cmd = "-b:v 0 -crf " + str(segment.quality_level.video_crf) + " "
        else:
            rate_control_cmd = "-b:v " + str(bitrate) + "k "

        if segment.video_coding.maxrate_factor:
            rate_control_cmd += "-maxrate " + str(segment.video_coding.maxrate_factor * bitrate) + "k "
        if segment.video_coding.minrate_factor:
            rate_control_cmd += "-minrate " + str(segment.video_coding.minrate_factor * bitrate) + "k "

        # keyframe interval
        if iframe_interval:
            target_interval = int(target_fps * iframe_interval)
            iframe_interval_cmd = "-g " + str(target_interval) + " -keyint_min " + str(target_interval)
        else:
            iframe_interval_cmd = ""

        if not scenecut:
            iframe_interval_cmd += " -sc_threshold 0 "

        cmd = """
        -c:v {encoder}
        {rate_control_cmd}
        {iframe_interval_cmd}
        -strict -2 -tile-columns 1 -tile-rows 0 -threads 4 -cpu-used 6 -row-mt 1 -usage 1 -enable-global-motion 0 -enable-intrabc 0 -enable-restoration 0
        -pix_fmt {pix_fmt}
        {pass_cmd} {passlogfile_cmd}
        """.format(**locals())

    else:
        logger.error("wrong encoder: " + str(encoder))
        sys.exit(1)

    return cmd


def _get_fps(segment):
    """
    Return the fps filter spec and calculated fps for ffmpeg for that segment,
    based on the FPS specification in the test configuration (quality level).

    This can be one of:

    - a number
    - a fraction (e.g. "1/2")
    - the string "original"
    - the string "auto"
    - the string "50/60"
    - the string "24/25/30"
    """
    fps_spec = segment.quality_level.fps
    fps = None

    # keep the original framerate
    if fps_spec == "original":
        fps = None

    # set to auto for YouTube
    elif fps_spec == "auto":
        fps = None

    # handle special case where FPS are to be selected from SRC framerate
    elif (fps_spec == "24/25/30"):
        orig_fps = segment.src.get_fps()

        # if the SRC is between 24 and 30, just take it as-is
        if orig_fps in [24, 25, 30]:
            fps = None
        # if the SRC is 50/60 we take half of it:
        elif orig_fps == 50:
            fps = 25
        elif orig_fps in [60, 120]:
            fps = 30
        else:
            logger.error("SRC " + str(segment.src) + " has unsupported frame rate (" + str(orig_fps) + ")")
            sys.exit(1)

    # handle special case where FPS are to be selected from SRC framerate
    elif fps_spec == "50/60":
        orig_fps = segment.src.get_fps()

        if orig_fps in [50, 60]:
            fps = None
        elif orig_fps < 50:
            logger.error("fps for " + str(segment) + " were requested as 50/60 but SRC has only " + str(orig_fps))
            sys.exit(1)
        elif orig_fps == 120:
            fps = 60
        else:
            logger.error("SRC " + str(segment.src) + " has unsupported frame rate (" + str(orig_fps) + ")")
            sys.exit(1)

    # use a given fraction (e.g. 2/3) of the original
    elif "/" in str(fps_spec):
        frac = float(Fraction(fps_spec))
        orig_fps = segment.src.get_fps()
        fps = orig_fps * frac
        # sanity check:
        if (fps > 60) or (fps < 12):
            logger.warn("fps for " + str(segment) + " were calculated as " + str(fps) + " which does not seem right")

    # just take the specific FPS value, e.g. 15
    else:
        fps = int(fps_spec)

    # construct the ffmpeg command, either none (take FPS as-is) or use the "fps" filter
    if fps is None:
        fps_cmd = None
    else:
        fps_cmd = "fps=fps=" + str(fps)

    return (fps_cmd, fps)


def get_stream_size(segment, stream_type="video"):
    """
    Return the video stream size in Bytes, as determined by summing up the individual
    frame size.

    stream_type: either "video" or "audio"
    """
    switch = "v" if stream_type == "video" else "a"
    cmd = "ffprobe -loglevel error -select_streams " + switch + " -show_entries packet=size -of compact=p=0:nk=1  '" + segment.file_path + "'"

    if os.path.isfile(segment.file_path + '.yaml'):
        with open(segment.file_path + '.yaml') as f_in:
            ydata = yaml.load(f_in, Loader=yaml.FullLoader)
            size = ydata['get_stream_size'][switch]
    else:
        stdout, _ = cmd_utils.run_command(cmd, name="get accumulated frame size for " + str(segment))
        size = sum([int(ll) for ll in stdout.split("\n") if ll != ""])

    return size


def fix_video_profile_string(video_profile):
    """
    Return a proper string for the video profiles.
    """
    video_profile = video_profile.replace(" ", "")
    video_profile = video_profile.replace("Profile", "")
    video_profile = video_profile.replace("High", "Hi")
    video_profile = video_profile.replace(":", "")
    video_profile = video_profile.replace("Predictive", "P")

    return video_profile


def get_segment_info(segment):
    """
    Get the info about the segment, as shown by ffprobe, for use in .qchanges file

    Returns an OrderedDict, with the keys:
    - `segment_filename`: Basename of the segment file
    - `file_size`: Size of the file in bytes
    - `video_duration`: Duration of the video in `s.msec`
    - `video_frame_rate`: Framerate in Hz
    - `video_bitrate`: Bitrate of the video stream in kBit/s
    - `video_target_bitrate`: Target bitrate of the video stream in kBit/s (may be empty/unknown)
    - `video_width`: Width in pixels
    - `video_height`: Height in pixels
    - `video_codec`: Video codec (`h264`, `hevc`, `vp9`, `av1`)
    - `video_profile`: Video profile
    - `audio_duration`: Duration of the audio in `s.msec`
    - `audio_sample_rate`: Audio sample rate in Hz
    - `audio_codec`: Audio codec name (`aac`)
    - `audio_bitrate`: Bitrate of the video stream in kBit/s
    """
    input_file = segment.file_path

    if sys.platform == "darwin":
        cmd = "stat -f '%z' '" + input_file + "'"
    else:
        cmd = "stat -c '%s' '" + input_file + "'"
    stdout, _ = cmd_utils.run_command(cmd, name="get segment size for " + str(segment))
    segment_size = int(stdout.strip())

    cmd = "ffprobe -loglevel error -show_streams -of json '" + input_file + "'"
    stdout, _ = cmd_utils.run_command(cmd, name="get segment video info for " + str(segment))
    info = json.loads(stdout)
    has_video = False
    has_audio = False
    for stream_info in info["streams"]:
        if stream_info["codec_type"] == "video":
            video_info = stream_info
            has_video = True
        elif stream_info["codec_type"] == "audio":
            audio_info = stream_info
            has_audio = True

    if not has_video:
        logger.error("No video stream found in segment " + str(segment))
        sys.exit(1)

    if 'duration' in video_info.keys():
        video_duration = float(video_info['duration'])
    elif 'tags' in video_info.keys() and 'DURATION' in video_info['tags']:
        duration_str = video_info['tags']['DURATION']
        hms, msec = duration_str.split('.')
        total_dur = sum(int(x) * 60 ** i for i, x in enumerate(reversed(hms.split(":"))))
        video_duration = total_dur + float("0." + msec)
    else:
        info_type = 'packet'
        cmd = "ffprobe -loglevel error -select_streams v -show_packets -show_entries packet=pts_time,dts_time,duration_time,size,flags -of json '" + segment.file_path + "'"
        stdout, _ = cmd_utils.run_command(cmd, name="get VFI for " + str(segment))
        info = json.loads(stdout)[info_type + "s"]
        index = -1
        while True:
            packet_info = info[index]
            if 'dts_time' in packet_info.keys() and 'duration_time' in packet_info.keys():
                video_duration = float(packet_info['dts_time']) + abs(index)*float(packet_info['duration_time'])
                break
            index = index - 1
        logger.warning("Calculated duration of segment " + str(segment) + " manually. Might not be perfectly accurate.")

    if not video_duration:
        logger.error("Video duration of " + str(segment) + " was calculated as zero! Make sure that the input file is correct.")
        sys.exit(1)

    if 'bit_rate' in video_info.keys():
        video_bitrate = round(float(video_info['bit_rate']) / 1024.0, 2)
    else:
        # fall back to calculating from accumulated frame duration
        stream_size = get_stream_size(segment)
        video_bitrate = round((stream_size * 8 / 1024.0) / video_duration, 2)

    if hasattr(segment, "quality_level"):
        video_target_bitrate = segment.quality_level.video_bitrate
    else:
        video_target_bitrate = 0

    # override designation of video profile:
    if 'profile' in video_info.keys():
        video_profile = fix_video_profile_string(video_info['profile'])
    else:
        video_profile = ""

    ret = OrderedDict([
        ('segment_filename', segment.filename),
        ('file_size', segment_size),
        ('video_duration', video_duration),
        ('video_frame_rate', float(Fraction(video_info['r_frame_rate']))),
        ('video_bitrate', video_bitrate),
        ('video_target_bitrate', video_target_bitrate),
        ('video_width', video_info['width']),
        ('video_height', video_info['height']),
        ('video_codec', video_info['codec_name']),
        ('video_profile', video_profile)
    ])

    if has_audio:
        if 'duration' in audio_info.keys():
            audio_duration = float(audio_info['duration'])
        elif 'tags' in audio_info.keys() and 'DURATION' in audio_info['tags']:
            duration_str = audio_info['tags']['DURATION']
            hms, msec = duration_str.split('.')
            total_dur = sum(int(x) * 60 ** i for i, x in enumerate(reversed(hms.split(":"))))
            audio_duration = total_dur + float("0." + msec)
        elif 'nb_frames' in audio_info.keys():
            audio_duration = float(audio_info['nb_frames']) / float(audio_info['sample_rate'])
        else:
            logger.error("Could not extract audio duration from " + str(segment))
            sys.exit(1)

        if 'bit_rate' in audio_info.keys():
            audio_bitrate = round(float(audio_info['bit_rate']) / 1024.0, 2)
        else:
            # fall back to calculating from accumulated frame duration
            stream_size = get_stream_size(segment, stream_type="audio")
            audio_bitrate = round((stream_size * 8 / 1024.0) / audio_duration, 2)

        ret.update(OrderedDict([
            ('audio_duration', audio_duration),
            ('audio_sample_rate', audio_info['sample_rate']),
            ('audio_codec', audio_info['codec_name']),
            ('audio_bitrate', audio_bitrate)
        ]))

    return ret


def get_src_info(src):
    """
    Get info about the SRC, as shown by ffprobe.
    Possible return keys, including example output:
        - codec_name: "h264"
        - codec_long_name: "H.264 / AVC / MPEG-4 AVC / MPEG-4 part 10"
        - profile: "High 4:4:4 Predictive"
        - codec_type: "video"
        - codec_time_base: "1/120"
        - codec_tag_string: "avc1"
        - codec_tag: "0x31637661"
        - width: 3840
        - height: 2160
        - coded_width: 3840
        - coded_height: 2160
        - has_b_frames: 0
        - sample_aspect_ratio: "1:1"
        - display_aspect_ratio: "16:9"
        - pix_fmt: "yuv444p"
        - level: 52
        - chroma_location: "left"
        - refs: 1
        - is_avc: "true"
        - nal_length_size: "4"
        - r_frame_rate: "60/1"
        - avg_frame_rate: "60/1"
        - time_base: "1/15360"
        - start_pts: 0
        - start_time: "0.000000"
        - duration_ts: 153600
        - duration: "10.000000"
        - bit_rate: "1569904"
        - bits_per_raw_sample: "8"
        - nb_frames: "600"
    """
    input_file = src.file_path

    cmd = "ffprobe -loglevel error -select_streams v -show_streams -of json '" + input_file + "'"
    if not os.path.isfile(src.info_path):
        stdout, _ = cmd_utils.run_command(cmd, name="get SRC info for " + str(src))
        info = json.loads(stdout)
        returndata = info["streams"][0]
        if '/' in returndata['r_frame_rate']:
            returndata['r_frame_rate'] = str(int(eval(returndata['r_frame_rate'])))

        videosize = get_stream_size(src)
        audiosize = get_stream_size(src, 'audio')

        info_to_dump = {}
        info_to_dump['md5sum'] = '-'
        info_to_dump['get_stream_size'] = {"v": videosize, "a": audiosize}
        info_to_dump['get_src_info'] = returndata

        with open(src.info_path, 'w') as outfile:
            yaml.dump(info_to_dump, outfile, default_flow_style=False)
    else:
        with open(src.info_path) as f_in:
            ydata = yaml.load(f_in, Loader=yaml.FullLoader)
            returndata = ydata['get_src_info']
    return returndata


def get_video_frame_info(segment, info_type="packet"):
    """
    Return a list of OrderedDicts with video frame info, in decoding or presentation order
    info_type: "packet" or "frame", if packet: decoding order, if frame: presentation order

    Return keys:
        - `segment`: basename of the segment file
        - `index`: index of the frame
        - `frame_type`: `I` or `Non-I` (for decoding order) or `I`, `P`, `B` (for presentation order)
        - `dts`: DTS of the frame (only for decoding order)
        - `pts`: PTS of the frame
        - `size`: Size of the packet in bytes (including SPS, PPS for first frame, and AUD units for subsequent frames)
        - `duration`: Duration of the frame in `s.msec`
    """
    if info_type == "packet":
        cmd = "ffprobe -loglevel error -select_streams v -show_packets -show_entries packet=pts_time,dts_time,duration_time,size,flags -of json '" + segment.file_path + "'"
    elif info_type == "frame":
        cmd = "ffprobe -loglevel error -select_streams v -show_frames -show_entries frame=pkt_pts_time,pkt_dts_time,pkt_duration_time,pkt_size,pict_type -of json '" + segment.file_path + "'"
    else:
        logger.error("wrong info type, can be 'packet' or 'frame'")
        sys.exit(1)

    stdout, _ = cmd_utils.run_command(cmd, name="get VFI for " + str(segment))
    info = json.loads(stdout)[info_type + "s"]

    # Assemble info into OrderedDict
    if info_type == "packet":
        ret = []
        index = 0

        default_duration = next((x["duration_time"] for x in info if "duration_time" in x.keys()), "NaN")

        for packet_info in info:
            frame_type = "I" if packet_info['flags'] == "K_" else "Non-I"

            if 'dts_time' in packet_info.keys():
                dts = float(packet_info['dts_time'])
            else:
                dts = "NaN"

            if 'duration_time' in packet_info.keys():
                duration = float(packet_info['duration_time'])
            else:
                duration = default_duration

            ret.append(OrderedDict([
                ('segment', segment.get_filename()),
                ('index', index),
                ('frame_type', frame_type),
                ('dts', dts),
                ('size', packet_info['size']),
                ('duration', duration)
            ]))
            index += 1

    elif info_type == "frame":
        ret = []
        index = 0
        for frame_info in info:
            if 'pts_time' in frame_info.keys():
                pts = float(frame_info['pts_time'])
            else:
                pts = "NaN"
            ret.append(OrderedDict([
                ('segment', segment.get_filename()),
                ('index', index),
                ('frame_type', frame_info['pict_type']),
                ('pts', pts),
                ('size', int(frame_info['pkt_size'])),
                ('duration', float(frame_info['pkt_duration_time']))
            ]))
            index += 1
    else:
        # cannot happen
        pass

    # fix for missing duration in VP9: estimate duration from DTS difference
    ret = fix_durations(ret)

    return ret


def fix_durations(frame_info):
    """
    Add missing durations to a list of frame info dicts
    """
    # iterator between current and next
    a, b = itertools.tee(frame_info)
    next(b, None)
    prev_duration = None

    # go through frames and assign difference between DTS as duration
    for current_frame, next_frame in zip(a, b):
        if current_frame['duration'] != 'NaN':
            continue
        duration = round(next_frame['dts'] - current_frame['dts'], 6)
        current_frame['duration'] = duration
        prev_duration = duration

    # if previous duration has been set, replacement for the last
    # frame needs to be done
    if prev_duration:
        if frame_info[-1]['duration'] == 'NaN':
            frame_info[-1]['duration'] = prev_duration

    return frame_info


def get_audio_frame_info(segment):
    """
    Return a list of OrderedDicts with audio sample info, in presentation order

    Keys:
        - `segment`: basename of the segment file
        - `index`: index of the frame
        - `dts`: DTS of the sample
        - `size`: Size of the sample in bytes
        - `duration`: Duration of the sample in `s.msec`
    """
    cmd = "ffprobe -loglevel error -select_streams a -show_packets -show_entries packet=duration_time,size,dts_time -of json '" + segment.file_path + "'"
    stdout, _ = cmd_utils.run_command(cmd, name="get AFI for " + str(segment))
    info = json.loads(stdout)["packets"]
    ret = []
    index = 0
    for packet_info in info:
        ret.append(OrderedDict([
            ('segment', segment.get_filename()),
            ('index', index),
            ('dts', float(packet_info['dts_time'])),
            ('size', int(packet_info['size'])),
            ('duration', float(packet_info['duration_time']))
        ]))
        index += 1
    return ret


def encode_segment(segment, overwrite=False):
    """
    Encodes a segment using its options.
    Returns the command that needs to be called.
    """
    test_config = segment.src.test_config

    input_file = segment.src.file_path
    output_file = os.path.join(test_config.get_video_segments_path(), segment.get_filename())

    if overwrite:
        overwrite_spec = "-y"
    else:
        overwrite_spec = "-n"
        if os.path.isfile(output_file):
            logger.warn("output " + output_file + " already exists, will not convert. Use --force to force overwriting.")
            return None

    nr_threads_opt = ' -threads 1'
    if segment.quality_level.video_codec == 'av1':
        nr_threads_opt = ''

    # Filters
    filter_list = []

    # Size handling
    width = segment.quality_level.width
    height = segment.quality_level.height
    filter_list.append("scale={width}:-2:flags=bicubic".format(**locals()))

    # FPS handling
    (fps_cmd, calculated_fps) = _get_fps(segment)
    orig_fps = float(Fraction(segment.src.stream_info["r_frame_rate"]))

    if fps_cmd:
        fps_perc = 100 * calculated_fps / orig_fps
        if int(fps_perc) != 100:
            adv_select = ''

            if int(fps_perc) == 50:  # fps 60->30, 24->12
                adv_select = "mod(n+1,2)"
            elif int(fps_perc) == 40:  # fps 60->24
                adv_select = "not(mod(n,5))+not(mod(n-3,5))"
            elif int(fps_perc) == 33:  # fps 60->20, 24->8
                adv_select = "not(mod(n,3))"
            elif int(fps_perc) == 25:  # fps 60->15, 24->6
                adv_select = "not(mod(n,4))"
            elif int(fps_perc) == 80:  # # fps 30->24, this usually does not look good
                adv_select = "mod(n+1,5)"
            elif int(fps_perc) == 30:  # fps 50->15
                adv_select = "not(mod(n,10)) + not(mod(n-3,10)) + not(mod(n-7,10))"
            elif int(fps_perc) == 60:  # fps 25->15
                adv_select = "not(mod(n,5))+not(mod(n-3,5))+not(mod(n-2,5))"
            elif fps_perc == 62.5:  # fps 24->15
                adv_select = "not(mod(n,8))+not(mod(n-3,8))+not(mod(n-2,8))+not(mod(n-5,8))+not(mod(n-6,8))"
            else:
                logger.error("Frame rate conversion from " + str(orig_fps) + " to " + str(calculated_fps) + " is not supported in segment " + str(segment))
                sys.exit(1)

            filter_list.append("select=\'" + adv_select + "\'")
        filter_list.append("fps=fps=" + str(calculated_fps))    
    else:
        filter_list.append("fps=fps=" + str(orig_fps))

    filters = ",".join(filter_list)
    filters = "\"" + filters + "\""

    # Audio coding (only for long tests)
    if test_config.type == "long":
        audio_bitrate = segment.quality_level.audio_bitrate
        audio_encoder = segment.audio_coding.encoder
        audio_encoder_cmd = "-c:a {audio_encoder} -b:a {audio_bitrate}k".format(**locals())
    else:
        audio_encoder_cmd = ""

    # Construct command for pass 1 and 2
    if segment.video_coding.passes == 2:

        # Common commands for both passes
        common_opts = """
        -nostdin
        -ss {segment.start_time} -i {input_file}
        {nr_threads_opt}
        -t {segment.duration}
        -video_track_timescale 90000
        -filter:v {filters}
        {audio_encoder_cmd}
        """.format(**locals())

        # Rate control and other options
        log_path = test_config.get_logs_path()

        passlogfile = os.path.join(
            log_path,
            'passlogfile_' + os.path.splitext(os.path.basename(output_file))[0]
        )
        video_encoder_cmd_pass1 = _get_video_encoder_command(segment, current_pass=1, total_passes=2, logfile=passlogfile)
        video_encoder_cmd_pass2 = _get_video_encoder_command(segment, current_pass=2, total_passes=2, logfile=passlogfile)

        # combine pass 1 and 2 commands
        if segment.ext == "mp4":
            output_format = "mp4"
        elif segment.ext == "mkv":
            output_format = "matroska"
        else:
            logger.error("unknown segment extension " + segment.ext)

        pass1_cmd = " ".join([
            "ffmpeg",
            "-y",
            common_opts,
            video_encoder_cmd_pass1,
            "-f",
            output_format,
            "/dev/null"
        ])
        pass2_cmd = " ".join([
            "ffmpeg",
            overwrite_spec,
            common_opts,
            video_encoder_cmd_pass2,
            output_file
        ])
        cmd = pass1_cmd + " && " + pass2_cmd

    # simple 1-pass version
    elif segment.video_coding.passes == 1:
        # Rate control and other options
        video_encoder_cmd = _get_video_encoder_command(segment)

        cmd = """
        ffmpeg -nostdin
        {overwrite_spec}
        -ss {segment.start_time} -i {input_file}
        {nr_threads_opt}
        -t {segment.duration}
        -video_track_timescale 90000
        -filter:v {filters}
        {video_encoder_cmd}
        {audio_encoder_cmd}
        {output_file}
        """.format(**locals())

    elif segment.video_coding.crf:
        video_encoder_cmd = _get_video_encoder_command(segment)

        cmd = """
        ffmpeg -nostdin
        {overwrite_spec}
        -ss {segment.start_time} -i {input_file}
        {nr_threads_opt}
        -t {segment.duration}
        -video_track_timescale 90000
        -filter:v {filters}
        {video_encoder_cmd}
        {audio_encoder_cmd}
        {output_file}
        """.format(**locals())
    else:
        logger.error("only 1 or 2 pass or crf encoding implemented")
        sys.exit(1)

    # remove multiple spaces
    cmd = (" ").join(cmd.split())

    return cmd


def create_avpvs_short(pvs, overwrite=False, scale_avpvs_tosource=False):
    """
    Decode the first segment and create AVPVS using FFV1 and FLAC.
    """
    test_config = pvs.test_config

    # FIXME: this only use the first post_processing-context now. Have to send each individual post processing context to create_avpvs_short and loop over it in p03/4 later. naming?
    coding_width = test_config.post_processings[0].coding_width
    coding_height = test_config.post_processings[0].coding_height

    # output_file = pvs.get_avpvs_file_path()

    if pvs.has_buffering():
        output_file = pvs.get_avpvs_wo_buffer_file_path()
    else:
        output_file = pvs.get_avpvs_file_path()

    if scale_avpvs_tosource:
        src_framerate = pvs.src.get_fps()
    else:
        src_framerate = 60.0

    if overwrite:
        overwrite_spec = "-y"
    else:
        overwrite_spec = "-n"
        if os.path.isfile(output_file):
            logger.warn("output " + output_file + " already exists, will not convert. Use --force to force overwriting.")
            return None

    input_file = pvs.segments[0].get_segment_file_path()
    target_pix_fmt = pvs.get_pix_fmt_for_avpvs()

    [avpvs_width, avpvs_height] = calculate_avpvs_video_dimensions(
        pvs.src.stream_info['coded_width'], pvs.src.stream_info['coded_height'],
        coding_width, coding_height)

    cmd = """
    ffmpeg -nostdin
    {overwrite_spec}
    -i {input_file}
    -filter:v scale={avpvs_width}:{avpvs_height}:flags=bicubic,fps={src_framerate},setsar=1/1
    -c:v ffv1 -threads 4 -level 3 -coder 1 -context 1 -slicecrc 1
    -pix_fmt {target_pix_fmt} -c:a flac
    {output_file}""".format(**locals())

    # remove multiple spaces
    cmd = (" ").join(cmd.split())

    return cmd


def create_avpvs_segment(seg, pvs, overwrite=False, scale_avpvs_tosource=False):
    """
    Decode the segments of the PVS without audio and write to a raw output file. Using FFV1.
    """
    cmd = ''
    test_config = pvs.test_config

    coding_height = test_config.post_processings[0].coding_height
    coding_width = test_config.post_processings[0].coding_width

    [avpvs_width, avpvs_height] = calculate_avpvs_video_dimensions(
        pvs.src.stream_info['coded_width'], pvs.src.stream_info['coded_height'],
        coding_width, coding_height)

    target_pix_fmt = pvs.get_pix_fmt_for_avpvs()

    input_file = seg.get_segment_file_path()
    output_file = seg.get_tmp_path()

    if overwrite:
        overwrite_spec = "-y"
    else:
        overwrite_spec = "-n"
        if os.path.isfile(output_file):
            logger.warn("output " + output_file + " already exists, will not convert. Use --force to force overwriting.")
            return None

    if scale_avpvs_tosource:
        src_framerate = pvs.src.get_fps()
    else:
        src_framerate = 60.0

    segment_duration = seg.get_segment_duration()

    overlay = "-f lavfi -i nullsrc=s={avpvs_width}x{avpvs_height}:d={segment_duration}:r={src_framerate}".format(**locals())
    complex_filter = "-filter_complex \"[0:v]scale={avpvs_width}:{avpvs_height}:flags=bicubic,fps={src_framerate},setsar=1/1[ol_0];[1:v][ol_0]overlay[vout]\"".format(**locals())

    cmd = """
    ffmpeg -nostdin
    {overwrite_spec}
    -i {input_file}
    {overlay}
    {complex_filter}
    -map "[vout]" -t {segment_duration}
    -c:v ffv1 -threads 4 -level 3 -coder 1 -context 1 -slicecrc 1
    -pix_fmt {target_pix_fmt}
    {output_file}
    """.format(**locals())

    # remove multiple spaces
    cmd = (" ").join(cmd.split())

    return cmd


def create_avpvs_long_concat(pvs, overwrite=False, scale_avpvs_tosource=False):
    """
    Concatenate the decoded segments of the PVS and write to a raw output file together with SRC audio. Using FFV1 and FLAC.
    """
    test_config = pvs.test_config
    target_pix_fmt = pvs.get_pix_fmt_for_avpvs()

    output_file = pvs.get_tmp_wo_audio_path()

    if overwrite:
        overwrite_spec = "-y"
    else:
        overwrite_spec = "-n"
        if os.path.isfile(output_file):
            logger.warn("output " + output_file + " already exists, will not convert. Use --force to force overwriting.")
            return None

    if scale_avpvs_tosource:
        src_framerate = pvs.src.get_fps()
    else:
        src_framerate = 60.0

    number_of_segments = len(pvs.segments)
    total_length_for_concatenation = sum([int(s.get_segment_duration()) for s in pvs.segments])

    audio_src = pvs.src.get_src_file_path()

    # create file list
    tmp_filelist = pvs.get_avpvs_file_list()
    tmp_filelist_h = open(tmp_filelist, 'w+')
    for s in pvs.segments:
        decoded_segment_path = s.get_tmp_path()
        line_to_write = 'file ' + decoded_segment_path + '\n'
        tmp_filelist_h.write(line_to_write)
    tmp_filelist_h.close()

    cmd = """
    ffmpeg -nostdin
    {overwrite_spec}
    -f concat -safe 0
    -i {tmp_filelist}
    -c:v copy -t {total_length_for_concatenation}
    {output_file}""".format(**locals())

    # remove multiple spaces
    cmd = (" ").join(cmd.split())

    return cmd


def simple_encoding(pvs, overwrite, input_file, output_file, vopts, aopts="", filters=""):
    """
    Encode an input file to an output file.

    Arguments:
        pvs {Pvs}
        overwrite {boolean} -- force overwriting
        input_file {str} -- path to input file
        output_file {str} -- path to output file
        vopts {str} -- simple video options, must be at least "-c:v <videocodec>"

    Keyword Arguments:
        aopts {str} -- simple audio options, default: ""
        filters {str} -- filters, default: ""

    Returns:
        str -- the command
    """
    if overwrite:
        overwrite_spec = "-y"
    else:
        overwrite_spec = "-n"
        if os.path.isfile(output_file):
            logger.warn("output " + output_file + " already exists, will not convert. Use --force to force overwriting.")
            return None

    test_config = pvs.test_config

    cmd = """
    ffmpeg -nostdin
    {overwrite_spec}
    -i {input_file} {filters}
    {vopts} {aopts}
    {output_file}""".format(**locals())

    # remove multiple spaces
    cmd = (" ").join(cmd.split())

    return cmd


def create_cpvs(pvs, post_processing, rawvideo=False, overwrite=False, mobile_crf=17, mobile_vprofile="high", mobile_preset="fast"):
    """
    Create the CPVS used for PC or mobile devices,
    for PC with proper pixel format in AVI container,
    for mobile using  H.264, fixed CRF and audio bitrate, optionally with padding, in MP4.
    Will add black bars where it is needed to make the display resolution match the intended device

    Arguments:
        - pvs {Pvs} -- the PVS to process
        - post_processing {PostProcessing} -- post processing specification
        - rawvideo {boolean} -- output raw video instead of lossless codec
        - overwrite {boolean} -- force overwrite
        - mobile_crf {int} -- CRF parameter for mobile encodes (default: 15)
        - mobile_vprofile {str} -- video profile for mobile (default: baseline)
        - mobile_preset {str} -- video preset for mobile (default: baseline)
    """
    test_config = pvs.test_config

    input_file = pvs.get_avpvs_file_path()
    output_file = pvs.get_cpvs_file_path(context=post_processing.processing_type, rawvideo=rawvideo)

    coding_height = post_processing.coding_height
    coding_width = post_processing.coding_width

    [avpvs_width, avpvs_height] = calculate_avpvs_video_dimensions(
        pvs.src.stream_info['coded_width'], pvs.src.stream_info['coded_height'],
        coding_width, coding_height)
    aformat_normalize = ''
    if post_processing.processing_type in ["pc", "tv"]:
        vcodec, target_pix_fmt = pvs.get_vcodec_and_pix_fmt_for_cpvs(rawvideo=rawvideo)
        filters = "-af aresample=48000 -filter:v 'fps=fps={post_processing.display_frame_rate}".format(**locals())

        # videos with smaller height will be padded to full height
        if avpvs_height < post_processing.coding_height:
            filters += "," + "pad=width={post_processing.display_width}:height={post_processing.display_height}:x=(ow-iw)/2:y=(oh-ih)/2".format(**locals()) + "'"
        else:
            filters += "'"

        if test_config.is_short():
            pc_aopts = "-an"
        else:
            total_duration = str(pvs.hrc.get_long_hrc_duration())
            pc_aopts = "-ac 2 -c:a pcm_s16le -t {total_duration}".format(**locals())

        cmd = simple_encoding(
                pvs,
                overwrite,
                input_file,
                output_file,
                "-c:v " + vcodec + " -pix_fmt " + target_pix_fmt,
                pc_aopts,
                filters
            )
    else:
        mobile_vopts = "-c:v libx264 -preset {mobile_preset} -pix_fmt yuv420p -crf {mobile_crf} -profile:v {mobile_vprofile} -movflags faststart".format(**locals())

        filters = "-filter:v 'fps=fps={post_processing.display_frame_rate}".format(**locals())
        if (post_processing.display_height != post_processing.coding_height) or (avpvs_height < post_processing.coding_height):
            # special case for tablet where padding is needed, pad to display height
            pad_filter = "pad=width={post_processing.display_width}:height={post_processing.display_height}:x=(ow-iw)/2:y=(oh-ih)/2".format(**locals())
            filters += ',' + pad_filter + "'"
        else:
            filters += "'"

        if test_config.is_short():
            mobile_aopts = "-an"
        else:
            total_duration = str(pvs.hrc.get_long_hrc_duration())
            aformat_normalize = "-c:a aac -b:a 512k"
            mobile_aopts = "-c:a aac -b:a 512k -t {total_duration}".format(**locals())

        cmd = simple_encoding(
                pvs, 
                overwrite, 
                input_file, 
                output_file, 
                mobile_vopts, 
                mobile_aopts, 
                filters
            )

    # add audio normalization step to -23dBFS RMS
    if test_config.is_long():
        # if simple_encoding returned nothing, nothing to encode
        if cmd is None:
            return

        cpvs_path = os.path.abspath(test_config.get_cpvs_path())
        cmd = " ".join([
            cmd,
            "&&",
            "TMP={cpvs_path}".format(**locals()),
            "ffmpeg-normalize {output_file} -o {output_file} -f -nt rms {aformat_normalize}".format(**locals())
        ])

    return(cmd)


def create_preview(pvs, overwrite=False):
    """
    Create a preview file from the PVS using ProRes and AAC audio.
    """
    input_file = pvs.get_avpvs_file_path()
    output_file = pvs.get_preview_file_path()

    cmd = simple_encoding(pvs, overwrite, input_file, output_file, "-c:v prores", "-c:a aac")

    return(cmd)


def audio_mux(pvs, overwrite=False):
    input_file = pvs.get_tmp_wo_audio_path()
    audio_src = pvs.src.get_src_file_path()

    if pvs.has_buffering():
        output_file = pvs.get_avpvs_wo_buffer_file_path()
    else:
        output_file = pvs.get_avpvs_file_path()

    if overwrite:
        overwrite_spec = "-y"
    else:
        overwrite_spec = "-n"
        if os.path.isfile(output_file):
            logger.warn("output " + output_file + " already exists, will not convert. Use --force to force overwriting.")
            return None

    cmd = """
    ffmpeg -nostdin
    {overwrite_spec}
    -i {input_file}
    -i {audio_src}
    -c:v copy -ac 2 -c:a pcm_s16le -map 0:v -map 1:a
    {output_file}""".format(**locals())

    cmd = (" ").join(cmd.split())

    return(cmd)
