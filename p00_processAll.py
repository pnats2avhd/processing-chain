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

import lib.parse_args as parse_args
import lib.check_requirements as check_requirements


def run(cli_args):
    import p01_generateSegments as p01
    import p02_generateMetadata as p02
    import p03_generateAvPvs as p03
    import p04_generateCpvs as p04
    test_config = None

    if "1" in cli_args.scripts_to_run or cli_args.scripts_to_run == 'all':
        print("Running script 1")
        print(parse_args.parse_args(name="p01_generateSegments", script=1))
        test_config = p01.run(cli_args=parse_args.parse_args(name="p01_generateSegments", script=1))
    if "2" in cli_args.scripts_to_run or cli_args.scripts_to_run == 'all':
        print("Running script 2")
        print(parse_args.parse_args(name="p02_generateMetadata", script=2))
        test_config = p02.run(cli_args=parse_args.parse_args(name="p02_generateMetadata", script=2), test_config=test_config)
    if "3" in cli_args.scripts_to_run or cli_args.scripts_to_run == 'all':
        print("Running script 3")
        print(parse_args.parse_args(name="p03_generateAvPvs", script=3))
        test_config = p03.run(cli_args=parse_args.parse_args(name="p03_generateAvPvs", script=3), test_config=test_config)
    if "4" in cli_args.scripts_to_run or cli_args.scripts_to_run == 'all':
        print("Running script 4")
        p04.run(cli_args=parse_args.parse_args(name="p04_generateCpvs", script=4), test_config=test_config)


def main():
    cli_args = parse_args.parse_args(os.path.basename(__file__))

    check_requirements.check_requirements(skip=cli_args.skip_requirements)

    run(cli_args)


if __name__ == '__main__':
    main()
