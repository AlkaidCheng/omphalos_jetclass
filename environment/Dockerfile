# The image omphjc runs in: the environment of environment/environment.yml,
# MadGraph and omphjc. Build it from the repository root:
#
#   docker build -f environment/Dockerfile \
#       --build-arg OMPHJC_VERSION=<version> -t omphjc .

FROM condaforge/miniforge3:latest

# MadGraph is a tarball with no resolver behind it, so it is the one program
# whose version is named, with the SHA-256 of its archive; both change by hand.
# Launchpad (https://launchpad.net/mg5amcnlo) offers only the newest release of
# a series, so the release comes from the tag archive of the upstream
# repository, which stays at its URL.
ARG MG5_VERSION=3.8.1
ARG MG5_URL=https://github.com/mg5amcnlo/mg5amcnlo/archive/refs/tags/v${MG5_VERSION}.tar.gz
# The SHA-256 of that archive, read on 2026-11-10.
ARG MG5_SHA256=b8cc4ce99ac9d614c32298bcb587d50e15b1bad424e569ab49c48a54ba5a1612
# The version setuptools-scm would read from the git history, which the build
# context leaves out.
ARG OMPHJC_VERSION=0.0.0

# MadGraph builds its libraries with `ar` and `ranlib` called by name
# (Template/LO/Source/.make_opts), while conda-forge's compilers provide them
# only under target-prefixed names, and the base image has no binutils.
RUN apt-get update \
    && apt-get install --no-install-recommends --yes binutils \
    && rm -rf /var/lib/apt/lists/*

COPY environment/environment.yml /opt/omphjc/environment.yml
RUN conda env create --name omphjc --file /opt/omphjc/environment.yml \
    && conda clean --all --yes

RUN wget --quiet --output-document=/tmp/mg5.tar.gz "${MG5_URL}" \
    && echo "${MG5_SHA256}  /tmp/mg5.tar.gz" | sha256sum --check --strict \
    && mkdir /opt/MG5_aMC \
    && tar --extract --gzip --file=/tmp/mg5.tar.gz --directory=/opt/MG5_aMC \
        --strip-components=1 \
    && rm /tmp/mg5.tar.gz
# MadGraph asks before installing an update it finds at start-up, which a run
# without a terminal cannot answer, and opens a browser on a run's status page.
RUN cp /opt/MG5_aMC/input/.mg5_configuration_default.txt \
        /opt/MG5_aMC/input/mg5_configuration.txt \
    && printf '%s\n' "auto_update = 0" "automatic_html_opening = False" \
        >> /opt/MG5_aMC/input/mg5_configuration.txt

ENV PATH=/opt/MG5_aMC/bin:/opt/conda/envs/omphjc/bin:${PATH}

COPY . /opt/omphjc/source
RUN SETUPTOOLS_SCM_PRETEND_VERSION_FOR_OMPHJC="${OMPHJC_VERSION}" \
        conda run --name omphjc pip install --no-cache-dir /opt/omphjc/source \
    && conda run --name omphjc python \
        /opt/omphjc/source/environment/check_requirements.py
RUN { conda list --name omphjc; \
      echo "# MadGraph5_aMC@NLO ${MG5_VERSION} from ${MG5_URL}"; \
    } > /opt/omphjc/packages.txt

WORKDIR /work
ENTRYPOINT ["tini", "--", "/opt/omphjc/source/environment/entrypoint.sh"]
CMD ["bash"]
