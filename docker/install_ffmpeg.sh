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


# Exit on error
set -e

# Install ffmpeg and dependencies
install_ffmpeg() {
  mkdir -p ~/ffmpeg_sources
  mkdir -p ~/ffmpeg_build
  mkdir -p ~/bin

  # x264
  cd ~/ffmpeg_sources
  tar xjvf /setup/x264-snapshot-20170202-2245-stable.tar.bz2
  cd x264-snapshot-20170202-2245-stable
  PATH="$HOME/bin:$PATH" ./configure --prefix="$HOME/ffmpeg_build" --bindir="$HOME/bin" --enable-static --disable-opencl
  PATH="$HOME/bin:$PATH" make -j 4
  make install
  make distclean

  # x265
  cd ~/ffmpeg_sources
  tar xzvf /setup/x265_2.2.tar.gz
  cd x265_2.2/build/linux
  PATH="$HOME/bin:$PATH" cmake -G "Unix Makefiles" -DCMAKE_INSTALL_PREFIX="$HOME/ffmpeg_build" -DENABLE_SHARED:bool=off ../../source
  make -j 4
  make install

  # fdk-aac
  cd ~/ffmpeg_sources
  tar xzvf /setup/fdk-aac.tar.gz
  cd fdk-aac*
  autoreconf -fiv
  ./configure --prefix="$HOME/ffmpeg_build" --disable-shared
  make -j 4
  make install
  make distclean

  # vpx
  cd ~/ffmpeg_sources
  tar xzvf /setup/libvpx-1.6.1.tar.gz
  cd libvpx-1.6.1
  PATH="$HOME/bin:$PATH" ./configure --prefix="$HOME/ffmpeg_build" --disable-examples --disable-unit-tests --enable-vp9-highbitdepth
  PATH="$HOME/bin:$PATH" make -j 4
  make install
  make clean

  # ffmpeg
  cd ~/ffmpeg_sources
  tar xjvf /setup/ffmpeg-3.2.2.tar.bz2
  cd ffmpeg-3.2.2
  PATH="$HOME/bin:$PATH" PKG_CONFIG_PATH="$HOME/ffmpeg_build/lib/pkgconfig" ./configure \
    --prefix="$HOME/ffmpeg_build" \
    --pkg-config-flags="--static" \
    --extra-cflags="-I$HOME/ffmpeg_build/include" \
    --extra-ldflags="-L$HOME/ffmpeg_build/lib" \
    --bindir="$HOME/bin" \
    --enable-gpl \
    --enable-libass \
    --enable-libfreetype \
    --enable-libfdk-aac \
    --enable-libx264 \
    --enable-libx265 \
    --enable-libvpx \
    --enable-nonfree
  PATH="$HOME/bin:$PATH" make -j 4
  make install
  make distclean

  hash -r

  echo "MANPATH_MAP $HOME/bin $HOME/ffmpeg_build/share/man" >> ~/.manpath

  cd ~
}

# Install 10-Bit variants of x264 and x265, with ffmpeg10 binary
install_ffmpeg10() {
  cp -al ~/ffmpeg_build ~/ffmpeg_build_10

  # x264 10-Bit
  cd ~/ffmpeg_sources
  cp -al x264-snapshot-20170202-2245-stable x264-snapshot-20170202-2245-stable-10bit
  cd x264-snapshot-20170202-2245-stable-10bit
  make distclean
  PATH="$HOME/bin:$PATH" ./configure --prefix="$HOME/ffmpeg_build_10" --bindir="$HOME/bin" --enable-static --disable-cli --disable-opencl --bit-depth=10
  PATH="$HOME/bin:$PATH" make -j 4
  make install
  make distclean

  # x265
  cd ~/ffmpeg_sources
  cp -al x265_2.2 x265_2.2-10bit
  cd x265_2.2-10bit/build/linux
  PATH="$HOME/bin:$PATH" cmake -G "Unix Makefiles" -DHIGH_BIT_DEPTH=ON -DCMAKE_INSTALL_PREFIX="$HOME/ffmpeg_build_10" -DENABLE_SHARED:bool=off ../../source
  make -j 4
  make install

  # ffmpeg
  cd ~/ffmpeg_sources
  cp -al ffmpeg-3.2.2 ffmpeg-3.2.2-10bit
  cd ffmpeg-3.2.2-10bit
  PATH="$HOME/bin:$PATH" PKG_CONFIG_PATH="$HOME/ffmpeg_build_10/lib/pkgconfig" ./configure \
    --prefix="$HOME/ffmpeg_build_10" \
    --pkg-config-flags="--static" \
    --extra-cflags="-I$HOME/ffmpeg_build_10/include" \
    --extra-ldflags="-L$HOME/ffmpeg_build_10/lib" \
    --bindir="$HOME/bin" \
    --enable-gpl \
    --enable-libass \
    --enable-libfreetype \
    --enable-libfdk-aac \
    --enable-libx264 \
    --enable-libx265 \
    --enable-libvpx \
    --enable-nonfree
  PATH="$HOME/bin:$PATH" make -j 4
  cp "ffmpeg" "$HOME/bin/ffmpeg10"
  make distclean

  hash -r

  echo "MANPATH_MAP $HOME/bin $HOME/ffmpeg_build_10/share/man" >> ~/.manpath

  cd ~
}

# Install ffmpeg
if command -v ffmpeg >/dev/null; then
  echo "ffmpeg already installed, skipping installation"
else
  install_ffmpeg
fi

# Install ffmpeg10
if command -v ffmpeg10 >/dev/null; then
  echo "ffmpeg10 already installed, skipping installation"
else
  install_ffmpeg10
fi

