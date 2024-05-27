# syntax=docker/dockerfile:1

FROM continuumio/miniconda3:latest

WORKDIR /clipper

RUN useradd -m -r appuser && \
    chown appuser /app

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

COPY clipper/ clipper/

ARG PYTHON_VERSION=3.11
ENV LANG=C.UTF-8 LC_ALL=C.UTF-8
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Expose port
EXPOSE 5000

# Switch to the non-privileged user to run the application.
# USER appuser

# Run the application.
CMD ["python3",  "clipper/app.py"]
