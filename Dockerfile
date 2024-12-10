FROM nvidia/cuda:11.6.1-cudnn8-runtime-ubuntu20.04
WORKDIR /graphormer
COPY . .
RUN apt-get update
RUN apt-get install -y python3.9
RUN apt-get install -y python3-pip
RUN apt-get install -y python3.9-dev
RUN apt-get install -y ninja-build
RUN ./install.sh
#download weights
RUN distributional_graphormer\checkpoints\download_weights.sh
ENTRYPOINT ["tail", "-f", "/dev/null"]