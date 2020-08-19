FROM amd64/ubuntu:16.04
WORKDIR /setup

RUN useradd -g 100 -u 1000 -ms /bin/bash ubuntu

RUN apt-get update -qq && apt-get install -qq -y \
  autoconf \
  automake \
  build-essential \
  libass-dev \
  libfreetype6-dev \
  libtool \
  pkg-config \
  texinfo \
  zlib1g-dev \
  yasm \
  libssl-dev \
  cmake \
  mercurial \
  wget \
  software-properties-common \
  libffi6 \
  libffi-dev \
  git \
  python-setuptools python3-setuptools \
  python-pip python3-pip \
  python-numpy python3-numpy \
  python-scipy python3-scipy \
  python-matplotlib python3-matplotlib \
  && rm -rf /var/lib/apt/lists/*

COPY ./docker/* /setup/
RUN chmod +x ./install_ffmpeg.sh

USER ubuntu
RUN ./install_ffmpeg.sh
USER root

COPY ./requirements.txt /setup/requirements.txt
RUN pip3 install --upgrade --no-cache-dir -r requirements.txt

COPY . /processing-chain
RUN chown -R ubuntu:users /processing-chain
ENV NAME pnats_processing_chain
ENV PATH="/root/bin:/root/.local/bin:/home/ubuntu/bin/:$PATH" 
RUN mkdir /proponent-databases
RUN chown -R ubuntu:users /proponent-databases

USER ubuntu

WORKDIR /processing-chain
