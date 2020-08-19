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
Logger helper class
"""

import logging

loggers = {}


def setup_custom_logger(name, debug=False):
    """
    Create a logger with a certain name and level
    """
    global loggers

    if loggers.get(name):
        return loggers.get(name)

    formatter = logging.Formatter(
        fmt='%(asctime)s - %(levelname)s - %(module)s: %(message)s'
    )

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    # \033[1;30m - black
    # \033[1;31m - red
    # \033[1;32m - green
    # \033[1;33m - yellow
    # \033[1;34m - blue
    # \033[1;35m - magenta
    # \033[1;36m - cyan
    # \033[1;37m - white

    logging.addLevelName(logging.ERROR,     "\033[1;31m%s\033[1;0m" % logging.getLevelName(logging.ERROR))
    logging.addLevelName(logging.WARNING,   "\033[1;33m%s\033[1;0m" % logging.getLevelName(logging.WARNING))
    logging.addLevelName(logging.INFO,      "\033[1;34m%s\033[1;0m" % logging.getLevelName(logging.INFO))
    logging.addLevelName(logging.DEBUG,     "\033[1;35m%s\033[1;0m" % logging.getLevelName(logging.DEBUG))

    logger = logging.getLogger(name)
    if debug:
        logger.setLevel(logging.DEBUG)
    else:
        logger.setLevel(logging.INFO)

    if (logger.hasHandlers()):
        logger.handlers.clear()
    logger.addHandler(handler)
    loggers.update(dict(name=logger))

    return logger
