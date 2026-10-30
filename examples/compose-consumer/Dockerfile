# syntax=docker/dockerfile:1
#
# A consumer's image of vendorfake: installed from the release's source
# archive on GitHub, so a machine with no git access, no registry login and
# no token can build it. One image, every installed vendor; VENDORFAKE_VENDOR
# chooses at run time, the same as the repository's own Dockerfile.
#
# VENDORFAKE_REF is the one place to bump: compose.yaml lists the arg with
# no value, so compose passes it only when the shell sets it and otherwise
# this default governs. A tag normally. To consume a
# branch before its tag, `refs/heads/<branch>` or a commit sha also resolve
# (https://github.com/konyklabs/vendorfake/archive/<ref>.tar.gz); then
# `vendorfake.__version__` reports the previous release (docs/start/install.md,
# "Pinning a commit instead of a tag"), and `docker compose build --no-cache`
# is needed because the layer below caches on this string.
FROM python:3.13-slim-bookworm

# release-please rewrites the version inside this block on every release
# (generic updater, block annotation). A Dockerfile has no inline comments,
# so the block form is used; BuildKit was observed to strip a trailing
# `# ...` from an ARG value, but nothing here relies on that.
# x-release-please-start-version
ARG VENDORFAKE_REF=v0.11.0
# x-release-please-end

RUN groupadd --system --gid 10001 vendorfake \
 && useradd --system --uid 10001 --gid vendorfake --home-dir /home/vendorfake --create-home vendorfake

# [serve] carries fastapi and uvicorn, which only `vendorfake serve` needs
# (the in-process bindings never import them). pip builds the sdist in an
# isolated environment, so hatchling comes from PyPI at build time.
RUN pip install --no-cache-dir "vendorfake[serve] @ https://github.com/konyklabs/vendorfake/archive/${VENDORFAKE_REF}.tar.gz"

# Loopback is the CLI's default; inside a container it would make the port
# unreachable from the host, so this is the one place the bind is widened.
ENV PYTHONUNBUFFERED=1 \
    VENDORFAKE_HOST=0.0.0.0 \
    VENDORFAKE_PORT=8080

USER vendorfake
WORKDIR /home/vendorfake
EXPOSE 8080

# 200 only once the unit has constructed and hydrated its seed; the one route
# VENDORFAKE_CONTROL_TOKEN never guards; follows VENDORFAKE_CONTROL_PORT when
# the control plane has a listener of its own. Verbatim from the repository's
# Dockerfile, which tools/verify_image_build.sh holds to this exact command.
HEALTHCHECK --interval=5s --timeout=3s --start-period=5s --retries=5 \
  CMD ["python", "-c", "import os, sys, urllib.request; port = os.environ.get('VENDORFAKE_CONTROL_PORT') or os.environ.get('VENDORFAKE_PORT', '8080'); sys.exit(0 if urllib.request.urlopen(f'http://127.0.0.1:{port}/__unit/health', timeout=2).status == 200 else 1)"]

ENTRYPOINT ["vendorfake"]
CMD ["serve"]
