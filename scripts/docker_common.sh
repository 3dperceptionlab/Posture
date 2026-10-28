#!/usr/bin/env bash
if [[ -f /usr/local/bin/docker_wrapper.sh ]] && sudo -n -l 2>/dev/null | grep -q '/usr/local/bin/docker_wrapper.sh'; then
  docker_cmd() { sudo -n /usr/local/bin/docker_wrapper.sh "$@"; }
else
  docker_cmd() { command docker "$@"; }
fi

vision_directory() {
  local posture_dir_value=${POSTURE_VISION_DIR:-}
  if [[ -z "$posture_dir_value" && -f .env ]]; then
    posture_dir_value=$(sed -n 's/^POSTURE_VISION_DIR=//p' .env)
  fi
  if [[ -z "$posture_dir_value" ]]; then
    if [[ "${POSTURE_PROJECT:-posture}" == posture ]]; then posture_dir_value=./data/vision;
    else posture_dir_value="./data/${POSTURE_PROJECT}/vision"; fi
  fi
  realpath -m -- "$posture_dir_value"
}
