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
Parse the yaml data.

EXAMPLE:

>>> config = TestConfig('P2STR00_sample.yaml')
>>> config
>>> config.segments
>>> config.pvses['P2LTR00_SRC000_HRC000'].hrcs['HRC001'].video_coding
"""

import os
import sys
import yaml
import re
import pprint
import logging
from fractions import Fraction
import lib.ffmpeg as ffmpeg
import lib.cmd_utils as cmd_utils
import pandas as pd

logger = logging.getLogger('main')


class Pvs:
    def __init__(self, pvs_id, test_config, src, hrc):
        self.pvs_id = pvs_id
        self.test_config = test_config
        self.src = src
        self.hrc = hrc

        # compare SRC dimensions and maximum dimensions specified in HRC
        if not self.src.is_youtube:
            max_width, max_height = self.hrc.get_max_res()
            src_width = self.src.stream_info["width"]
            if src_width < max_width:
                logger.error("PVS {self.pvs_id} uses {self.hrc.hrc_id}, which specifies a quality level with maximum width {max_width}. The {src} is only {src_width} wide and would have to be upscaled. Choose a SRC with higher resolution, fix the SRC, or use an HRC with lower maximum resolution.".format(**locals()))
                sys.exit(1)

        # a list of segments this PVS needs
        # will be added later by _create_required_segments()
        self.segments = []

    def is_online(self):
        """
        Whether any of this PVS's segments is online
        """
        return any([s.video_coding.is_online for s in self.segments])

    def get_avpvs_wo_buffer_file_path(self):
        """
        Get the AVPVS file path before stalling added
        """
        return os.path.join(
            self.test_config.get_avpvs_path(),
            self.pvs_id + "_concat_wo_buffer.avi"
        )

    def get_tmp_wo_audio_path(self):
        """
        Get the AVPVS file path after concatenation but before adding audio
        """
        return os.path.join(
            self.test_config.get_avpvs_path(),
            self.pvs_id + "_concat_wo_audio.avi"
        )

    def get_avpvs_file_path(self):
        """
        Get the AVPVS file path after concatenation and possibly stalling added
        """
        return os.path.join(
            self.test_config.get_avpvs_path(),
            self.pvs_id + ".avi"
        )

    def get_avpvs_file_list(self):
        """
        Get the file containing a list of temporary avpvs decoded segments
        """
        return os.path.join(
            self.test_config.get_avpvs_path(),
            self.pvs_id + "_tmp_filelist.txt"
            )

    def get_cpvs_file_path(self, context="pc", rawvideo=False):
        """
        Get the CVPVS file path after context post processing.

        Arguments:
            - context {str} -- one of (pc|mobile|tablet), default: "pc"
            - rawvideo {bool} -- if true, use MKV as output always
        """

        # TODO: possible bug here, no TV-context.

        if context == "pc":
            if rawvideo:
                ext = ".mkv"
            else:
                ext = ".avi"
        else:
            ext = ".mp4"

        cpvs_name = self.pvs_id + "_" + context[0:2].upper() + ext
        if not re.match(self.test_config.REGEX_CPVS_ID, cpvs_name):
            logger.error("CPVS ID " + cpvs_name + " does not correspond to regex!")
            sys.exit(1)

        return os.path.join(self.test_config.get_cpvs_path(), cpvs_name)

    def get_preview_file_path(self):
        """
        Get the preview file path
        """
        return os.path.join(
            self.test_config.get_cpvs_path(),
            self.pvs_id + '_preview.mov'
        )

    def __repr__(self):
        return "<PVS " + self.pvs_id + ">"

    def has_buffering(self):
        return self.hrc.has_buffering()

    def has_stalling(self):
        return self.has_buffering()

    def has_framefreeze(self):
        return self.hrc.has_framefreeze()

    def get_buff_events_media_time(self):
        """
        Return the buff events in the format required for .buff files in media time
        """
        return self.hrc.get_buff_events_media_time()

    def get_buff_events_wallclock_time(self):
        """
        Return the buff events in the format required for .buff files in wallclock time
        """
        return self.hrc.get_buff_events_wallclock_time()

    def get_pix_fmt_for_avpvs(self):
        """
        AVPVS pixel format is simply the unique pixel format of the segments
        """
        target_pix_fmts = set([seg.target_pix_fmt for seg in self.segments])
        if len(target_pix_fmts) > 1:
            logger.error("Segments for PVS " + str(self) + " use different target pixel formats!")
            sys.exit(1)
        return list(target_pix_fmts)[0]

    def get_logfile_path(self):
        return os.path.join(self.test_config.get_logs_path(), self.get_logfile_name())

    def get_logfile_name(self):
        return self.pvs_id + ".log"

    def get_vcodec_and_pix_fmt_for_cpvs(self, rawvideo=False):
        """
        CPVS pixel format depends on the AVPVS pixel format.
        Returns the vcodec and correct pixel format to use for CPVS encoding.

        Arguments:
          - rawvideo {bool} -- if true, always use rawvideo codec, even for 10-bit (otherwise will use v210)
        """
        avpvs_format = self.get_pix_fmt_for_avpvs()

        # TODO: check if this is really the only possible mapping? What about 444?
        format_map_auto = {
            "yuv420p": {
                "pix_fmt": "uyvy422",
                "vcodec": "rawvideo",
            },
            "yuv422p": {
                "pix_fmt": "uyvy422",
                "vcodec": "rawvideo",
            },
            "yuv420p10le": {
                "pix_fmt": "yuv422p10le",
                "vcodec": "v210",
            },
            "yuv422p10le": {
                "pix_fmt": "yuv422p10le",
                "vcodec": "v210"
            }
        }

        if rawvideo:
            target_pix_fmt = avpvs_format
            vcodec = "rawvideo"
        else:
            if avpvs_format not in format_map_auto.keys():
                logger.error("Cannot use input pixel format " + str(avpvs_format) + " for CPVS " + str(self))
            target_pix_fmt = format_map_auto[avpvs_format]["pix_fmt"]
            vcodec = format_map_auto[avpvs_format]["vcodec"]

        return (vcodec, target_pix_fmt)


class Hrc:
    def __init__(self, hrc_id, test_config, hrc_type, video_coding, audio_coding, event_list, segment_duration):
        """
        Arguments:
            hrc_id {string}
            hrc_type {string} -- "normal" or "youtube"
            video_coding {VideoCoding}
            audio_coding {AudioCoding}
            event_list {list} -- list of Event instances
            segment_duration {int} -- duration of a segment in this HRC,
                                      or None in case none was specified,
                                      or "src_duration" in case it should be taken from SRC later
        """
        self.hrc_id = hrc_id
        self.test_config = test_config
        self.hrc_type = hrc_type
        self.video_coding = video_coding
        self.audio_coding = audio_coding
        self.event_list = event_list

        for event in self.event_list:
            # if event.event_type == "stall" or event.event_type == "youtube"
            if event.event_type in ["stall", "freeze", "youtube"]:
                continue

            video_codec = event.quality_level.video_codec
            encoder = self.video_coding.encoder

            if (video_codec == "vp9" and encoder != "libvpx-vp9" and encoder not in self.test_config.ONLINE_CODERS) \
               or (video_codec == "h265" and encoder != "libx265" and encoder not in self.test_config.ONLINE_CODERS) \
               or (video_codec == "h264" and encoder != "libx264" and encoder not in self.test_config.ONLINE_CODERS):
                logger.error("In HRC " + self.hrc_id + ", quality level " + str(event.quality_level) + " and video coding " + str(self.video_coding) + " specify different codecs")
                sys.exit(1)

        # check the event list length for consistency
        # if self.test_config.type == "short":
        #     if len(self.event_list) > 1 or self.event_list[0].event_type == "stall":
        #         logger.error("Exactly one event of type 'quality' is allowed for short tests, please fix HRC " + self.hrc_id)
        #         sys.exit(1)

        # add segment duration, if not, we are in a short test so it does
        # not matter -- in that case, it will be taken from first (and only) event
        if (segment_duration is not None) and (segment_duration != "src_duration"):
            self.segment_duration = int(segment_duration)
        elif segment_duration is None:
            first_event = self.event_list[0]
            if first_event.event_type in ["stall", "freeze"]:
                logger.error("Tried to get segment duration from the first event in HRC " + self.hrc_id + ", but it was a stalling/freezing event. This should not happen in a long test, since you need to specify a default segmentDuration for the entire test.")
                sys.exit(1)
            self.segment_duration = first_event.duration
        elif segment_duration == "src_duration":
            self.segment_duration = segment_duration
        else:
            logger.error("Invalid segment duration: " + str(segment_duration))
            sys.exit(1)

        self.pvses = set()
        self.quality_levels = set()
        # will be added later by _create_required_segments()
        self.segments = set()

        self.buffer_events = []
        if self.has_buffering():
            self.buffer_events = self.get_buff_events_media_time()

    # tests for both buffering and frame freezes
    def has_buffering(self):
        for event in self.event_list:
            if event.event_type in ["stall", "freeze"]:
                return True
        return False

    def has_framefreeze(self):
        for event in self.event_list:
            if event.event_type == "freeze":
                return True
        return False

    def has_stalling(self):
        return self.has_buffering()

    def get_buff_events_media_time(self):
        """
        Return the buff events in the format required for .buff files in wallclock time
        """
        buff_events = []

        if self.has_framefreeze():
            for event in self.event_list:
                if event.event_type == "freeze":
                    buff_events.append(event.duration)
            buff_events = sorted(buff_events)

        elif self.has_buffering():
            total_media_dur = 0
            for event in self.event_list:
                if event.event_type == "stall":
                    stall_dur = event.duration
                    buff_events.append([total_media_dur, stall_dur])
                else:
                    total_media_dur += event.duration

        return buff_events

    def get_long_hrc_duration(self):
        return sum([float(event.duration) for event in self.event_list])

    def get_buff_events_wallclock_time(self):
        """
        Return the buff events in the format required for .buff files in wallclock time
        """
        buff_events = []
        if self.has_buffering():
            total_dur = 0
            for event in self.event_list:
                if event.event_type == "stall":
                    stall_dur = event.duration
                    buff_events.append([total_dur, stall_dur])
                total_dur += event.duration
        return buff_events

    def get_max_res(self):
        """
        Return (width, height) of the maximum resolution used for this HRC's quality levels
        """
        max_width = 0
        max_height = 0

        for event in self.event_list:
            if event.event_type in ["stall", "freeze"]:
                continue
            width = event.quality_level.width
            height = event.quality_level.height
            if width > max_width:
                max_width = width
            if height > max_height:
                max_height = height

        return (max_width, max_height)

    def __repr__(self):
        return "<" + self.hrc_id + ">"


class Segment:
    def __init__(self, index, src, quality_level, video_coding, audio_coding, start_time, duration):
        """
        One segment is an actual video segment belonging to a SRC, encoded with
        a certain quality level. It can be used in multiple PVSes. Its name contains the
        database ID, the SRC, the quality level, and the time range.
        Arguments:
            index {int} -- The index of this segment in the corresponding PVS,
                           starting with 0.
            src {Src}
            quality_level {QualityLevel}
            video_coding {Coding}
            audio_coding {Coding}
            start_time {int}
            duration {int}
        """
        self.index = index
        self.src = src
        self.test_config = src.test_config
        self.quality_level = quality_level
        self.video_coding = video_coding
        self.audio_coding = audio_coding
        self.start_time = start_time
        self.duration = duration
        self.end_time = self.start_time + self.duration

        self.video_frame_info = None
        self.audio_frame_info = None
        self.segment_info = None

        self.filename = self.get_filename()
        self.file_path = os.path.join(self.test_config.get_video_segments_path(), self.filename)
        self.tmp_path = os.path.join(src.test_config.get_avpvs_path(), 'tmp_' + self.filename + '.avi')

        self.target_pix_fmt = None
        self.target_video_bitrate = None

        self.set_pix_fmt()

        if self.quality_level.video_bitrate:
            self.set_target_video_bitrate()

    def uses_10_bit(self):
        """
        Check if a PVS uses 10-bit encoding
        """

        if not self.target_pix_fmt:
            return
        return ("10" in self.target_pix_fmt) and (self.target_pix_fmt != "yuv410p")

    def set_target_video_bitrate(self):
        """
        Set the target bitrate for the Segment based on the encoding complexity of the SRC.
        """
        if self.test_config.is_complex():
            multiple_bitrates = str(self.quality_level.video_bitrate).split('/')
            multiple_bitrates = [float(aa) for aa in multiple_bitrates]
            multiple_bitrates.sort()

            if len(multiple_bitrates) > 1:
                segment_complexity_level = self.test_config.complexity_dict[self.src.get_src_file_name()]
                if segment_complexity_level > 1:
                    self.target_video_bitrate = multiple_bitrates[1]
                else:
                    self.target_video_bitrate = multiple_bitrates[0]
            else:
                # maybe add warning that only a single bitrate is in the yaml?
                self.target_video_bitrate = multiple_bitrates[0]
        else:
            self.target_video_bitrate = self.quality_level.video_bitrate

    def set_pix_fmt(self):
        """
        Various fixes on the set profile depending on the SRC
        and coding settings / codec.

        For now, the profile will be automatically chosen.
        """
        if self.src.is_youtube:
            self.target_pix_fmt = "yuv420p"
            return

        src_pix_fmt = self.src.stream_info["pix_fmt"]

        # 4:4:4 will always be changed to 4:2:2, all others
        # are harmonized to yuv422p or yuv420p.
        if ("444" in src_pix_fmt) or \
           ("422" in src_pix_fmt) or \
           ("rgb" in src_pix_fmt):
            self.target_pix_fmt = "yuv422p"
        elif "420" in src_pix_fmt:
            self.target_pix_fmt = "yuv420p"
        else:
            logger.error("Unknown SRC pixel format: " + str(src_pix_fmt))
            sys.exit(1)

        # 10-Bit handling
        if self.src.uses_10_bit():
            self.target_pix_fmt += "10le"

        if (self.quality_level.video_codec == "h264") and (self.video_coding.encoder.casefold() == "bitmovin"):
            self.target_pix_fmt = "yuv420p"

    def get_filename(self):
        """
        Return the filename of the segment to be generated.
        <db-id>_<src-id>_<quality-level-id>_<seq>_<start-time>-<end-time>.<ext>

        Here, "seq" is the quality index of the segment.
        """
        if self.quality_level.video_codec == "h264" or self.quality_level.video_codec == "h265":
            self.ext = "mp4"
        elif self.video_coding.encoder == "youtube" and self.quality_level.video_codec == "vp9":
            self.ext = "webm"
        elif self.video_coding.encoder.casefold() == "bitmovin" and self.quality_level.video_codec == "vp9":
            self.ext = "mkv"
        elif self.quality_level.video_codec == "vp9":
            self.ext = "mp4"
        else:
            logger.error("Wrong video codec for quality level " + self.quality_level)
            sys.exit(1)

        # Example: P2STR00_SRC000_Q0_98-100.mp4
        # FIXME: file name generated with truncating segment timestamps,
        # will this cause problems?
        return "_".join([
                self.test_config.database_id,
                self.src.src_id,
                self.quality_level.ql_id,
                format(self.index, '04'),
                str(int(self.start_time)) + '-' + str(int(self.end_time))
            ]) + "." + self.ext

    def get_segment_file_path(self):
        """
        Return a path to the encoded segment file.
        """
        return self.file_path

    def get_hash(self):
        """
        Return SHA-1 hash of the encoded video file
        """
        _, ret, _ = cmd_utils.shell_call(["sha1sum", self.file_path], raw=False)
        shasum = ret.split(" ")[0]
        return shasum

    def get_logfile_hash(self):
        """
        Return SHA-1 hash of the logfile
        """
        _, ret, _ = cmd_utils.shell_call(["sha1sum", self.get_logfile_path()], raw=False)
        shasum = ret.split(" ")[0]
        return shasum

    def get_logfile_path(self):
        return os.path.join(self.test_config.get_logs_path(), self.get_logfile_name())

    def get_logfile_name(self):
        return os.path.splitext(self.get_filename())[0] + ".log"

    def get_video_frame_info(self):
        """
        Return a list of dicts with video frame info, in presentation order
        """
        if not self.video_frame_info:
            self.video_frame_info = ffmpeg.get_video_frame_info(self)
        return self.video_frame_info

    def get_audio_frame_info(self):
        """
        Return a list of dicts with audio sample info, in presentation order
        """
        if not self.audio_frame_info:
            self.audio_frame_info = ffmpeg.get_audio_frame_info(self)
        return self.audio_frame_info

    def get_segment_info(self):
        """
        Return a dict with segment info
        """
        if not self.segment_info:
            self.segment_info = ffmpeg.get_segment_info(self)
        return self.segment_info

    def get_segment_duration(self):
        """
        Returns the length of the segment in seconds, as an int
        """
        return self.duration

    def get_tmp_path(self):
        """
        Returns the path to the temporary avpvs segment.
        """
        return self.tmp_path

    def __repr__(self):
        return "<Segment " + format(self.index, '04') + " of " + self.src.src_id + ", " + \
            str(self.start_time) + "-" + str(self.end_time) + \
            ", " + self.quality_level.ql_id + ">"

    def __hash__(self):
        """
        Overwrite internal hash method to make sure that two segments
        are seen as equal when they are from the same SRC, have the same
        audio and video coding, use the same quality level, and have the
        same start time / duration
        """
        return hash((self.src, self.quality_level, self.video_coding, self.audio_coding, self.start_time, self.duration))

    def __lt__(self, other):
        """
        Override sorting method; sort by SRC, start time, QL
        """
        return ((self.src.src_id, self.start_time, self.quality_level.ql_id, self.duration) < (other.src.src_id, other.start_time, other.quality_level.ql_id, self.duration))

    def exists(self):
        return(os.path.isfile(os.path.join(self.test_config.get_video_segments_path(),self.get_filename())))


class Event:
    def __init__(self, event_type, quality_level, duration):
        """
        Event (stalling or quality level playout)

        Arguments:
            event_type {string} -- "quality_level", "stall" or "youtube"
            quality_level {QualityLevel} or {None} (for stall) or {int} for YouTube iTag
            duration {int} -- in seconds, or string "str_duration" to get it from SRC
        """
        self.event_type = event_type
        self.quality_level = quality_level

        self.uses_src_duration = (duration == "src_duration")
        if not self.uses_src_duration:
            if self.event_type == "stall":
                # MMuel edited due to buffering with non-integer length
                self.duration = float(duration)
            elif self.event_type == "freeze":
                self.duration = duration
            else:
                if not float(duration).is_integer():
                    logger.error("All non-stalling events must have an integer duration, but you specified one with " + str(duration))
                    sys.exit(1)
                self.duration = int(duration)
        else:
            self.duration = "src_duration"

    def set_duration(self, duration):
        """
        Later set the duration in seconds (float)
        """
        try:
            self.duration = float(duration)
        except Exception as e:
            logger.error("Tried to set duration of Event " + str(self) + " to " + str(duration))
            exit(1)

    def __repr__(self):
        return "<Event " + self.event_type + ", " + str(self.quality_level) + ", " + str(self.duration) + "s>"


class Src:
    def __init__(self, src_id, test_config, data):
        self.src_id = src_id
        self.test_config = test_config

        # will be added later by _create_required_segments()
        self.pvses = set()
        self.segments = set()

        self.duration = None

        if isinstance(data, str):
            self.filename = data
            self.is_youtube = False
        else:
            self.filename = data['srcFile']
            self.youtube_url = data['youtubeUrl']
            self.is_youtube = True

        self.file_path = os.path.join(test_config.get_src_vid_path(), self.filename)
        self.info_path = os.path.join(test_config.get_src_vid_path(), self.filename+'.yaml')

    def locate_and_get_info(self):
        """
        Locate the SRC file and get the stream info
        """
        self.locate_src_file()
        self.stream_info = ffmpeg.get_src_info(self)

    def uses_10_bit(self):
        """
        Check if a SRC uses 10-bit encoding
        """
        return ("10" in self.stream_info["pix_fmt"]) and (self.stream_info["pix_fmt"] != "yuv410p")

    def get_duration(self):
        """
        Return the duration of the SRC, using the ffmpeg functions
        """
        if not self.duration:
            self.duration = ffmpeg.get_segment_info(self)["video_duration"]
        return self.duration

    def locate_src_file(self):
        """
        Find file_path for the SRC file, if it exists. Otherwise break.
        """
        # look for SRC in joint folder first
        if not os.path.exists(self.file_path):
            self.file_path = os.path.join(self.test_config.get_src_vid_local_path(), self.filename)
            if not os.path.exists(self.file_path):
                logger.error("SRC " + os.path.basename(self.file_path) + " does not exist, neither in " + self.test_config.get_src_vid_local_path() + " nor " + self.test_config.get_src_vid_path() + "!")
                logger.error("Make sure you have all the SRCs in this folder, or set the folder to a different one using the processingchain_defaults.yaml file.")
                sys.exit(1)
            else:
                logger.debug("SRC " + self.filename + " not found in " + self.test_config.get_src_vid_path() + ", " +
                             "falling back to local folder at " + self.test_config.get_src_vid_local_path())

    def get_fps(self):
        """
        Return the SRC FPS as float
        """
        return float(Fraction(self.stream_info["r_frame_rate"]))

    def __repr__(self):
        return "<" + self.src_id + ", File: " + self.filename + ">"

    def get_src_file_path(self):
        """
        Return the path to the PVS' SRC-file
        """
        return(self.file_path)

    def get_src_file_name(self):
        """
        Return the PVS' SRC-filename
        """
        return(self.filename)

    def exists(self):
        return(os.path.isfile(self.file_path))


class Coding:
    def __init__(self, coding_id, test_config, data):
        self.coding_id = coding_id
        self.test_config = test_config
        self.coding_type = data['type']

        self.is_online = None

        if self.coding_type == "video":
            self.encoder = data['encoder']
            self.is_online = True if self.encoder in self.test_config.ONLINE_CODERS else False
            if data['encoder'].casefold() in ['youtube', 'vimeo']:  # or 'vimeo' or 'dailymotion':
                self.protocol = data['protocol']
                return
            elif data['encoder'].casefold() == 'bitmovin':
                self.max_gop = None
                self.min_gop = None
                if 'maxGop' in data:
                    self.max_gop = data['maxGop']
                if 'minGop' in data:
                    self.min_gop = data['minGop']
            else:
                if 'passes' in data.keys():
                    self.passes = int(data['passes'])
                    if self.passes not in [1, 2]:
                        logger.error("only 1-pass or 2-pass encoding allowed, error in coding " + self.coding_id)
                        sys.exit(1)
                else:
                    if 'crf' in data.keys():
                        crf = int(data['crf'])
                        if self.encoder == "libvpx-vp9" and crf not in range(0, 63):
                            logger.error("only crf values between 0 to 63 allowed, error in coding " + self.coding_id)
                            sys.exit(1)
                        elif self.encoder in ["libx264", "libx264"] and crf not in range(0, 51):
                            logger.error("only crf values between 0 to 51 allowed, error in coding " + self.coding_id)
                            sys.exit(1)
                        else:
                            self.crf = crf
                            self.passes = None
                    else:
                        logger.warn("number of passes not specified in coding " + self.coding_id + ", assuming 2")
                        self.passes = 2

            # Optional with defaults
            self.speed = 1
            self.quality = "good"
            self.scenecut = True

            # Optional where encoder chooses defaults or will be set now
            self.iframe_interval = None
            self.bframes = None
            self.preset = None
            self.minrate_factor = None
            self.maxrate_factor = None
            self.bufsize_factor = None
            self.minrate = None
            self.maxrate = None
            self.bufsize = None

            if 'profile' in data:
                logger.warning("Setting profile in " + self.coding_id + " is not supported anymore.")

            if 'pix_fmt' in data:
                logger.warning("Setting pix_fmt in " + self.coding_id + " is not supported.")

            if 'iFrameInterval' in data:
                self.iframe_interval = int(data['iFrameInterval'])
            elif not self.is_online:
                logger.warn("Constant iFrame-Interval not set in coding " + self.coding_id + ", this is not recommended!")

            if 'bframes' in data:
                if self.encoder == "libvpx-vp9":
                    logger.warn("VP9 does not have B-frames, will ignore setting in coding " + self.coding_id)
                else:
                    self.bframes = int(data['bframes'])
                    if self.bframes < 0:
                        logger.error("bframes must be >= 0")
                        sys.exit(1)

            if 'scenecut' in data:
                self.scenecut = bool(data['scenecut'])

            if 'preset' in data:
                self.preset = data['preset']

            if 'speed' in data:
                self.speed = data['speed']
                if self.speed not in [0, 1, 2, 3, 4]:
                    logger.error("speed must be between 0 and 4")
                    sys.exit(1)

            if 'quality' in data:
                self.quality = data['quality']
                if self.quality not in ["good", "best"]:
                    logger.error("quality must be 'good' or 'best'")
                    sys.exit(1)

            if 'minrateFactor' in data:
                self.minrate_factor = float(data['minrateFactor'])

            if 'maxrateFactor' in data:
                self.maxrate_factor = float(data['maxrateFactor'])

            if 'bufsizeFactor' in data:
                self.bufsize_factor = float(data['bufsizeFactor'])

            if 'minrate' in data:
                self.minrate = float(data['minrate'])

            if 'maxrate' in data:
                self.maxrate = float(data['maxrate'])

            if 'bufsize' in data:
                self.bufsize = float(data['bufsize'])

            # enforce that both maxrate and bufsize are specified
            if self.encoder != "libvpx-vp9" and \
               (bool(self.maxrate_factor) ^ bool(self.bufsize_factor)):
                logger.error("if either maxrate or bufsize are set, then both must be specified in coding " + self.coding_id)
                sys.exit(1)

        elif self.coding_type == "audio":
            self.encoder = data['encoder']

        else:
            logger.error("Wrong coding type: " + self.coding_type + ", must be audio or video, error in  coding " + self.coding_id)
            sys.exit(1)

    def __repr__(self):
        return "<Coding " + self.coding_id + ">"


class YoutubeCoding:
    def __init__(self, coding_id, test_config):
        self.coding_id = coding_id
        self.test_config = test_config

    def __repr__(self):
        return "<Coding " + self.coding_id + ">"


class QualityLevel:
    def __init__(self, ql_id, test_config, data):
        self.ql_id = ql_id
        self.test_config = test_config

        self.index = data['index']
        self.video_codec = data['videoCodec']

        self.video_bitrate = None
        if 'videoBitrate' in data:
            self.video_bitrate = data['videoBitrate']

        self.width = int(data['width'])
        self.height = int(data['height'])
        self.fps = data['fps']

        if (self.width % 2 != 0) or (self.height % 2 != 0):
            logger.error("width and height in QualityLevel " + self.ql_id + " must be divisible by 2")
            sys.exit(1)

        if 'audioCodec' in data:
            self.audio_codec = data['audioCodec']
            self.audio_bitrate = data['audioBitrate']

        self.hrcs = set()

    def __repr__(self):
        return "<QualityLevel " + self.ql_id + ", Index " + str(self.index) + ">"


class PostProcessing:
    def __init__(self, test_config, data):
        self.test_config = test_config
        self.processing_type = data['type']

        if self.processing_type not in ["pc", "tablet", "mobile"]:
            logger.error("Wrong post processing type " + self.processing_type + ", must be pc/tablet/mobile")
            sys.exit(1)

        try:
            self.display_width = int(data['displayWidth'])
            self.display_height = int(data['displayHeight'])
            self.coding_width = int(data['codingWidth'])
            self.coding_height = int(data['codingHeight'])
        except Exception as e:
            logger.error("Missing or wrong data in post processing: " + str(e.message))
            sys.exit(1)

        if self.display_width != self.coding_width:
            logger.error("Post processing must have same coding and display width!")
            sys.exit(1)

        if self.processing_type == "pc" and \
           ((self.display_height != self.coding_height) or (self.display_width != self.coding_width)):
            logger.error("PC post processing must have same coding and display width/height!")
            sys.exit(1)

    def __repr__(self):
        return "<PostProcessing " + self.processing_type.upper() + ">"


class TestConfig:
    """
    Class representing a test configuration.

    You have access to the following data (see individual class definitions for more):

    Attributes:
    - data
    - database_id
    - type
    - default_segment_duration

    Dictionaries:
    - quality_levels
        - hrcs
    - codings
    - srcs
        - segments
    - hrcs
        - segments
        - quality levels
        - event list
    - pvses

    Lists:
    - post_processings
    - segments (all required segments for this test)
    """

    # regular expressions for checking IDs
    REGEX_DATABASE_ID = r'P2(S|L)(TR|PT|IT|VL|XM)[\d]{2,3}'
    REGEX_QL_ID = r'Q[\d]+'
    REGEX_CODING_ID = r'(A|V)C[\d]+'
    REGEX_SRC_ID = r'SRC[\d]{3,5}'
    REGEX_HRC_ID = r'HRC[\d]{3,4}'
    REGEX_PVS_ID = r'P2(S|L)(TR|PT|IT|VL|XM)[\d]{2,3}_SRC[\d]{3,5}_HRC[\d]{3,4}'
    REGEX_CPVS_ID = r'P2(S|L)(TR|PT|IT|VL|XM)[\d]{2,3}_SRC[\d]{3,5}_HRC[\d]{3,4}_(PC|MO|TA)'

    # required minimum version of YAML file syntax
    REQUIRED_YAML_SYNTAX_VERSION = 6

    ONLINE_CODERS = ['youtube', 'bitmovin', 'vimeo']

    def __init__(self, yaml_filename, filter_srcs=None, filter_hrcs=None, filter_pvses=None):
        """
        Load the YAML file and create test config.
        Arguments:
            - yaml_filename {str} -- path to YAML file
            - filter_srcs {str} -- filter string for SRC
            - filter_hrcs {str} -- filter string for HRC
            - filter_pvses {str} -- filter string for PVSES
        """
        self.yaml_file = yaml_filename

        if filter_srcs:
            self.filter_srcs = filter_srcs.split("|")
        else:
            self.filter_srcs = []
        if filter_hrcs:
            self.filter_hrcs = filter_hrcs.split("|")
        else:
            self.filter_hrcs = []
        if filter_pvses:
            self.filter_pvses = filter_pvses.split("|")
        else:
            self.filter_pvses = []

        self.database_dir = os.path.dirname(self.yaml_file)
        self.complex_bitrates = False

        self._check_names()

        with open(self.yaml_file) as f_in:
            self.data = yaml.load(f_in, Loader=yaml.FullLoader)

        self._load_paths()
        self._parse_data_from_yaml()
        if self.complex_bitrates:
            self._parse_complexity()
        self._create_required_segments()

    def _check_names(self):
        """
        Check if the name of the YAML file is correct, also if the name of the database folder
        is the same as the YAML file.
        """

        if not os.path.exists(self.yaml_file):
            logger.error("YAML file " + self.yaml_file + " does not exist")
            sys.exit(1)

        # check for YAML DB ID
        self.yaml_basename = os.path.splitext(os.path.basename(self.yaml_file))[0]
        if not re.match(self.REGEX_DATABASE_ID, self.yaml_basename):
            logger.error("YAML filename does not have correct ID syntax: " + self.REGEX_DATABASE_ID)
            sys.exit(1)

        # check for name equivalence
        self.db_dirname = os.path.basename(os.path.dirname(self.yaml_file))
        if ("P2STR00" not in self.yaml_basename) and ("P2LTR00" not in self.yaml_basename) and \
           self.yaml_basename != self.db_dirname:
            logger.error("Database folder must have the same name as YAML config file. Rename your database folder to '" + self.yaml_basename + "'")
            sys.exit(1)

        if os.path.isfile(os.path.join(os.path.dirname(__file__), '..', 'util', 'complexityAnalysis', 'complexity_classification.csv')):
            self.complex_bitrates = True

    def _load_paths(self):
        """
        Load the overriden paths from processingchain_defaults.yaml, if it exists,
        otherwise, set the paths to the local output folders
        """

        self.path_mapping = {
            'srcVid': os.path.abspath(os.path.join(self.database_dir, '../srcVid')),
            'srcVidLocal': os.path.join(self.database_dir, 'srcVid'),
            'avpvs': os.path.join(self.database_dir, 'avpvs'),
            'cpvs': os.path.join(self.database_dir, 'cpvs'),
            'videoSegments': os.path.join(self.database_dir, 'videoSegments'),
            'buffEventFiles': os.path.join(self.database_dir, 'buffEventFiles'),
            'qualityChangeEventFiles': os.path.join(self.database_dir, 'qualityChangeEventFiles'),
            'audioFrameInformation': os.path.join(self.database_dir, 'audioFrameInformation'),
            'videoFrameInformation': os.path.join(self.database_dir, 'videoFrameInformation'),
            'sideInformation': os.path.join(self.database_dir, 'sideInformation'),
            'logs': os.path.join(self.database_dir, 'logs'),
        }

        # Removing relative paths for avpvs-path due to some problems in the ffmpeg.py create_avpvs_long_concat()-function
        from pathlib import Path
        if ".." in self.path_mapping['avpvs']:
            cwd = Path.cwd()
            self.path_mapping['avpvs'] = str((cwd / self.path_mapping['avpvs']).resolve())

        # check SRC folder(special treatment)
        if not os.path.isdir(self.path_mapping["srcVid"]):
            logger.warning("Tried to find joint 'srcVid' folder at " +
                           os.path.abspath(self.path_mapping["srcVid"]) + " but it does not exist. " +
                           "Falling back to the 'srcVid' folder inside " + self.database_dir)
            self.path_mapping["srcVid"] = os.path.join(self.database_dir, "srcVid")

        # load paths from override file
        override_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'processingchain_defaults.yaml')
        if os.path.isfile(override_file):
            # load YAML file
            with open(override_file) as f:
                overrides = yaml.load(f, Loader=yaml.FullLoader)
            # set overrides if dir exists
            if overrides:
                for key, path in overrides.items():
                    # only override valid keys
                    if key in self.path_mapping.keys():
                        if not os.path.isdir(path):
                            logger.error("path " + path + ", as specified in processingchain_defaults.yaml, does not exist in the virtual machine! Please create it first.")
                            sys.exit(1)
                        if not os.access(path, os.W_OK):
                            logger.error("path " + path + ", as specified in processingchain_defaults.yaml, does not have write permissions for current user!")
                            sys.exit(1)
                        self.path_mapping[key] = path
                    else:
                        logger.warn(key + " is not a valid path identifier, ignoring")

        for key, path in self.path_mapping.items():
            if not os.path.isdir(path):
                logger.warn("path " + path + " does not exist; creating empty folder")
                os.makedirs(path)

        logger.debug(pprint.pformat(self.path_mapping))

    def _create_required_segments(self):
        """
        Creates the Segment instances required for this TestConfig
        """
        self.segments = set()

        for pvs_id, pvs in self.pvses.items():
            # get the SRC length so we can make sure that we don't exceed it with the last segment
            if not pvs.src.is_youtube:
                if pvs.hrc.event_list[0].duration != "src_duration":
                    src_length = float(pvs.src.get_duration())
                    total_event_duration = sum(event.duration for event in pvs.hrc.event_list if event.event_type == "quality_level")
                    if src_length < total_event_duration:
                        logger.warning("{pvs.src} has a length of only {src_length}, but events in {pvs} sum up to {total_event_duration}. Last event(s) will be cut.".format(**locals()))
                    elif src_length > total_event_duration:
                        logger.warning("{pvs.src} is longer than the events specified in {pvs}; trimming will occur.".format(**locals()))
                else:
                    logger.debug("Skipping calculation of event duration for " + str(pvs) + ", since it's set to SRC duration")
            else:
                logger.warning("Cannot check duration of YouTube videos yet, make sure your events in " + str(pvs) + " sum up to the right duration.")

            current_timestamp = 0
            segment_index = 0

            # go through all events for this HRC
            for event in pvs.hrc.event_list:
                # only handle non-YouTube and non-stall
                if event.event_type == "quality_level":
                    # special case where event duration is "src_duration"
                    if event.duration == "src_duration":
                        number_of_segments = 1
                    else:
                        # check that the event is divisible by segment duration
                        if (event.duration % pvs.hrc.segment_duration != 0):
                            logger.error("event duration " + str(event.duration) +
                                         " does not match with segment duration of " + str(pvs.hrc.segment_duration) +
                                         ", please fix this event in " + pvs.hrc.hrc_id)
                            sys.exit(1)

                        # check how many segments we need and create them
                        number_of_segments = event.duration / pvs.hrc.segment_duration

                    if self.type == "short" and number_of_segments > 1:
                        logger.error("Short databases only allow one segment, HRC " + str(pvs.hrc) + " does not comply.")
                        sys.exit(1)

                    # create the individual segments
                    for i in range(int(number_of_segments)):

                        # normal case
                        if pvs.hrc.segment_duration != "src_duration":
                            # normally, the segment length is the default segment length
                            required_segment_duration = pvs.hrc.segment_duration

                            # ... unless we would exceed the end of the SRC, in which case
                            # we have to cut the segment.
                            if not pvs.src.is_youtube:
                                if current_timestamp + required_segment_duration > src_length:
                                    required_segment_duration = src_length - current_timestamp
                        # segment duration should be the (only) event duration == SRC duration
                        else:
                            # required_segment_duration = event.duration
                            logger.debug("Setting segment duration in PVS " + str(pvs) + " to SRC duration")
                            required_segment_duration = pvs.src.get_duration()

                        if required_segment_duration <= 0:
                            logger.warning("Got a segment with duration less or equal 0 in PVS {}, skipping".format(pvs))
                            continue

                        segment = Segment(
                            index=segment_index,
                            src=pvs.src,
                            quality_level=event.quality_level,
                            video_coding=pvs.hrc.video_coding,
                            audio_coding=pvs.hrc.audio_coding,
                            start_time=current_timestamp,
                            duration=required_segment_duration
                        )
                        current_timestamp += required_segment_duration
                        segment_index += 1
                        logger.debug("adding segment " + str(segment))

                        # add the references to this segment to various containers
                        pvs.segments.append(segment)
                        pvs.src.segments.add(segment)
                        pvs.hrc.segments.add(segment)
                        self.segments.add(segment)

    def _parse_complexity(self):
        df_c = pd.read_csv(os.path.join(os.path.dirname(__file__), '..', 'util', 'complexityAnalysis', 'complexity_classification.csv'), sep=",")

        df_c_val = pd.read_csv(os.path.join(os.path.dirname(__file__), '..', 'util', 'complexityAnalysis', 'complexity_classification_validation.csv'), sep=",")

        complexity_dict = {**pd.Series(df_c.complexity_class.values, index=df_c.file).to_dict(), **pd.Series(df_c_val.complexity_class.values, index=df_c_val.file).to_dict()}

        self.complexity_dict = complexity_dict

    def _parse_data_from_yaml(self):
        """
        Parse fields and create classes from YAML source
        """
        self.database_id = self.data['databaseId']

        # check YAML syntax version
        if 'syntaxVersion' in self.data.keys():
            if self.data['syntaxVersion'] < self.REQUIRED_YAML_SYNTAX_VERSION:
                logger.error("Your YAML file syntax may be outdated, as the syntax has changed in the meantime. Please check if your YAML file is compatible with the syntax given in https://gitlab.com/pnats2avhd/processing-chain/wikis/home and change the 'syntaxVersion' number to " + str(self.REQUIRED_YAML_SYNTAX_VERSION))
                sys.exit(1)
        else:
            logger.warn("YAML file does not specify the 'syntaxVersion', things might break!")

        if not re.match(self.REGEX_DATABASE_ID, self.database_id):
            logger.error("Database ID " + self.database_id + " does not have correct ID syntax: " + self.REGEX_DATABASE_ID)
            sys.exit(1)
        if self.yaml_basename != self.database_id:
            logger.error("Database ID and YAML filename do not match")
            sys.exit(1)

        self.type = self.data['type']

        if self.type not in ["short", "long"]:
            logger.error("Database type must be 'short' or 'long'")
            sys.exit(1)

        # parse default segment duration, if any
        if 'segmentDuration' in self.data.keys():
            self.default_segment_duration = self.data['segmentDuration']
        else:
            # if none exists for long tests, this is an error
            if self.type == 'long':
                logger.error("A default segment duration must be defined for long tests using the 'segmentDuration' key. You can override this in every HRC.")
                sys.exit(1)
            # else, for short tests, there doesn't have to be default
            self.default_segment_duration = None

        self.quality_levels = {}
        self.codings = {}
        self.srcs = {}
        self.hrcs = {}
        self.pvses = {}
        self.urls = {}

        self.post_processings = []

        for ql_id, data in self.data['qualityLevelList'].items():
            if not re.match(self.REGEX_QL_ID, ql_id):
                logger.error("Quality Level ID " + ql_id + " does not have correct syntax: " + self.REGEX_QL_ID)
                sys.exit(1)
            ql = QualityLevel(ql_id, self, data)
            self.quality_levels[ql_id] = ql

        for coding_id, data in self.data['codingList'].items():
            if not re.match(self.REGEX_CODING_ID, coding_id):
                logger.error("Coding ID " + coding_id + " does not have correct syntax: " + self.REGEX_CODING_ID)
                sys.exit(1)
            self.codings[coding_id] = Coding(coding_id, self, data)
            self.codings['youtube'] = YoutubeCoding('youtube', self)  # dummy coding

        for src_id, data in self.data['srcList'].items():
            if not re.match(self.REGEX_SRC_ID, src_id):
                logger.error("SRC ID " + src_id + " does not have correct syntax: " + self.REGEX_SRC_ID)
                sys.exit(1)

            if self.filter_srcs and src_id not in self.filter_srcs:
                # skip this source
                logger.info("skipping SRC " + src_id)
                continue

            src = Src(src_id, self, data)
            self.srcs[src_id] = src

        for hrc_id, data in self.data['hrcList'].items():
            if not re.match(self.REGEX_HRC_ID, hrc_id):
                logger.error("HRC ID " + hrc_id + " does not have correct syntax: " + self.REGEX_HRC_ID)
                sys.exit(1)

            if self.filter_hrcs and hrc_id not in self.filter_hrcs:
                # skip this HRC
                logger.info("skipping HRC " + hrc_id)
                continue

            video_coding = self.codings[data['videoCodingId']]
            if self.type == "long":
                audio_coding = self.codings[data['audioCodingId']]
            else:
                audio_coding = None
            quality_level_list = []  # list of quality levels this HRC uses
            event_list = []  # list of events for this HRC

            # allow overriding segment duration per HRC
            if 'segmentDuration' in data.keys():
                if 'src_duration' in [e[1] for e in data['eventList']]:
                    logger.error("You cannot specify both segmentDuration and src_duration as event length in HRC " + hrc_id + "!")
                    sys.exit(1)
                hrc_segment_duration = data['segmentDuration']
            else:
                # if not, it could still be "None" ...
                hrc_segment_duration = self.default_segment_duration

            # go through all events and gather quality levels and durations
            for event_data in data['eventList']:
                if len(event_data) != 2:
                    logger.error("Event data must consist of two elements: " + str(event_data))
                    sys.exit(1)

                # Either the event list is based on YouTube
                if 'youtube' in data['videoCodingId']:
                    event_type = 'youtube'
                    quality_level = event_data[0]  # = YouTube itag
                    hrc_type = 'youtube'
                # or a normal quality level
                else:
                    hrc_type = 'normal'
                    if 'Q' in event_data[0]:
                        event_type = 'quality_level'
                        quality_level = self.quality_levels[event_data[0]]
                    elif 'stall' in event_data[0]:
                        event_type = 'stall'
                        quality_level = None
                    elif 'freeze' in event_data[0]:
                        event_type = 'freeze'
                        quality_level = None
                    else:
                        logger.error("Wrong event type: " + str(event_data[0]) + ", must be quality level ID or 'stall'")
                        sys.exit(1)

                # event duration can be either a number or "src_duration"
                event_duration = event_data[1]
                if event_duration == "src_duration":
                    hrc_segment_duration = "src_duration"
                event = Event(event_type, quality_level, event_duration)
                event_list.append(event)
                quality_level_list.append(quality_level)

            hrc = Hrc(hrc_id, self, hrc_type, video_coding, audio_coding, event_list, hrc_segment_duration)

            # re-associate HRC with the created events
            for e in event_list:
                e.hrc = hrc

            # re-associate the quality levels with the HRC and vice-versa
            for q in set(quality_level_list):
                hrc.quality_levels.add(q)
            for q in set([q for q in quality_level_list if isinstance(q, QualityLevel)]):
                q.hrcs.add(hrc)

            self.hrcs[hrc_id] = hrc

        for pvs_id in self.data['pvsList']:
            if not re.match(self.REGEX_PVS_ID, pvs_id):
                logger.error("PVS ID " + pvs_id + " does not have correct syntax: " + self.REGEX_PVS_ID)
                sys.exit(1)

            if self.filter_pvses and pvs_id not in self.filter_pvses:
                # skip this PVS
                logger.info("skipping PVS " + pvs_id)
                continue

            src_id = re.findall(r'SRC\d+', pvs_id)[0]
            hrc_id = re.findall(r'HRC\d+', pvs_id)[0]

            skip_pvs = False
            if self.filter_srcs and src_id not in self.filter_srcs:
                skip_pvs = True

            if self.filter_hrcs and hrc_id not in self.filter_hrcs:
                skip_pvs = True

            if skip_pvs:
                logger.info("skipping PVS " + pvs_id + " because it includes a skipped SRC/HRC")
                continue

            # assign PVS with SRC and HRC
            if src_id not in self.srcs.keys():
                logger.error("PVS " + pvs_id + " specifies SRC " + src_id + " but it is not defined in the srcList")
                sys.exit(1)
            if hrc_id not in self.hrcs.keys():
                logger.error("PVS " + pvs_id + " specifies HRC " + hrc_id + " but it is not defined in the hrcList")
                sys.exit(1)
            src = self.srcs[src_id]
            hrc = self.hrcs[hrc_id]

            # get SRC info for PVS
            src.locate_and_get_info()

            pvs = Pvs(pvs_id, self, src, hrc)

            self.pvses[pvs_id] = pvs
            src.pvses.add(pvs)
            hrc.pvses.add(pvs)

        for data in self.data['postProcessingList']:
            post_processing = PostProcessing(self, data)
            self.post_processings.append(post_processing)
            if len(self.post_processings) > 1:
                logger.warning("More than one post processing is not really supported!")

    def __repr__(self):
        return self.data.__repr__()

    def is_complex(self):
        return self.complex_bitrates

    def is_short(self):
        return self.data['type'] == 'short'

    def is_long(self):
        return self.data['type'] == 'long'

    def get_bitrate(self, hrc):
        """
        Return the bitrate per chunk as a list.
        """
        q_level = [e[0] for e in self.data['hrcList'][hrc]['eventList']]
        if self.complex_bitrates:
            lo_bitrates = [self.data['qualityLevelList'][q]['videoBitrate'].split('/')[0] for q in q_level]
            # hi_bitrates = [self.data['qualityLevelList'][q]['videoBitrate'].split('/')[0] for q in q_level]
            bitr = lo_bitrates
        else:
            bitr = [self.data['qualityLevelList'][q]['videoBitrate'] for q in q_level]
        return bitr

    def get_height(self, hrc):
        """
        Return the height for all events in HRC.
        """
        q_level = [e[0] for e in self.data['hrcList'][hrc]['eventList']]
        height = [self.data['qualityLevelList'][q]['height'] for q in q_level]

        return height

    def get_pvs_ids(self):
        return self.pvses.keys()

    def get_required_segments(self):
        """
        Returns a set of all the segments needed to be produced for this test
        """
        return self.segments

    def get_src_vid_path(self):
        """
        Return the path to srcVid folder
        """
        return self.path_mapping["srcVid"]

    def get_src_vid_local_path(self):
        """
        Return the path to srcVid folder
        """
        return self.path_mapping["srcVidLocal"]

    def get_avpvs_path(self):
        """
        Return the path to avpvs folder
        """
        return self.path_mapping["avpvs"]

    def get_cpvs_path(self):
        """
        Return the path to cpvs folder
        """
        return self.path_mapping["cpvs"]

    def get_video_segments_path(self):
        """
        Return the path to videoSegments folder
        """
        return self.path_mapping["videoSegments"]

    def get_buff_event_files_path(self):
        """
        Return the path to buffEventFiles folder
        """
        return self.path_mapping["buffEventFiles"]

    def get_quality_change_event_files_path(self):
        """
        Return the path to qualityChangeEventFiles folder
        """
        return self.path_mapping["qualityChangeEventFiles"]

    def get_audio_frame_information_path(self):
        """
        Return the path to audioFrameInformation folder
        """
        return self.path_mapping["audioFrameInformation"]

    def get_video_frame_information_path(self):
        """
        Return the path to videoFrameInformation folder
        """
        return self.path_mapping["videoFrameInformation"]

    def get_side_information_path(self):
        """
        Return the path to sideInformation folder
        """
        return self.path_mapping["sideInformation"]

    def get_logs_path(self):
        """
        Return the path to logs folder
        """
        return self.path_mapping["logs"]
