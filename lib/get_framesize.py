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

import lib.cmd_utils as cmd_utils
import os.path
from os import remove

logger = logging.getLogger('main')


def delete_packets(pvs_vfi):
    """
    Delete packets from VFI output
    """
    last_dts = -10
    mergedPackets = 0
    packets_to_delete = []

    # if dts differ only marginally, they belong together in one superframe -> one is not displayed
    vp9_size = 0
    for index, vf in enumerate(pvs_vfi):
        if pvs_vfi[index]["index"] == 0:
            mergedPackets_segment = 0
        vp9_size += int(pvs_vfi[index]["size"])
        if abs(vf["dts"] - last_dts) < 0.0011:
            pvs_vfi[index - 1]["size"] = int(pvs_vfi[index - 1]["size"]) + int(vf["size"])
            packets_to_delete.append(index - mergedPackets)
            mergedPackets += 1
            mergedPackets_segment += 1
            logger.debug("videoFrames merged!")
        else:
            pvs_vfi[index]["index"] = vf["index"] - mergedPackets_segment
        last_dts = vf["dts"]
    for packet_to_delete in packets_to_delete:
        del (pvs_vfi[packet_to_delete])


def convert_file(filename, codec, force):
    if force:
        add_y = " -y "
    else:
        add_y = ""
    cmd = "ffmpeg {add_y} -i {filename} -vcodec copy -acodec copy".format(**locals())
    # copy vp9 stream to vfi container -> nice to parse
    if codec == 'vp9':
        conv_filename = "".join([filename, "_tmp.ivf"])
        cmd += " {conv_filename}".format(**locals())
    # create file with raw h264 stream formatted according to annex-b
    elif codec == 'h264':
        conv_filename = "".join([filename, "_tmp.h264"])
        cmd += " -bsf:v h264_mp4toannexb {conv_filename}".format(**locals())
    # create file with raw h265 stream formatted according to annex-b
    else:
        conv_filename = "".join([filename, "_tmp.h265"])
        cmd += " -bsf:v hevc_mp4toannexb {conv_filename}".format(**locals())
    # if there is already a temporary file, use this if -f is not specified
    if os.path.isfile(conv_filename) and not force:
        return conv_filename
    cmd_utils.run_command(cmd, "converting {filename} to {conv_filename}".format(**locals()))

    return conv_filename


def remove_convFile(conv_filename):
    if os.path.isfile(conv_filename):
        remove(conv_filename)
    else:
        print("Tried to delete {conv_filename}, but it was not found!")


def get_framesize_vp9(filename, force):
    conv_filename = convert_file(filename, 'vp9', force)

    framesizes = []
    nrFrames = 0
    with open(conv_filename, 'rb') as openFile:
        # skip the header of ivf container
        openFile.seek(32)
        # frame head of ivf container contains framesize in first 3 bytes
        byte_read = openFile.read(3)
        # search for new frames until everything is read
        while byte_read != b'' and len(byte_read) == 3:
            nrFrames = nrFrames + 1
            hex_bytes = ''
            for char in byte_read:
                hex_byte = hex(ord(chr(char)))
                if len(hex_byte) == 3:
                    hex_byte = hex_byte[0:2] + '0' + hex_byte[2]
                hex_bytes = hex_byte[2:4] + hex_bytes
            hex_bytes = '0x' + hex_bytes

            framesizes.append(int(hex_bytes, 16))
            # get frame type from uncompressed header (from vp9)
            openFile.seek(int(12-3), 1)
            byte_read = openFile.read(3)
            if byte_read != b'' and len(byte_read) == 3:
                bin_bytes = []
                bin_bytes_string = ""

                # form a big string
                for char in byte_read:
                    bin_bytes.append(bin(ord(chr(char)))[2:])
                    while len(bin_bytes[-1]) != 8:
                        bin_bytes[-1] = "0" + bin_bytes[-1]
                    bin_bytes_string = bin_bytes_string + bin_bytes[-1]
                # frame data should start with "10", otherwise no frame
                pos = 0
                if bin_bytes_string[pos:pos+2] != "10":
                    print("Frame misdeteciton! Aborting...")
                pos += 2
                # if preset == 11 -> reserved 0

                if bin_bytes_string[pos:pos+2] == "11":
                    pos += 1
                pos += 2

                if bin_bytes_string[pos] == 1:
                    pos += 3
                pos += 1

            openFile.seek(int(hex_bytes, 16) + 12 - 3 - 12, 1)
            byte_read = openFile.read(3)

    remove_convFile(conv_filename)
    return framesizes


