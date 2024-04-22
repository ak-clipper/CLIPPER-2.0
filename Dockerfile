# syntax=docker/dockerfile:1

# Comments are provided throughout this file to help you get started.
# If you need more help, visit the Dockerfile reference guide at
# https://docs.docker.com/go/dockerfile-reference/

# Want to help us make this template better? Share your feedback here: https://forms.gle/ybq9Krt8jtBL3iCk7

FROM continuumio/miniconda3:latest

WORKDIR /app

RUN conda install -y -c conda-forge pycairo && \
 #   conda install -c conda-forge pymol-open-source && \
    conda install --channel conda-forge pygraphviz

# Download dependencies as a separate step to take advantage of Docker's caching.
# Leverage a cache mount to /root/.cache/pip to speed up subsequent builds.
# Leverage a bind mount to requirements.txt to avoid having to copy them into
# into this layer.
COPY requirements.txt ./

RUN --mount=type=cache,target=/root/.cache/pip \
    --mount=type=bind,source=requirements.txt,target=requirements.txt \
    python3 -m pip install -r requirements.txt

COPY clipper/*.* clipper/
COPY clipper/bin/ clipper/bin/
COPY clipper/static/ clipper/static/
COPY clipper/templates/ clipper/templates/
COPY clipper/data/credentials.json clipper/data/

ARG PYTHON_VERSION=3.11
ENV LANG=C.UTF-8 LC_ALL=C.UTF-8
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Expose port
EXPOSE 5000

# Create a non-privileged user that the app will run under.
# See https://docs.docker.com/go/dockerfile-user-best-practices/
ARG UID=10001
RUN adduser \
    --disabled-password \
    --gecos "" \
    --home "/app" \
    --shell "/sbin/nologin" \
    --no-create-home \
    --uid "${UID}" \
   appuser

# Switch to the non-privileged user to run the application.
USER appuser

# Run the application.
#CMD ["python3",  "clipper/app.py"]
