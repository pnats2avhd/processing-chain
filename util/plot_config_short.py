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
Start from a AVHD-AS/P.NATS phase2 test configuration yaml file and plot the HRCs.

@todo : Currently, it plots a rectangle in the frame height - bitrate plane.
@todo : instead of a rectangle, visualize some encoder settings like GOP size, codec (e.g. color),...


A 'WARNING' is printed if the configuration file check fails
@todo : some config file checking --> see check_config.py.


EXAMPLE:

Make a plot corresponding to the config file 'testConfig.yaml' and
store the plot under 'testConfig.svg'.

>>> python plot_config.py P2STR00.yaml


NOTE:

To use the script from within the virtual machine, install packages:

> sudo apt-get update &&
> sudo apt-get --assume-yes install python-dev
> sudo pip install matplotlib
"""

import os
import sys
import matplotlib

matplotlib.use('svg')
from matplotlib.patches import *
from matplotlib.collections import PatchCollection
from pylab import *

sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
import lib.test_config as cfg
import lib.log as log
logger = log.setup_custom_logger('main')


# scale the x and y axis, such that the plane is used in a more uniform manner
def scale_x(x):
    return sqrt(x)


def scale_y(y):
    return log(y)


def plot_hrc(ax, height, bitrate):
    """
    Plot attributes of an HRC, currently:

    bitrate, frame height.
    """
    ax.add_patch(Rectangle((scale_x(height), scale_y(bitrate)), scale_x(2), scale_y(1.2), color='red'))


def create_plot(config):
    """
    Plot the test design in a resolution-bitrate plot.
    """
    fig = figure(figsize=(10, 10))
    ax = fig.add_subplot(111)

    x_t = array([120, 240, 360, 480, 720, 1080, 2160])
    y_t = array([10 ** i for i in range(2, 6)])
    xticks(scale_x(x_t), x_t)
    yticks(scale_y(y_t), y_t)
    xlim([min(scale_x(x_t)), max(scale_x(x_t))])
    ylim([min(scale_y(y_t)), max(scale_y(y_t))])

    for hrc, event_list in config.data['hrcList'].items():
        bitrate = config.get_bitrate(hrc)[0]
        height = config.get_height(hrc)[0]

        plot_hrc(ax, height, bitrate)

    xlabel('frame height')
    ylabel('bitrate in kbit/s')
    fig.suptitle('AVHD-AS/P.NATS phase2 framework')


def create_plot_codecwise(config, yamlPath):
    """

    :param config: parsed yaml file
    :param yamlPath: path of the yaml-file -> same path will be used for output files

    Supported videocodecs are: vp9, h264, h265

    """
    bitrates = [[], [], []]
    heights = [[], [], []]
    videoCodecs = ['vp9', 'h264', 'h265']

    (dir, tail) = os.path.split(yamlPath)
    databaseName = os.path.splitext(tail)[0]
    savepath = os.path.join(dir, databaseName + '_datarate-resolution_plot_')

    for hrc, event_list in config.data['hrcList'].items():
        q_level = [e[0] for e in config.data['hrcList'][hrc]['eventList']]
        videoCodec = [config.data['qualityLevelList'][q]['videoCodec'] for q in q_level]
        videoCodec = videoCodec[0]

        if videoCodec not in videoCodecs:
            print("Unexpected video codec %s ! Ignoring it..." % videoCodec)

        else:
            position = videoCodecs.index(videoCodec)

            bitrates[position].append(config.get_bitrate(hrc)[0])
            heights[position].append(config.get_height(hrc)[0])

    for counter in range(len(videoCodecs)):
        fig = figure(figsize=(10, 10))
        ax = fig.add_subplot(111)

        x_t = array([120, 240, 360, 480, 720, 1080, 2160])
        xticks(x_t)

        ax.scatter(heights[counter], bitrates[counter])  # new

        xlabel('frame height')
        ylabel('bitrate in kbit/s')

        ax.grid(True)
        ax.set_title(videoCodecs[counter])
        fig.suptitle('AVHD-AS/P.NATS phase2 framework')

        plot_file = savepath + videoCodecs[counter] + '.svg'

        savefig(plot_file)
        print("Created plot and saved it in %s." % plot_file)


def info_str(plot_fn):
    return ('Create a plot of video test conditions and \nstore it in %s' % plot_fn)


"""------------------------------------------------------------------
   running the script will make a plot, the first argument is the config
   file name. The plot will be stored in a svg file."""

if __name__ == "__main__":
    if not len(sys.argv) >= 2:
        print('Usage:\n')
        print('./plot_config.py <config_file.yaml> (-codec-wise)')
        print('')
        print(info_str('<config_file.svg>'))
        print('')
        print('Optional:')
        print('-codec-wise: create a single plot for every codec')
        print('')
    elif len(sys.argv) == 3:

        if sys.argv[2] == '-codec-wise':
            config = cfg.TestConfig(sys.argv[1])

            outputPath = os.path.realpath(sys.argv[1])

            create_plot_codecwise(config, outputPath)

        else:
            print('Unknown option %s' % sys.argv[2])
            print('')
            print('Usage:\n')
            print('./plot_config.py <config_file.yaml> (-codec-wise)')
            print('')
            print(info_str('<config_file.svg>'))
            print('')
            print('Optional:')
            print('-codec-wise: create a single plot for every codec')
            print('')
    else:
        config = cfg.TestConfig(sys.argv[1])

        create_plot(config)

        plot_file = sys.argv[1][:-5] + '.svg'

        savefig(plot_file)

        print('Created plot and stored it in %s' % plot_file)
