#!/bin/bash
# Runs a command in the image's omphjc environment, with the variables its
# packages set on activation.
source /opt/conda/etc/profile.d/conda.sh
conda activate omphjc
exec "$@"
