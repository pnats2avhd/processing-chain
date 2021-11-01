#!/usr/bin/env bash
#
# Installer for FFmpeg with dependencies
# ======================================
#
# - ffmpeg (8/10 bit)
# - x264 (8/10 bit)
# - x265 (8/10 bit)
# - fdk-aac
# - vpx (8/10 bit)
#
# https://trac.ffmpeg.org/wiki/CompilationGuide/Ubuntu
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

set -e

# Install ffmpeg and dependencies
install_ffmpeg() {
  mkdir -p "$HOME/ffmpeg_sources"
  mkdir -p "$HOME/ffmpeg_build"
  mkdir -p "$HOME/bin"

  # ffmpeg
  cd "$HOME/ffmpeg_sources"
  wget -q -O ffmpeg44.tar.bz2 https://ffmpeg.org/releases/ffmpeg-4.4.tar.bz2
  tar xjf ffmpeg44.tar.bz2
  cd ffmpeg-4.4
  PATH="$HOME/bin:$PATH" PKG_CONFIG_PATH="$HOME/ffmpeg_build/lib/pkgconfig" ./configure \
    --prefix="$HOME/ffmpeg_build" \
    --pkg-config-flags="--static" \
    --extra-cflags="-I$HOME/ffmpeg_build/include" \
    --extra-ldflags="-L$HOME/ffmpeg_build/lib" \
    --extra-libs="-lpthread -lm" \
    --bindir="$HOME/bin" \
    --enable-gpl \
    --enable-libfdk-aac \
    --enable-libfreetype \
    --enable-libmp3lame \
    --enable-libopus \
    --enable-libvpx \
    --enable-libx264 \
    --enable-libx265 \
    --enable-libaom \
    --enable-nonfree
  PATH="$HOME/bin:$PATH" make -j 4
  make install
  make distclean

  hash -r

  echo "MANPATH_MAP $HOME/bin $HOME/ffmpeg_build/share/man" >> $HOME/.manpath

  cd "$HOME"
}

# Install ffmpeg
if command -v ffmpeg >/dev/null; then
  echo "ffmpeg already installed, skipping installation"
else
  install_ffmpeg
fi
