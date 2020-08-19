# Docker howto

First, install Docker on your platform.

The build file has only been tested on Ubuntu and macOS hosts, so it might be a bit different on Windows.

## Building

Run  

```
docker build -t processing_chain .
```

on the command line where the Dockerfile is located. In this repository, it is located in the level above this README.md.

The build starts, and it can take a while if you haven't done it before. It will generate an image named `processing_chain`.

## Usage

First, clone an example database:

```
git clone https://github.com/pnats2avhd/example-databases
realpath example-databases
```

Copy this path; we need it to mount it to the Docker image.

Run the following command, and replace the `/path/to/example-databases` with the one on your system that was printed above.

```
docker run -it \
  -v /path/to/example-databases/:/proponent-databases/ processing_chain \
  python3 p00_processAll.py -c /proponent-databases/P2SXM00/P2SXM00.yaml -v
```

This will run all four steps on the short examples database, resulting in ~ 625 MB of video files being written into the databases folder.
