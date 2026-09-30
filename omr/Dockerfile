# Audiveris OMR, headless, wrapped by a tiny stdlib HTTP server (omr_server.py).
FROM ubuntu:noble-20260911

ARG AUDIVERIS_VERSION=5.11.0
ARG AUDIVERIS_SHA256=f20113aaa33b3149ec8d6a09b2a7963360e65fafd92d69389987a85bbc3ec7a3

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/tessdata

# Official release .deb (ships its own JRE via jpackage), checksum-verified.
# tesseract-ocr-eng only provides tessdata (Audiveris bundles libtesseract via JavaCPP).
# python3 runs the HTTP wrapper. libgtk-3 is loaded via JNA at startup (HiDPI probe)
# even in batch mode, but the .deb does not declare it.
# The package's postinst only registers a desktop menu entry + MIME type via xdg-utils,
# which exits 3 on a minimal image with no menu dirs; pre-create them so it installs cleanly.
RUN mkdir -p /etc/xdg/menus /usr/share/applications /usr/share/desktop-directories /usr/share/mime/packages \
 && apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl \
 && curl -fsSL -o /tmp/audiveris.deb \
      https://github.com/Audiveris/audiveris/releases/download/${AUDIVERIS_VERSION}/Audiveris-${AUDIVERIS_VERSION}-ubuntu24.04-x86_64.deb \
 && echo "${AUDIVERIS_SHA256}  /tmp/audiveris.deb" | sha256sum -c - \
 && apt-get install -y --no-install-recommends \
      /tmp/audiveris.deb tesseract-ocr-eng libgtk-3-0t64 python3 fontconfig fonts-dejavu-core \
 && apt-get purge -y curl && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/* /tmp/audiveris.deb

RUN useradd --create-home --uid 10001 omr \
 && mkdir -p /data && chown omr:omr /data
COPY --chown=omr:omr omr_server.py /opt/omr_server.py

USER omr
WORKDIR /home/omr
EXPOSE 8090
CMD ["python3", "/opt/omr_server.py"]
