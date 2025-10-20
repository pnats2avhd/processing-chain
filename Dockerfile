FROM ubuntu:24.04

ARG DEBIAN_FRONTEND="noninteractive"
ENV NVIDIA_DRIVER_CAPABILITIES=all
ENV NVIDIA_VISIBLE_DEVICES=all

RUN apt update -qq && apt install -qq -y \
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
  libc6 \
  libc6-dev \
  unzip \
  libnuma1 \
  libnuma-dev \
  libunistring-dev \ 
  ninja-build meson \
  libffi-dev \
  && rm -rf /var/lib/apt/lists/*

RUN mkdir /nvenc
WORKDIR /nvenc
RUN git clone -b sdk/12.1 https://github.com/FFmpeg/nv-codec-headers.git
RUN cd nv-codec-headers && make install

RUN mkdir /vmaf
WORKDIR /vmaf
RUN wget -q -O v3.0.0.tar.gz https://github.com/Netflix/vmaf/archive/refs/tags/v3.0.0.tar.gz
RUN tar xvf v3.0.0.tar.gz
WORKDIR /vmaf/vmaf-3.0.0/libvmaf
RUN meson build --buildtype release
RUN ninja -vC build
RUN ninja -vC build install

RUN mkdir /ffmpeg_sources
WORKDIR /ffmpeg_sources
RUN git -C aom pull 2> /dev/null || git clone --depth 1 https://aomedia.googlesource.com/aom
RUN mkdir -p aom_build
WORKDIR /ffmpeg_sources/aom_build
RUN PATH="$HOME/bin:$PATH" cmake -G "Unix Makefiles" -DCMAKE_INSTALL_PREFIX="$HOME/ffmpeg_build" -DENABLE_SHARED=off -DENABLE_NASM=on ../aom 
RUN PATH="$HOME/bin:$PATH" make -j 8
RUN make install

COPY ./docker/install_ffmpeg.sh /install_ffmpeg.sh
RUN chmod +x /install_ffmpeg.sh && \
  /install_ffmpeg.sh && \
  cp /root/bin/ffmpeg /usr/local/bin/ffmpeg && \
  cp /root/bin/ffprobe /usr/local/bin/ffprobe
ENV LD_LIBRARY_PATH="$LD_LIBRARY_PATH:/usr/local/lib/x86_64-linux-gnu/"

RUN mkdir /uvsource
WORKDIR /uvsource
RUN wget -qO- https://astral.sh/uv/0.5.29/install.sh | env UV_INSTALL_DIR="/uvsource" sh
ENV PATH="$PATH:/uvsource"

COPY requirements.txt /processing-chain/requirements_used.txt
WORKDIR /processing-chain
RUN chown -R 1000:1000 /processing-chain
USER 1000

RUN uv python install 3.11
RUN uv init
# RUN uv pip sync requirements_used.txt
RUN uv add -r requirements_used.txt
RUN uv sync
RUN uv lock

ENV NAME=pnats_processing_chain
USER root
RUN mkdir /proponent-databases
RUN chown -R 1000:1000 /proponent-databases
COPY . /processing-chain
RUN chown -R 1000:1000 /processing-chain
RUN git config --global --add safe.directory /processing-chain
USER 1000
