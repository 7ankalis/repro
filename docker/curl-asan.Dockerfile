# curl built with ASan + UBSan, debug symbols. Network is used ONLY at image build time.
# Build:  docker build -f docker/curl-asan.Dockerfile -t repro/curl-asan:latest .
#         (optional) --build-arg CURL_REF=curl-8_XX_0   to pin a release tag
FROM ubuntu:24.04
ARG CURL_REF=master
ENV DEBIAN_FRONTEND=noninteractive
# libclang-rt-18-dev = the ASan/UBSan runtime libraries. With --no-install-recommends, the `clang` package does
# NOT pull it in, and every -fsanitize link fails ("C compiler cannot create executables").
RUN apt-get update && apt-get install -y --no-install-recommends \
      clang-18 libclang-rt-18-dev llvm-18 make autoconf automake libtool pkg-config git ca-certificates perl \
      python3 libssl-dev zlib1g-dev diffutils patch file xxd \
    && rm -rf /var/lib/apt/lists/*
ENV CC=clang-18 CXX=clang++-18 \
    CFLAGS="-fsanitize=address,undefined -fno-sanitize-recover=undefined -fno-omit-frame-pointer -g -O1" \
    LDFLAGS="-fsanitize=address,undefined" \
    PATH="/usr/lib/llvm-18/bin:${PATH}"
# Fail fast with a clear message if the sanitizer toolchain is broken (llvm-symbolizer comes from llvm-18).
RUN printf 'int main(void){return 0;}\n' > /tmp/t.c && $CC $CFLAGS $LDFLAGS /tmp/t.c -o /tmp/t && /tmp/t \
    && echo "sanitizer toolchain OK"
RUN git clone --depth 1 --branch ${CURL_REF} https://github.com/curl/curl.git /src/curl || \
    (git clone https://github.com/curl/curl.git /src/curl && cd /src/curl && git checkout ${CURL_REF})
WORKDIR /src/curl
RUN autoreconf -fi \
    && (./configure --with-openssl --enable-debug --disable-shared --without-libpsl || (tail -60 config.log; exit 1)) \
    && make -j"$(nproc)" && echo "curl built: $(src/curl --version | head -1)"
RUN mkdir -p /work
WORKDIR /src/curl
