#!/usr/bin/env python
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
Start from a P.NATS test configuration yaml file and plot the HRCs.

The fill intensity is proportional to the bitrate of the chunk.
For video, chunks of frame heights 1080, 480, 240 are blue, for a
better distinction those of height 720, 360 are purple.

The taller rectangles within a video chunk indicate segment duration,
the lower rectangles indicate GOP duration.

A 'WARNING' is printed on chunks, for which either the chunk duration
is not an integer multiple of segment duration, or segment duration
is not an integer multiple of GOP duration, or the segment duration
is different from the segment duration in the previous chunk.


EXAMPLE:

Make a plot corresponding to the config file 'testConfig.yaml' and
store the plot under 'testConfig.svg'.

> python plot_config.py testConfig.yaml

TODO:


NOTE:

To use the script from within the virtual machine, install packages:

> sudo apt-get update &&
> sudo apt-get --assume-yes install python-dev
> sudo pip install matplotlib
"""

import os
import yaml
import sys
# import re
import numpy as np
import matplotlib
matplotlib.use('svg')
from matplotlib.patches import *
from matplotlib.collections import PatchCollection
from pylab import *


plot_param = {'audio_height': 0.1,
              'stall_height': 0.03,
              'stall_offset': 0.025,
              'v_offset': 0.2,
              'v_height_max': 0.5,
              'v_res_max': 2160,
              'label_offset': 0.025}


def get_representation(reps, this_id):
    """
    Return a representation (audioVisualQualityLevel) corresponding to
    the id string (quality description) of the test condition segment.
    """

    for r in reps:
        if r==this_id:
            return r
    return None


def get_video_alpha(av_rep, value, index=1):
    y = [log(x[index]) for x in av_rep]
    # use strong filling if only one representation
    if max(y)-min(y) < 0.01:
        return 0.8
    # else use light to strong
    else:
        return 0.2+0.8*(log(value)-min(y))/(0.01+max(y)-min(y))


def get_audio_alpha(av_rep, value):
    return get_video_alpha(av_rep, value, index=3)


def plot_filename(config_filename):
    # return config_filename[:-5]+'.png'
    return config_filename[:-5]+'.svg'


def convert_percentage_to_sec(event_list, video_duration):
    return [[e[0], e[1]*video_duration] for e in event_list]


def get_colors():
    #    return matplotlib.cm.Dark2_r.colors
    return ['#800000', '#e6194b', '#f58231', '#ffe119', '#a6d96a', '#3cb44b', '#4393c3', '#2166ac']


def get_height_list():
    return [240, 360, 480, 540, 720, 1080, 1440, 2160]


def get_color(height):
    height_list = get_height_list()
    i = [i for i, h in enumerate(height_list) if h >= height][0]
    return get_colors()[i]


def plot_legend():
    import matplotlib.patches as mpatches
    height_list = get_height_list()
    leg_pat = [mpatches.Patch(color=get_color(h), label='%d' % h) for h in height_list]
    legend(handles=leg_pat)


def get_face_color(av_rep, rep):
    return get_color(rep['height'])


def is_int_multiple(x_mult, y):
    """
    Return 'True' if and only if x_mult is an integer multiple of y.
    """
    is_mult = False
    if mod(float(x_mult)/float(y), 1) < 0.0001:
        is_mult = True
    return is_mult


def plot_stream(event_list, av_rep, ax, y_offset, video_duration, segment_dur, gop_dur, stream_label, av_type='video'):
    """
    Create a plot of the HRCs

    INPUT:
    event_list     -- list of quality levels/stallling, e.g. [['buffering', 4], ['Q1080', 20], ['Q360', 5], ['Q1080', 15], ['Q360', 5], ['Q1080', 15]]
    av_rep         -- list of quality levels, e.g. [[1080, 2500, 'Q1080', 128], [720, 1400, 'Q720', 128], [480, 500, 'Q480', 96], [360, 400, 'Q360', 96], [240, 150, 'Q240', 64]]
    ax             -- figure axes
    y_offset       -- float, y-axis offset
    video_duration -- float, default video duration
    segment_dur    -- segment duration in seconds, per quality level, e.g. {'Q720': 1, 'Q240': 5, 'Q1080': 5, 'Q480': 5, 'Q1080': 5, 'Q360': 5}
    gop_dur        -- gop duration in seconds, per quality level, e.g. {'Q720': 2, 'Q240': 5, 'Q1080': 1, 'Q480': 2, 'Q1080': 1, 'Q360': 1}
    stream_label   -- string, label
    av_type        -- either 'audio' or 'video'
    """
    has_warning = False
    t = 0
    seg_dt = 0

    # check constraints on chunk duration:
    if av_type == 'video':
        # check that first chunk is at least 5s long
        first_chunk_duration = event_list[0][1]
        if first_chunk_duration < 5.0:
            print('HRC %s' % stream_label)
            print('First chunk duration < 5 seconds!')
            has_warning = True
        # check that last chunk is at least 10s long
        last_chunk_duration = event_list[-1][1]
        if (last_chunk_duration < 10.0 and video_duration > 60) or last_chunk_duration < 5.0:
            print('HRC %s' % stream_label)
            print('Last chunk duration < 10 seconds!')
            has_warning = True

    for i_e, e in enumerate(event_list):

        seg_id = e[0]
        duration = e[1]
        if duration == 0:
            continue

        if seg_id == 'buffering' or seg_id == 'stall':
            stall_offset = y_offset
            if av_type == 'video':
                stall_offset += plot_param['v_offset']
            if t == 0:
                ax.add_patch(Rectangle((0, stall_offset), duration, plot_param['stall_height'], fc='grey'))
            else:
                ax.add_patch(Rectangle((t, stall_offset), duration, plot_param['stall_height'], fc='grey'))
            t += duration
            seg_dt = duration

        else:
            seg_previous_dt = seg_dt
            seg_dt = segment_dur
            # gop_dt = gop_dur[seg_id]

            # check suitable parameters:
            # check that segment duration is the same as for the first chunk
            if seg_previous_dt > 0 and not seg_previous_dt == seg_dt:
                print('HRC %s' % stream_label)
                print('segment %s' % seg_id)
                print('Previous segment has duration=%1.2f, current segment duration=%1.2f' % (seg_previous_dt, seg_dt))
                has_warning = True

            rep = av_rep[seg_id]

            # add warning text
            if has_warning:
                # ax.text(t,y_offset+plot_param['v_offset'],"WARNING",rotation=30,rotation_mode='anchor',color='red')
                has_warning = False

            for i_seg in range(int(int(duration)/seg_dt)):
                if av_type == 'video':
                    height = rep['height']*plot_param['v_height_max']/plot_param['v_res_max']
                    # v_alpha = 1 # get_video_alpha(av_rep,rep[1])
                    col = get_face_color(av_rep, rep)
                    # col = [1-v_alpha,1-v_alpha,1]
                    # if rep[0]==1440 or rep[0]==720 or rep[0]==360:
                    #     col = [1-v_alpha/2,1-v_alpha,1]
                    # plot each segment individually
                    ax.add_patch(Rectangle((t, y_offset+plot_param['v_offset']), seg_dt, height,
                                 fc=col, ec='grey'))
                    # add gop lines
                    # for j_gop in range(seg_dt/gop_dt):
                    #     ax.add_patch(Rectangle((t+j_gop*gop_dt,y_offset+plot_param['v_offset']),\
                    #                  gop_dt,240*height/rep[0],lw=0.5,fc='none',ec='grey'))

                else:
                    pass
                    # a_alpha = get_audio_alpha(av_rep,rep[3])
                    # ax.add_patch(Rectangle((t,y_offset),seg_dt,plot_param['audio_height'],\
                    #              fc=[1,1-.1*a_alpha,1-0.8*a_alpha],ec='grey'))
                t += seg_dt


def get_duration(event_list):
    return sum([e[1] for e in event_list])


def create_plot(config_file):

    # read and parse configuration
    config = yaml.load(open(config_file))
    av_rep = config['qualityLevelList']
    hrc_list = config['hrcList']
    video_duration = np.min([get_duration(h['eventList']) for h in hrc_list.values()])
    segment_dur = config['segmentDuration']
    # gop_dur = config['GopLengthInSecPerQl']
    gop_dur = 0

    # prepare plot
    fig = figure(figsize=(min(video_duration/6, 35), len(hrc_list)))
    ax = fig.add_subplot(111)
    label = []
    max_duration = 0
    # plot HRCs
    for i, hrc_id in enumerate(sorted(hrc_list.keys())):
        hrc = hrc_list[hrc_id]
        event_list = hrc['eventList']

        # if hrc['type'] == 'customPercent':
        #    event_list = convert_percentage_to_sec(event_list,video_duration)

        max_duration = max(max_duration, get_duration(event_list))

        y_offset = len(hrc_list)-i-1
        # --- hrc to plot ---------------------------------------------------------
        plot_stream(event_list, av_rep, ax, y_offset, video_duration, segment_dur, gop_dur, hrc_id, 'video')
        plot_stream(event_list, av_rep, ax, y_offset, video_duration, segment_dur, gop_dur, hrc_id, 'audio')
        # -------------------------------------------------------------------------
        label.append(hrc_id)
        label.append('video')
        label.append('audio')

    # add ticks and labels...
    label.reverse()
    r = arange(0., len(hrc_list))+plot_param['label_offset']
    ytick_position = reshape([r, r+plot_param['v_offset'], r+2*plot_param['v_offset']], 3*len(r), 'F')
    yticks(ytick_position, label, fontsize='x-small')
    xlabel('time in seconds')
    # .. and set limits...
    ylim([-.1, len(hrc_list)+1])
    xlim([0, max_duration*1.05])
    # plot line at video duration
    plot([video_duration, video_duration], ylim(), '-k', alpha=0.3)
    # .. and title ..
    title(config['databaseId']+' : '+os.path.basename(config_file))
    suptitle('P.NATS framework')
    plot_legend()
    # .. save plot
    savefig(plot_filename(config_file))


def info_str(plot_fn):
    return ('Created a plot of audio/video test conditions and \nstored it in %s' % plot_fn)


"""------------------------------------------------------------------
   run the script will make a plot, the first argument is the config
   file name. The plot will be stored in a svg file."""

if __name__ == "__main__":
    if not len(sys.argv) == 2:
        print('Usage:\n')
        print('./plot_config.py <config_file.yaml>')
        print('')
        print(info_str('<config_file.svg>'))
        print('')
    else:
        config_file = sys.argv[1]
        print(info_str(plot_filename(config_file)))
        print("Note: Some durations will not add up to the real duration of the events.")
        create_plot(config_file)
