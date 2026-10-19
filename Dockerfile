# HyperDog Gazebo-szimuláció javításokkal, böngészős képpel (noVNC) és vezérlőpulttal.
# Build:  docker build -t hiperkutya-gazebo .
# Futás:  docker run -d --name hiperkutya -p 6080:6080 -p 6081:6081 hiperkutya-gazebo
# Kép:    http://localhost:6080/vnc.html?autoconnect=1&resize=scale
# Pult:   http://localhost:6081
FROM osrf/ros:foxy-desktop

# A Foxy már nem támogatott: a régi image ROS apt-kulcsa lejárt, friss kulcs kell
RUN rm -f /etc/apt/sources.list.d/ros2*.list /usr/share/keyrings/ros2-latest-archive-keyring.gpg; \
    curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key -o /usr/share/keyrings/ros-archive-keyring.gpg && \
    echo "deb [signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] http://packages.ros.org/ros2/ubuntu focal main" > /etc/apt/sources.list.d/ros2.list && \
    apt-get update && apt-get install -y --no-install-recommends \
      ros-foxy-gazebo-ros-pkgs ros-foxy-gazebo-ros2-control ros-foxy-ros2-control \
      ros-foxy-ros2-controllers ros-foxy-xacro ros-foxy-joy git \
      xvfb x11vnc novnc websockify fluxbox && \
    rm -rf /var/lib/apt/lists/*

# Az eredeti repó egy rögzített commitja, hogy a javítások biztosan illeszkedjenek
ARG UPSTREAM_COMMIT=604f8362f3e09d3b3246abac832ae82323ffa97d
COPY fixes/apply_fixes.sh /opt/hiperkutya/
WORKDIR /ws/src
RUN git init -q hyperdog_ros2 && cd hyperdog_ros2 && \
    git fetch -q --depth 1 https://github.com/NDHANA94/hyperdog_ros2.git $UPSTREAM_COMMIT && \
    git checkout -q FETCH_HEAD && \
    bash /opt/hiperkutya/apply_fixes.sh . && \
    cd .. && mv hyperdog_ros2/hyperdog_* . && rm -rf hyperdog_ros2
WORKDIR /ws
RUN . /opt/ros/foxy/setup.sh && colcon build 2>&1 | tail -20

COPY tools/pd_bridge.py tools/hd_web.py docker/run.sh /opt/hiperkutya/
ENV ROS_DOMAIN_ID=77
CMD ["bash", "/opt/hiperkutya/run.sh"]
