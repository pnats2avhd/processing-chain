# Stage 1: Builder
FROM ubuntu:24.04 AS builder

ARG DEBIAN_FRONTEND="noninteractive"

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
  unzip \
  libunistring-dev \
  ninja-build \
  meson \
  libffi-dev \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /nvenc
RUN git clone -b sdk/12.1 https://github.com/FFmpeg/nv-codec-headers.git
RUN cd nv-codec-headers && make install

WORKDIR /vmaf
RUN wget -q -O v3.0.0.tar.gz https://github.com/Netflix/vmaf/archive/refs/tags/v3.0.0.tar.gz
RUN tar xvf v3.0.0.tar.gz
WORKDIR /vmaf/vmaf-3.0.0/libvmaf
RUN meson build --buildtype release
RUN ninja -vC build
RUN ninja -vC build install

WORKDIR /ffmpeg_sources
RUN git clone --depth 1 https://aomedia.googlesource.com/aom
RUN mkdir -p aom_build
WORKDIR /ffmpeg_sources/aom_build
RUN cmake -G "Unix Makefiles" -DCMAKE_INSTALL_PREFIX="/usr/local" -DENABLE_SHARED=off -DENABLE_NASM=on ../aom
RUN make -j$(nproc) && make install

COPY ./docker/install_ffmpeg.sh /install_ffmpeg.sh
RUN chmod +x /install_ffmpeg.sh && /install_ffmpeg.sh 
RUN cp /root/bin/ffmpeg /usr/local/bin/ffmpeg && \
  cp /root/bin/ffprobe /usr/local/bin/ffprobe


# Stage 2: Final Image
FROM ubuntu:24.04

ARG DEBIAN_FRONTEND="noninteractive"
ENV NVIDIA_DRIVER_CAPABILITIES=all
ENV NVIDIA_VISIBLE_DEVICES=all

RUN apt update -qq && apt install -qq -y \
  libc6 \
  libnuma1 \
  libx264-dev \
  libx265-dev \
  libopus-dev \
  libmp3lame-dev \
  libfdk-aac-dev \
  libvpx-dev \
  libunistring-dev \
  libfreetype6-dev \
  git \
  unzip \
  wget \
  curl \
  && rm -rf /var/lib/apt/lists/*

COPY --from=builder /usr/local/bin/ffmpeg /usr/local/bin/ffmpeg
COPY --from=builder /usr/local/bin/ffprobe /usr/local/bin/ffprobe
COPY --from=builder /usr/local/lib/ /usr/local/lib/
COPY --from=builder /usr/local /usr/local

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
RUN uv add -r requirements_used.txt
RUN uv sync
RUN uv lock

ENV NAME=pnats_processing_chain
USER root
RUN mkdir /proponent-databases && chown -R 1000:1000 /proponent-databases
COPY . /processing-chain
RUN chown -R 1000:1000 /processing-chain
RUN git config --global --add safe.directory /processing-chain
USER 1000
