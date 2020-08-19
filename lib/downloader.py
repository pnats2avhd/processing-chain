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

import logging
import os
import re
import sys
from stat import S_ISDIR
import bitmovin
import paramiko
import yaml
import youtube_dl
import lib.cmd_utils as cmd_utils
import lib.ffmpeg as ffmpeg

logger = logging.getLogger('main')


class OnlineVideo:
    """
    Simple wrapper class to segment
    """
    def __init__(self, path):
        self.file_path = path
        self.filename = 'random'

    def __repr__(self):
        return "<OnlineVideo " + self.file_path + ">"


class Downloader:
    """
    Online service video downloader
    """

    def __init__(self, folder, bitmovin_key_file=None, output_details=None, input_details=None, overwrite=False):
        """
        Initialize video downloader.

        Arguments:
        - folder: path to stored video segments
        - bitmovin_key_file: path to a file containing your Bitmovin API-key
        - output_details: path to a file containing your output preferences (SFTP only)
        - input_details: path to a file containing your input preferences (SFTP of HTTPS)
        - overwrite: If you want to overwrite existing files, set this to 'True'. Default: False
        """
        self.video_segments_folder = folder
        self.overwrite = overwrite
        self.bitmovin_initialized = False

        # only check for output/input server details if a bitmovin key is given, because only then they will be used
        if os.path.isfile(output_details) and \
                os.path.isfile(input_details) and \
                os.path.isfile(bitmovin_key_file):

            with open(bitmovin_key_file) as key_file:
                self.bitmovinkey = key_file.readline()

            # read in input and output preferences file
            with open(input_details, 'r') as input_details_f:
                self.input_details = yaml.load(input_details_f, Loader=yaml.FullLoader)
            with open(output_details, 'r') as output_details_f:
                self.output_details = yaml.load(output_details_f, Loader=yaml.FullLoader)

            # check if input is sftp or https
            if self.input_details["input_type"] not in ["sftp", "http", "https"]:
                logger.error("No suitable input for bitmovin found, must be either 'sftp' or 'https'!")
                sys.exit(1)

            if self.output_details["output_type"] not in ["sftp", "azure"]:
                logger.error("No suitable output for bitmovin found, must be either 'sftp' or 'azure'!")
                sys.exit(1)

            self.bitmovin_initialized = True

    @staticmethod
    def fix_codec(vcodec):
        """
        Fix the video codec name for YouTube-DL
        """
        if re.match(".*h264.*", vcodec):
            vcodec = 'avc'
        if re.match(".*vp9.*", vcodec):
            vcodec = 'vp9'
        return vcodec

    @staticmethod
    def check_mode(url):
        """
        Check the platform for the URL and return it
        """
        if re.match('.*youtube\\..*', url) or re.match('.*youtu.be.*', url):
            mode = 'youtube'
        elif re.match('.*vimeo\\..*', url):
            # FIXME: currently not working properly, too, unfortunately. The video formats are not found consistently.
            mode = 'vimeo'
        elif re.match('.*dailymotion\\..*', url):
            logger.warning('Using Dailymotion, mostly not working properly if ffmpeg is not compiled with -openssl')
        else:
            mode = 'else'
            logger.warning("Unsupported download platform! Trying to download but no guarantees.")
        return mode

    @staticmethod
    def check_video_len(dl_file):
        if os.path.exists(dl_file):
            seg = OnlineVideo(dl_file)
            info = ffmpeg.get_segment_info(seg)
            if info is None:
                logger.warning("Duration of " + dl_file + " could not be calculated.")
            if not (7 < int(info['video_duration']) < 9):
                logger.warning("Video " + dl_file + " is not within 7-9 seconds length!")

    @staticmethod
    def get_formats(url, verbose=False):
        ydl_opts_list_formats = {
            'listformats': True
        }
        ydl_opts_list_formats['quiet'] = False if verbose else True
        ydl_opts_extract_info = {
            'quiet': True
        }
        try:
            if verbose:
                logger.debug("These are the available formats:")
                with youtube_dl.YoutubeDL(ydl_opts_list_formats) as ydl:
                    ydl.download([url])

            with youtube_dl.YoutubeDL(ydl_opts_extract_info) as ydl:
                formats = ydl.extract_info(url, download=False)
        except:
            formats = None

        if not formats:
            logger.error("No formats for URL " + str(url) + " found!")
            sys.exit(1)
        return formats

    def download_video(self, url, width, height, filename, vcodec, bitrate, protocol, fps, force_overwriting=False, verbose=False):
        """
        Arguments:
            - url: url of the video. Supported are: youtube, vimeo and dailymotion
            - width: width of the downloaded video
            - height: height of the downloaded video
            - filename: name of the output file without file extension
            - vcodec: vcodec of the video to download
            - bitrate: only download a video if it has a bitrate below the specified one
            - protocol: Streaming protocol (DASH, HLS, MPD, M3U8)
            - fps: framerate of the downloaded video
            - force_overwriting: if you want to overwrite existing videos (default: False)
            - verbose: logger.debug verbose messages (default: False)
        """
        # fix case in protocol
        if protocol not in ["dash", "hls", "mpd", "m3u8", None]:
            logger.error("Only DASH, HLS, MPD, M3U8 allowed as protocols")
            sys.exit(1)

        width = int(width)
        height = int(height)
        bitrate = int(bitrate)

        # check video codec and mode
        vcodec = self.fix_codec(vcodec)
        mode = self.check_mode(url)

        # some sanity checks
        if mode == "vimeo":
            if vcodec not in ["avc", "h264"]:
                logger.warning("Vimeo only supports h264/avc as vcodec.")
        if mode == 'youtube':
            get_ext_format = "bestvideo"
        else:
            get_ext_format = "best"

        # define the different options for the youtube-dl
        info_opts = {
            'quiet': True,
            'format': get_ext_format + '[vcodec *= ' + vcodec + ']',
            'no-continue': True,
        }

        # in order to see if the file is already downloaded, get the right extension and check
        try:
            with youtube_dl.YoutubeDL(info_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                dl_file = os.path.join(self.video_segments_folder, filename + '.' + info['ext'])

            if force_overwriting:
                for f in os.listdir(self.video_segments_folder):
                    if re.search(filename + '.' + info['ext'] + '.*', f):
                        os.remove(os.path.join(self.video_segments_folder, f))

            if os.path.exists(dl_file) and not force_overwriting:
                logger.warning("File " + dl_file + " exists; if you want to overwrite existing files, use '-f'.")
                return
        except:
            if force_overwriting:
                logger.error("File might not be overwritten!")

        # initialize it with a reasonable high value
        resolution_delta = int(width)*int(width) + int(height)*int(height)
        resolution_delta_false = resolution_delta

        format_nr = None
        chosen_width = None
        chosen_height = None
        chosen_rate = None
        right_protocol = False
        format_fps = 0

        for format_entry in self.get_formats(url, verbose)['formats']:
            # omit audio only streams
            if(re.match('.*audio only.*', format_entry['format'])):
                continue
            if protocol:
                if 'm3u8' in format_entry['protocol'].casefold() or 'hls' in format_entry['protocol'].casefold():
                    if 'm3u8' in protocol or 'hls' in protocol:
                        right_protocol = True
                        pass
                    elif right_protocol is True:
                        continue

                elif 'dash' in format_entry['protocol'].casefold() or 'mpd' in format_entry['protocol'].casefold():
                    if 'dash' in protocol or 'mpd' in protocol:
                        right_protocol = True
                        pass
                    elif right_protocol is True:
                        continue
                else:
                    right_protocol = True

            # continue if the vcodec is not right
            if "vcodec" in format_entry.keys() and vcodec not in format_entry['vcodec']:
                continue

            # first check video bitrate, if this field is not available check total bitrate
            if "vbr" in format_entry.keys():
                current_rate = format_entry['vbr']
            elif "tbr" in format_entry.keys():
                current_rate = format_entry['tbr']
            else:
                continue

            if int(bitrate) < int(current_rate):
                continue
            # check if the found video stream is closer to the specified resolution than the video stream found
            # before
            new_resolution_delta = abs(int(height) - format_entry['height'])
            if right_protocol is True and new_resolution_delta <= resolution_delta or\
               right_protocol is False and new_resolution_delta <= resolution_delta_false:

                current_fps = format_entry['fps']
                if new_resolution_delta == resolution_delta or new_resolution_delta == resolution_delta_false:
                    if fps.casefold() == 'original' or fps.casefold() == 'auto':
                        if current_fps < format_fps:
                            continue
                    elif current_fps > int(fps) and format_fps == 0:
                        pass
                    elif abs(current_fps - int(fps)) < abs(format_fps - int(fps)):
                        pass
                    else:
                        continue

                if right_protocol is True:
                    resolution_delta = new_resolution_delta
                else:
                    resolution_delta_false = new_resolution_delta

                # if we arrive here, we have a format
                format_nr = format_entry['format_id']
                chosen_width = format_entry['width']
                chosen_height = format_entry['height']
                # chosen_rate = current_rate
                format_fps = current_fps

        # if format_nr is None, no matching video stream was found
        if not format_nr:
            if bitrate is None:
                logger.error('bitrate ' + str(bitrate) + ' is not available!')
            elif vcodec is None:
                logger.error('Vcodec ' + vcodec + ' is not available! Please choose another one.')
            else:
                if fps == 'original':
                    logger.error(
                        'Combination of vcodec ' + vcodec + ' and bitrate ' + str(bitrate) + ' is not available! Please choose another one.')
                else:
                    logger.error(
                        'Combination of vcodec ' + vcodec + ' and bitrate ' + str(bitrate) + ' at ' + str(fps) + ' fps is not available! Please choose another one.')
            return

        # if format_nr is set, you can download the video.
        ydl_opts = {
            'format': format_nr,
            'outtmpl': os.path.join(self.video_segments_folder, filename + '.%(ext)s'),
            'quiet': True,
            'logger': logger,
            'verbose': False,
            'prefer_insecure': True,
            'fixup': 'never',
            'no-continue': True,
        }
        if verbose:
            ydl_opts['quiet'] = False
            ydl_opts['verbose'] = True

        # display the new resolution for information
        with youtube_dl.YoutubeDL(ydl_opts) as ydl:
            try:
                ydl.download([url])
            except:
                logger.error("Downloading video " + filename + " failed!")
                sys.exit(1)

        self.check_video_len(dl_file)

        if width != chosen_width or height != chosen_height:
            if fps == 'original' or fps == 'auto':
                logger.warning("The available resolution for bitrate " + str(bitrate) + ' is ' + str(chosen_width) + 'x'
                               + str(chosen_height) + "@" + str(format_fps) + "fps for file " + filename +
                               ". (originally specified resolution: " + str(width) + "x" + str(height) + ")")
            else:
                logger.warning("The available resolution for bitrate " + str(bitrate) + ' is ' + str(chosen_width) + 'x'
                               + str(chosen_height) + "@" + str(format_fps) + "fps for file " + filename +
                               ". (originally specified resolution: " + str(width) + "x" + str(height) + ", fps: " + str(fps) + ")")
        else:
            if fps == 'original' or fps == 'auto':
                logger.info("The framerate of downloaded video " + filename + " is " + str(format_fps) + ".")
            elif int(fps) != format_fps:
                logger.warning("The framerate of downloaded video " + filename + " is " + str(format_fps) + "." +
                               " (Originally specified framerate: " + str(fps) + ")")
        if (not right_protocol) and protocol:
            print(right_protocol)
            print(protocol)
            logger.warning("Protocol '" + protocol + "' not available for video " + filename + ".")
        return

    def init_download(self, seg, force=False, verbose=False):
        """
        Initialize download of a segment.

        Arguments:
            seg {Segment}
            force {bool} -- force overwriting output (default: {False})
            verbose {bool} -- logger.debug verbose messages (default: {False})
        """
        name, ext = os.path.splitext(seg.filename)
        if "protocol" not in seg.video_coding.__dict__.keys():
            protocol = None
        else:
            protocol = seg.video_coding.protocol.casefold()
        if seg.quality_level.fps.casefold() == 'original' or seg.quality_level.fps.casefold() == 'auto':
            frame_rate = seg.quality_level.fps
        else:
            SRC_fps = seg.src.get_fps()
            fps_split = seg.quality_level.fps.split('/')
            frame_rate = fps_split[-1]
            if int(SRC_fps) < int(fps_split[-1]):
                frame_rate = fps_split[0]

        self.download_video(
            seg.src.youtube_url,
            str(seg.quality_level.width),
            str(seg.quality_level.height),
            name,
            seg.quality_level.video_codec,
            str(seg.quality_level.video_bitrate),
            protocol=protocol,
            fps=frame_rate,
            force_overwriting=force,
            verbose=verbose
        )

    def encode_bitmovin(self, seg,  overwrite=False, config_name='default'):
        '''
        :param seg: video segment information
        :param overwrite: force overwriting existing files; default: False
        :param config_name: name of the configuration in bitmovin
        :return:
        '''

        if not self.bitmovin_initialized:
            logger.error("No settings for Bitmovin given. Please create the files under /processing-chain/bitmovin_settings/")
            return

        if '10' in seg.target_pix_fmt:
            tenBit = True
        else:
            tenBit = False

        audio = False
        filename = os.path.splitext(seg.filename)[0]

        if hasattr(seg.quality_level, 'audio_codec'):
            audio = True
            if seg.quality_level.audio_codec.casefold() != 'aac':
                logger.error("Audio_codec has to be 'aac', video was not coded.")
                sys.exit(1)
            elif seg.quality_level.audio_bitrate > 256:
                logger.warning("audio_bitrate too high. Bitmovin only supports bitrates up to 256kbit/s.")

        # check up to which point files exist -> use them
        if not self.overwrite:
            if seg.quality_level.video_codec.casefold() in ['h264', 'h265', 'hevc', 'avc']:
                full_video_path = os.path.join(self.video_segments_folder, seg.filename)
                if os.path.isfile(full_video_path):
                    return
                if self.download_from_sftp(filename):
                    return
            existence_level = self.check_output_existence_level(seg.get_filename(), seg.quality_level.video_codec, audio)
            logger.debug(existence_level)
            if existence_level == 3:
                logger.info(seg.get_filename() + " already exists. Use -f for overwriting")
                return
            if existence_level == 2:
                logger.info(seg.get_filename() + " will be generated from already existing video/audio chunks on your "
                                                 "PC. Use -f for overwriting")
                self.generate_full_segment(seg.get_filename(), seg.quality_level.video_codec.casefold(), tenBit, audio)
                return
            if existence_level == 1:
                logger.info(seg.get_filename() + " will be generated from already existing video/audio chunks on your "
                                                 "SFTP/Azure. Use -f for overwriting.")
                if self.output_details["output_type"] == "sftp":
                    self.download_from_sftp(filename)
                elif self.output_details["output_type"] == "azure":
                    self.download_from_azure(filename)
                self.generate_full_segment(seg.get_filename(), seg.quality_level.video_codec.casefold(), tenBit, audio)
                return

        bitmovin_instance = bitmovin.Bitmovin(api_key=self.bitmovinkey)

        # Create the input
        if self.input_details["input_type"] == "https":
            https_input = bitmovin.HTTPSInput(
                                name="test",
                                host=self.input_details["host"],
                                username=self.input_details["user"],
                                password=self.input_details["pw"]
                            )
            created_input = bitmovin_instance.inputs.HTTPS.create(https_input).resource

        elif self.input_details["input_type"] == "http":
            http_input = bitmovin.HTTPInput(
                                name="test",
                                host=self.input_details["host"],
                                username=self.input_details["user"],
                                password=self.input_details["pw"]
                            )
            created_input = bitmovin_instance.inputs.HTTP.create(http_input).resource

        elif self.input_details["input_type"] == "sftp":
            sftp_input = bitmovin.SFTPInput(
                                name="test",
                                host=self.input_details["host"],
                                username=self.input_details["user"],
                                password=self.input_details["pw"],
                                port=self.input_details["port"]
                            )
            created_input = bitmovin_instance.inputs.SFTP.create(sftp_input).resource

        if self.input_details["input_path"] and self.input_details["input_path"] != ".":
            in_path = os.path.join(self.input_details["input_path"], seg.src.filename)
        else:
            in_path = seg.src.filename

        logger.debug("Bitmovin input details: {}".format(self.input_details))
        logger.debug("Setting up input path: {}".format(in_path))

        # Select input file + stream
        video_input_stream = bitmovin.StreamInput(input_id=created_input.id,
                                                  input_path=in_path,
                                                  selection_mode=bitmovin.SelectionMode.AUTO)

        # If audio is wanted, the configuration of it is done here
        if audio:
            audio_input_stream = bitmovin.StreamInput(input_id=created_input.id,
                                                      input_path=in_path,
                                                      selection_mode=bitmovin.SelectionMode.AUTO)

            audio_codec_configuration = bitmovin.AACCodecConfiguration(name=filename + '_audio_configuration',
                                                                       bitrate=min(seg.quality_level.audio_bitrate, 256),
                                                                       rate=48000)

            audio_codec_configuration = bitmovin_instance.codecConfigurations.AAC.create(audio_codec_configuration).resource

        # Define the output
        if self.output_details["output_type"] == "azure":
            azure_output = bitmovin.AzureOutput(
                                account_name=self.output_details['azureaccount'],
                                account_key=self.output_details['azurekey'],
                                container=self.output_details['container']
                            )
            created_output = bitmovin_instance.outputs.Azure.create(azure_output).resource

        elif self.output_details["output_type"] == "sftp":
            sftp_output = bitmovin.SFTPOutput(
                                username=self.output_details['user'],
                                host=self.output_details['host'],
                                password=self.output_details['pw'],
                                port=self.output_details['port']
                            )
            created_output = bitmovin_instance.outputs.SFTP.create(sftp_output).resource

        else:
            logger.error("Output type {} is not supported".format(self.output_details["output_type"]))
            sys.exit(1)

        logger.debug("Bitmovin output details: {}".format(self.output_details))

        encoding = bitmovin_instance.encodings.Encoding.create(bitmovin.Encoding(name=filename, encoder_version=bitmovin.EncoderVersion.BETA)).resource

        # add audio to configuration
        if audio:
            audio_stream = bitmovin.Stream(codec_configuration_id=audio_codec_configuration.id,
                                           input_streams=[audio_input_stream], name=filename + '_AUDIO')
            audio_stream = bitmovin_instance.encodings.Stream.create(object_=audio_stream,
                                                                     encoding_id=encoding.id).resource

        # define variables for the video encoding configuration
        min_bitrate = None
        max_bitrate = None
        min_bitrate_pct = None
        max_bitrate_pct = None
        bufsize = None
        bitrate = seg.quality_level.video_bitrate*1000

        # set the right pixel-format
        # Distinguish between hevc/h265 and the other codecs
        if seg.quality_level.video_codec.casefold() in ["hevc", "h265"]:
            if seg.target_pix_fmt == "yuv420p":
                pix_fmt = bitmovin.PixelFormat.YUV420P
            elif seg.target_pix_fmt == "yuv420p10le":
                pix_fmt = bitmovin.PixelFormat.YUV420P10LE
            elif seg.target_pix_fmt == "yuv422p":
                pix_fmt = bitmovin.PixelFormat.YUV422P
            elif seg.target_pix_fmt == "yuv422p10le":
                pix_fmt = bitmovin.PixelFormat.YUV422P10LE
            else:
                pix_fmt = None
        # Case for the other codecs, because Bitmovin does not support 10Bit for them atm
        else:
            if "10" in seg.target_pix_fmt:
                logger.warning("10bit is only supported by hevc for bitmovin!")
            if "yuv420p" in seg.target_pix_fmt:
                pix_fmt = bitmovin.PixelFormat.YUV420P
            elif "yuv422p" in seg.target_pix_fmt:
                if seg.quality_level.video_codec.casefold() in ["avc", "h264"]:
                    logger.warning("pix_fmt yuv422p is currently broken for bitmovin")
                    pix_fmt = None
                else:
                    pix_fmt = bitmovin.PixelFormat.YUV422P
            else:
                pix_fmt = None

        if seg.quality_level.fps.casefold() == "original" or seg.quality_level.fps.casefold() == "auto":
            fps = None
        else:
            SRC_fps = seg.src.get_fps()
            fps_split = seg.quality_level.fps.split('/')
            fps = int(fps_split[-1])
            if int(SRC_fps) < int(fps_split[-1]):
                fps = int(fps_split[0])

        if seg.video_coding.minrate_factor:
            min_bitrate = seg.video_coding.minrate_factor * bitrate
            min_bitrate_pct = seg.video_coding.minrate_factor * 100

        if seg.video_coding.maxrate_factor:
            max_bitrate = seg.video_coding.maxrate_factor * bitrate
            max_bitrate_pct = seg.video_coding.maxrate_factor * 100

        if seg.video_coding.bufsize_factor:
            bufsize = seg.video_coding.bufsize_factor * bitrate

        video_profile = None
        video_quality = None
        config = None

        # generate configuration for h264
        if seg.quality_level.video_codec.casefold() == 'h264':
            logger.debug('h264 config')
            # get profile for h264, if not in seg.video_coding: main
            if hasattr(seg.video_coding, 'profile'):
                if seg.video_coding.profile.casefold() == 'main':
                    video_profile = bitmovin.H264Profile.MAIN
                elif seg.video_coding.profile.casefold() == 'high':
                    video_profile = bitmovin.H264Profile.HIGH
            if not video_profile:
                video_profile = bitmovin.H264Profile.MAIN

            config = bitmovin.H264CodecConfiguration(name='h264_' + filename,
                                                     bitrate=bitrate,
                                                     profile=video_profile,
                                                     rate=fps,
                                                     width=seg.quality_level.width,
                                                     height=seg.quality_level.height,
                                                     bframes=seg.video_coding.bframes,
                                                     min_bitrate=min_bitrate,
                                                     max_bitrate=max_bitrate,
                                                     bufsize=bufsize,
                                                     max_gop=seg.video_coding.max_gop,
                                                     min_gop=seg.video_coding.min_gop,
                                                     pixel_format=pix_fmt
                                                     )
            config = bitmovin_instance.codecConfigurations.H264.create(config).resource

        # or h265
        elif seg.quality_level.video_codec.casefold() in ['h265', 'hevc']:
            logger.debug('hevc config')
            if hasattr(seg.video_coding, 'profile'):
                if seg.video_coding.profile.casefold() == 'main':
                    video_profile = bitmovin.H265Profile.main
                elif seg.video_coding.profile.casefold() == 'main10':
                    video_profile = bitmovin.H265Profile.main10
            if not video_profile or video_profile == bitmovin.H265Profile.main:
                if '10' in seg.target_pix_fmt:
                    video_profile = bitmovin.H265Profile.main10
                else:
                    video_profile = bitmovin.H265Profile.main

            config = bitmovin.H265CodecConfiguration(name='h265_' + filename,
                                                     bitrate=bitrate,
                                                     profile=video_profile,
                                                     rate=fps,
                                                     width=seg.quality_level.width,
                                                     height=seg.quality_level.height,
                                                     bframes=seg.video_coding.bframes,
                                                     min_bitrate=min_bitrate,
                                                     max_bitrate=max_bitrate,
                                                     bufsize=bufsize,
                                                     max_gop=seg.video_coding.max_gop,
                                                     min_gop=seg.video_coding.min_gop,
                                                     pixel_format=pix_fmt
                                                     )
            config = bitmovin_instance.codecConfigurations.H265.create(config).resource

        # or vp9
        else:
            logger.debug('vp9 config')
            if hasattr(seg.video_coding, 'quality'):
                if seg.video_coding.quality.casefold() == 'good':
                    video_quality = bitmovin.VP9Quality.GOOD
                elif seg.video_coding.quality.casefold() == 'best':
                    video_quality = bitmovin.VP9Quality.BEST
                elif seg.video_coding.quality.casefold() == 'realtime':
                    video_quality = bitmovin.VP9Quality.REALTIME

            config = bitmovin.VP9CodecConfiguration(name='vp9_' + filename,
                                                    bitrate=bitrate,
                                                    rate=fps,
                                                    width=seg.quality_level.width,
                                                    height=seg.quality_level.height,
                                                    quality=video_quality,
                                                    rate_undershoot_pct=min_bitrate_pct,
                                                    rate_overshoot_pct=max_bitrate_pct,
                                                    pixel_format=pix_fmt
                                                    )

            config = bitmovin_instance.codecConfigurations.VP9.create(config).resource

        # combine video stream and video(+audio) configuration
        video_stream = bitmovin.Stream(codec_configuration_id=config.id, input_streams=[video_input_stream], name='Sample')
        video_stream = bitmovin_instance.encodings.Stream.create(object_=video_stream, encoding_id=encoding.id).resource

        acl_entry = bitmovin.ACLEntry(permission=bitmovin.ACLPermission.PUBLIC_READ)

        video_muxing_stream = bitmovin.MuxingStream(video_stream.id)

        if audio:
            audio_muxing_stream = bitmovin.MuxingStream(audio_stream.id)

        video_muxing_output = bitmovin.EncodingOutput(output_id=created_output.id,
                                                      output_path=os.path.join(self.output_details["output_path"], filename),
                                                      acl=[acl_entry])

        # Different video_muxing for H264/H264 and VP9
        logger.debug(seg.quality_level.video_codec.casefold())
        if seg.quality_level.video_codec.casefold() in ['h264', 'h265', 'hevc', 'avc']:
            logger.debug("will create mp4 muxing")
            video_muxing = bitmovin.MP4Muxing(streams=[video_muxing_stream],
                                              filename=filename + '.mp4',
                                              outputs=[video_muxing_output],
                                              name='filename')

            video_muxing = bitmovin_instance.encodings.Muxing.MP4.create(object_=video_muxing,
                                                                         encoding_id=encoding.id).resource
            if audio:
                video_muxing = bitmovin.MP4Muxing(streams=[video_muxing_stream, audio_muxing_stream],
                                                  filename=filename + '.mp4',
                                                  outputs=[video_muxing_output],
                                                  name='filename')

                video_muxing = bitmovin_instance.encodings.Muxing.MP4.create(object_=video_muxing,
                                                                             encoding_id=encoding.id).resource

        else:
            video_muxing = bitmovin.WebMMuxing(segment_length=4,
                                               segment_naming=filename+'_%number%.chk',
                                               init_segment_name=filename+'_init.hdr',
                                               streams=[video_muxing_stream],
                                               outputs=[video_muxing_output],
                                               name=filename)
            video_muxing = bitmovin_instance.encodings.Muxing.WebM.create(object_=video_muxing,
                                                                          encoding_id=encoding.id).resource

            if audio:
                audio_muxing_output = bitmovin.EncodingOutput(output_id=created_output.id,
                                                              output_path=os.path.join(self.output_details["output_path"],
                                                                                       filename, "audio"),
                                                              acl=[acl_entry])

                audio_muxing = bitmovin.FMP4Muxing(segment_length=4,
                                                   segment_naming=filename + '_%number%.chk',
                                                   init_segment_name=filename + '_init.hdr',
                                                   streams=[audio_muxing_stream],
                                                   outputs=[audio_muxing_output],
                                                   name=filename)
                audio_muxing = bitmovin_instance.encodings.Muxing.FMP4.create(object_=audio_muxing,
                                                                              encoding_id=encoding.id).resource

        bitmovin_instance.encodings.Encoding.start(encoding_id=encoding.id)

        try:
            bitmovin_instance.encodings.Encoding.wait_until_finished(encoding_id=encoding.id)
        except bitmovin.errors.BitmovinError as bitmovin_error:
            logger.error("Exception occurred while waiting for encoding to finish: {}".format(bitmovin_error))
            sys.exit(1)

        self.download_from_sftp(filename)
        if not seg.quality_level.video_codec.casefold() in ['h264', 'h265', 'hevc', 'avc']:
            self.generate_full_segment(seg.get_filename(), seg.quality_level.video_codec.casefold(), tenBit, audio)

    def download_from_sftp(self, filename):

        output_path = os.path.join(self.video_segments_folder, filename)
        logger.debug(output_path)
        if not os.path.isdir(output_path):
            os.mkdir(output_path)

        transport = paramiko.Transport((self.output_details['host'].split(":")[0], self.output_details['port']))

        transport.connect(
                username=self.output_details['user'],
                password=self.output_details['pw']
            )

        sftp = paramiko.SFTPClient.from_transport(transport)
        remotepath = os.path.join(self.output_details["output_path"], filename)
        try:
            S_ISDIR(sftp.stat(remotepath).st_mode)
        except:
            sftp.close()
            transport.close()
            return 0

        dir_entries = sftp.listdir(remotepath)

        for entry in dir_entries:
            entry_path = os.path.join(remotepath, entry)
            if S_ISDIR(sftp.stat(entry_path).st_mode):
                self.download_from_sftp(os.path.join(filename, entry))
            elif entry.endswith("_init.mp4") or entry.endswith(".m4s"):
                sftp.remove(entry_path)
            elif entry.endswith("_init.hdr") or entry.endswith(".chk"):
                sftp.get(remotepath=entry_path,
                         localpath=os.path.join(self.video_segments_folder, filename, entry))
            else:
                sftp.get(remotepath=entry_path,
                         localpath=os.path.join(self.video_segments_folder, entry))

        sftp.close()
        transport.close()

    def generate_full_segment(self, filename, codec, ten_bit=False, audio=False):

        if ten_bit:
            ffmpeg_version = "ffmpeg10"
        else:
            ffmpeg_version = "ffmpeg"

        root, ext = os.path.splitext(filename)
        full_video_path = os.path.join(self.video_segments_folder, filename)
        dload_path = os.path.join(self.video_segments_folder, root)
        video_outfile = os.path.join(dload_path, root + "_video_only" + ext)
        concat_cmd = ffmpeg_version + " -y -i " + video_outfile + " -strict -2 -c copy " + full_video_path

        video_init_element = None
        video_parts = []
        video_init_found = False

        directory = os.fsencode(dload_path)

        for video_part in os.listdir(directory):
            video_part_name = os.fsdecode(video_part)
            if video_part_name.endswith("init.hdr") and codec == "vp9" \
                    or video_part_name.endswith("init.mp4") and codec in ["h264", "h265", "hevc"]:
                if video_init_found:
                    logger.warning("Second init file found. Please clean your download folder " + dload_path)
                video_init_element = video_part_name
                video_init_found = True
                continue
            elif video_part_name.endswith(".chk") and codec == "vp9" \
                    or video_part_name.endswith(".m4s") and codec in ["h264", "h265", "hevc"]:
                raw_name = os.path.splitext(video_part_name)[0]
                part_number = int(raw_name.split("_")[-1])
                while len(video_parts) <= part_number:
                    video_parts.append("Dummy_entry")
                video_parts[part_number] = video_part_name
                continue
        if not video_init_found:
            logger.error("No init file found! Aborting")
            exit(-1)
        cmd = ffmpeg_version + """ -y -i \"concat:""" + os.path.join(dload_path, video_init_element)
        for video_part_name in video_parts:
            cmd = cmd + "|" + os.path.join(dload_path, video_part_name)

        cmd = cmd + """" -c copy -strict -2 """ + video_outfile
        cmd_utils.run_command(cmd)

        if audio:
            audio_init_element = None
            audio_parts = []
            audio_init_found = False

            dload_path = os.path.join(dload_path, "audio")
            logger.debug(dload_path)
            directory = os.fsencode(dload_path)

            audio_outfile = os.path.join(dload_path, root + "_audio_only.mp4")

            for audio_part in os.listdir(directory):
                audio_part_name = os.fsdecode(audio_part)
                logger.debug(audio_part_name)
                if audio_part_name.endswith("init.hdr") and codec == "vp9" \
                        or audio_part_name.endswith("init.mp4") and codec in ["h264", "h265", "hevc"]:
                    if audio_init_found:
                        logger.warning("Second init file found. Please clean your download folder " + dload_path)
                    audio_init_element = audio_part_name
                    audio_init_found = True
                    continue
                elif audio_part_name.endswith(".chk") and codec == "vp9" \
                        or audio_part_name.endswith(".m4s") and codec in ["h264", "h265", "hevc"]:
                    raw_name = os.path.splitext(audio_part_name)[0]
                    part_number = int(raw_name.split("_")[-1])
                while len(audio_parts) <= part_number:
                    audio_parts.append("Dummy_entry")
                    audio_parts[part_number] = audio_part_name
                    # audio_parts.append(audio_part_name)
                    continue

            if audio_init_found:
                # TODO: implement force overwriting
                cmd = ffmpeg_version + """ -y -i \"concat:""" + os.path.join(dload_path, audio_init_element)
                for audio_part_name in audio_parts:
                    cmd = cmd + "|" + os.path.join(dload_path, audio_part_name)

                cmd = cmd + """" -c copy -strict -2 """ + audio_outfile
                cmd_utils.run_command(cmd)

                concat_cmd = ffmpeg_version + " -y -i " + video_outfile + " -i " + audio_outfile + " -strict -2 -c copy " + full_video_path
            else:
                logger.warning("No audio file for " + root + " found. Will create a video without audio!")

        cmd_utils.run_command(concat_cmd)

    def check_output_existence_level(self, filename, codec, audio):
        # existence levels:
        # 3: Final segment is existent
        # 2: Video (and audio) chunks are existent
        # 1: no files on local machine (at least init and first chunk of audio or video are missing)
        # 0: no files on sftp/azure output (at least init and first chunk of audio or video are missing)

        # first check if there is a video on the local machine
        root, ext = os.path.splitext(filename)
        full_video_path = os.path.join(self.video_segments_folder, filename)
        if os.path.isfile(full_video_path):
            return 3

        # check if the files generated from the chunks are existent
        dload_path = os.path.join(self.video_segments_folder, root)

        video_init_found = False
        # If folder exists, check if the chunks are existent
        if os.path.isdir(dload_path):

            directory = os.fsencode(dload_path)
            # check if the chunks are existent
            for video_part in os.listdir(directory):
                video_part_name = os.fsdecode(video_part)
                if video_part_name.endswith("init.hdr") and codec == "vp9" \
                        or video_part_name.endswith("init.mp4") and codec in ["h264", "h265", "hevc"]:
                    if video_init_found:
                        logger.warning("Second init file found. Please clean your download folder " + dload_path)
                    video_init_found = True
                    continue
                elif video_part_name == root + "_0.chk" and codec == "vp9" \
                        or video_part_name == root + "_0.m4s" and codec in ["h264", "h265", "hevc"]:
                    first_video_chunk_found = True
                    continue

            # If audio is desired, check if these files are available, too
            if audio:
                audio_init_found = False
                first_audio_chunk_found = False

                dload_path = os.path.join(dload_path, "audio")
                if os.path.isdir(dload_path):
                    directory = os.fsencode(dload_path)

                    for audio_part in os.listdir(directory):
                        audio_part_name = os.fsdecode(audio_part)

                        if audio_part_name.endswith("init.hdr") and codec == "vp9" \
                                or audio_part_name.endswith("init.mp4") and codec in ["h264", "h265", "hevc"]:
                            if audio_init_found:
                                logger.warning(
                                    "Second init file found. Please clean your download folder " + dload_path)
                            audio_init_found = True
                            continue
                        elif audio_part_name == root + "_0.chk" and codec == "vp9" \
                                or audio_part_name == root + "_0.m4s" and codec in ["h264", "h265", "hevc"]:
                            first_audio_chunk_found = True
                            continue
            else:
                audio_init_found = True
                first_audio_chunk_found = True

            if video_init_found and first_video_chunk_found and audio_init_found and first_audio_chunk_found:
                return 2

        # then check if there are files lying on the output of bitmovin
        if self.output_details["output_type"] == "sftp":

            transport = paramiko.Transport((self.output_details['host'].split(":")[0], self.output_details['port']))
            transport.connect(username=self.output_details['user'], password=self.output_details['pw'])

            sftp = paramiko.SFTPClient.from_transport(transport)
            remotepath = os.path.join(self.output_details["output_path"], root)
            try:
                S_ISDIR(sftp.stat(remotepath).st_mode)
            except:
                sftp.close()
                transport.close()
                logger.warning("Checking existing files on SFTP failed!")
                return 0
            dir_entries = sftp.listdir(remotepath)

            video_init_found = False
            first_video_chunk_found = False
            audio_init_found = True
            first_audio_chunk_found = True
            search_audio = False

            for entry in dir_entries:
                if entry.endswith("init.hdr") and codec == "vp9" \
                        or entry.endswith("init.mp4") and codec in ["h264", "h265", "hevc"]:
                    if video_init_found:
                        logger.warning("Second init file found. Please clean your download folder " + remotepath)
                    video_init_found = True
                    continue
                elif entry == root + "_0.chk" and codec == "vp9" \
                        or entry == root + "_0.m4s" and codec in ["h264", "h265", "hevc"]:
                    first_video_chunk_found = True
                    continue
                entry_path = os.path.join(remotepath, entry)
                if S_ISDIR(sftp.stat(entry_path).st_mode) and entry == "audio":
                    search_audio = True

            if search_audio:
                first_audio_chunk_found = False
                audio_init_found = False
                dir_entries = sftp.listdir(os.path.join(remotepath, "audio"))

                for entry in dir_entries:
                    if entry.endswith("init.hdr") and codec == "vp9" \
                            or entry.endswith("init.mp4") and codec in ["h264", "h265", "hevc"]:
                        if audio_init_found:
                            logger.warning(
                                "Second init file found. Please clean your download folder " + os.path.join(
                                    remotepath, "audio"))
                        audio_init_found = True
                        continue
                    elif entry == root + "_0.chk" and codec == "vp9" \
                            or entry == root + "_0.m4s" and codec in ["h264", "h265", "hevc"]:
                        first_audio_chunk_found = True
                        continue

            sftp.close()
            transport.close()

            if video_init_found and first_video_chunk_found and audio_init_found and first_audio_chunk_found:
                return 1
            else:
                return 0
