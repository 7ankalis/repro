# curl built with ASan + UBSan, debug symbols. Network is used ONLY at image build time.
# Build:  docker build -f docker/curl-asan.Dockerfile -t repro/curl-asan:latest --build-arg CURL_REF=curl-8_XX_0  (any release tag) .
FROM ubuntu:24.04
ARG CURL_REF=master
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      clang llvm make autoconf automake libtool pkg-config git ca-certificates perl python3 \
      libssl-dev zlib1g-dev diffutils patch file xxd \
    && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 --branch ${CURL_REF} https://github.com/curl/curl.git /src/curl || \
    (git clone https://github.com/curl/curl.git /src/curl && cd /src/curl && git checkout ${CURL_REF})
WORKDIR /src/curl
ENV CC=clang CXX=clang++ \
    CFLAGS="-fsanitize=address,undefined -fno-sanitize-recover=undefined -fno-omit-frame-pointer -g -O1" \
    LDFLAGS="-fsanitize=address,undefined"
RUN autoreconf -fi && ./configure --with-openssl --enable-debug --disable-shared --without-libpsl \
    && make -j"$(nproc)" && echo "curl built: $(src/curl --version | head -1)"
RUN mkdir -p /work
WORKDIR /src/curl
