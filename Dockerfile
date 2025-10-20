FROM ubuntu:20.04

ARG DEBIAN_FRONTEND="noninteractive"

RUN apt-get update -qq && apt-get install -qq -y \
  autoconf \
  automake \
  build-essential \
  cmake \
  libfreetype6-dev \
  libtool \
  pkg-config \
  texinfo \
  wget \
  yasm \
  nasm \
  zlib1g-dev \
  libnuma-dev \
  git \
  libx264-dev \
  libx265-dev \
  libopus-dev \
  libmp3lame-dev \
  libfdk-aac-dev \
  libvpx-dev \
  python3-setuptools \
  libunistring-dev libaom-dev libdav1d-dev \
  python3-pip \
  python3-venv \
  && rm -rf /var/lib/apt/lists/*

COPY ./docker/install_ffmpeg.sh /install_ffmpeg.sh
RUN chmod +x /install_ffmpeg.sh && \
  /install_ffmpeg.sh && \
  cp /root/bin/ffmpeg /usr/local/bin/ffmpeg && \
  cp /root/bin/ffprobe /usr/local/bin/ffprobe

COPY . /processing-chain

WORKDIR /processing-chain
RUN pip3 install --no-cache-dir poetry && \
  poetry config virtualenvs.create false && \
  poetry install --no-interaction --no-ansi

ENV NAME pnats_processing_chain
RUN mkdir /proponent-databases

ENTRYPOINT ["poetry", "run", "python3"]
