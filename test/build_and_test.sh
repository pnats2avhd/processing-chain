#!/usr/bin/env bash

set -e

cd "$(dirname $"0")/.." || exit

git -C example-databases pull 2> /dev/null || git clone --depth 1 https://github.com/pnats2avhd/example-databases.git

docker build -t processing_chain_test .

docker run --rm -it \
  -v "$(pwd)/example-databases/:/proponent-databases/" processing_chain_test \
  python3 p00_processAll.py -c /proponent-databases/P2SXM00/P2SXM00.yaml -v

docker image rm processing_chain_test