def get_framesize_h264(filename, force):
    conv_filename = convert_file(filename, 'h264', force)

    byte = [None, None, None, None, None]
    cur_framesize = 0
    is_frame = False
    nal_detected = False
    framesizes = []

    with open(conv_filename, 'rb') as openFile:
        tmp = openFile.read(1)
        if tmp == b'':
            return framesizes
        # format to hex, because it is nicer readable than chars
        byte[0] = hex(ord(tmp))

        while True:  # byte != b'':
            cur_framesize += 1
            # check if NAL symbol is detected
            if byte[0] == '0x1' and byte[1] == '0x0' and byte[2] == '0x0':
                nal_detected = True
                if is_frame:
                    if byte[3] == '0x0' and byte[4] == '0x0':
                        framesizes.append(cur_framesize - 5)
                    else:
                        framesizes.append(cur_framesize - 3)
                # if frame was detected, search for a new one!
                is_frame = False
                # reset cur_framesize as we have indicated a new packet
                cur_framesize = 0
            # to get the bytes indicating the content, take the 8 bits directly after the NAL symbol
            if nal_detected and cur_framesize == 1:
                # if the byte after NAL pattern ends with 00001 or 00101 -> frame starting
                # first check: check the last 4 bits
                # second check: check the 4th bit -> if byte[0][-2] is 'x' the byte is e.g. '0x05', but the 0
                # is omitted in python -> therefore check for x, otherwise check if the number is even -> 4th bit is 0
                if (byte[0][-1] == '5' or byte[0][-1] == '1') and (byte[0][-2] == 'x' or int(byte[0][-2]) % 2 == 0):
                    # now we have a frame
                    is_frame = True
                # NAL pattern no more detected
                nal_detected = False

            # store old bytes
            byte[4] = byte[3]
            byte[3] = byte[2]
            byte[2] = byte[1]
            byte[1] = byte[0]
            tmp = openFile.read(1)
            # if no more byte is available, we're at the end
            if tmp == b'':
                # if we found a frame located at the end, append the size of the last frame
                if is_frame:
                    framesizes.append(cur_framesize + 3)
                openFile.close()
                remove_convFile(conv_filename)
                return framesizes
            # format input to hex -> better to handle than chars
            byte[0] = hex(ord(tmp))


def get_framesize_h265(filename, force):
    conv_filename = convert_file(filename, 'h265', force)

    byte = [None, None, None, None, None]
    cur_framesize = 0
    is_frame = False
    nal_detected = False
    framesizes = []

    with open(conv_filename, 'rb') as openFile:
        tmp = openFile.read(1)
        if tmp == b'':
            return framesizes
        # format to hex, because it is nicer readable than chars
        byte[0] = hex(ord(tmp))

        while True:  # byte != b'':
            cur_framesize += 1
            # check if NAL pattern is detected
            if byte[0] == '0x1' and byte[1] == '0x0' and byte[2] == '0x0':
                nal_detected = True
                if is_frame:
                    if byte[3] == '0x0' and byte[4] == '0x0':
                        framesizes.append(cur_framesize - 5)
                    else:
                        framesizes.append(cur_framesize - 3)
                # if frame was detected, search for a new one!
                is_frame = False
                # reset cur_framesize as we have indicated a new packet
                cur_framesize = 0
            # to get the bytes indicating the content, take the 8 bits directly after the NAL pattern
            if nal_detected and cur_framesize == 1:
                # if the 4 bits after NAL pattern ends are 0000/0001/0010 -> frame starting
                # Note: the bits are represented by hex numbers 0x02 will be 0x2
                # next 4 bits -> look at them depending on 4 bits after NAL pattern
                # The Byte is of the following form : 0xxx|xxxy where x indicates the bit is dedicated to NAL unit
                # identification
                if (byte[0][-2] == 'x') or (byte[0][-2] == '1' and int(byte[0][-1], 16) < 4) or (byte[0][-2] == '2' and int(byte[0][-1], 16) < 12):
                    # now we have a frame
                    is_frame = True
                # NAL unit detection disabled
                nal_detected = False

            # store old bytes
            byte[4] = byte[3]
            byte[3] = byte[2]
            byte[2] = byte[1]
            byte[1] = byte[0]
            tmp = openFile.read(1)
            # if no byte is available, we're at the end
            if tmp == b'':
                # if we found a frame located at the end, append the size of the last frame
                if is_frame:
                    framesizes.append(cur_framesize)
                openFile.close()
                # remove temp file TODO: implement switch to keep it
                remove_convFile(conv_filename)
                return framesizes
            # format input to hex -> better to handle than chars
            byte[0] = hex(ord(tmp))
