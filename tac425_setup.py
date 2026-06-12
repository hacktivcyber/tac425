#!/usr/bin/env python3
"""
TAC425 installer / lab generator.

This version provisions:
- DNS zone-transfer lab
- wordlists (rockyou + SecLists)
- bkimminich/juice-shop
- jeroenwillemsen/wrongsecrets
- webgoat/webgoat
- Zero-Health (cloned from GitHub and run locally)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import textwrap
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
WORK_DIR = Path.home() / "TAC425"
EXTERNAL_DIR = WORK_DIR / "external"
DNS_DIR = EXTERNAL_DIR / "dns_zone"
ZERO_HEALTH_DIR = EXTERNAL_DIR / "Zero-Health"
WORDLISTS_LINK = WORK_DIR / "wordlists"
CONTAINER_SCRIPTS_DIR = WORK_DIR / "container_scripts"
VENV_DIR = WORK_DIR / ".venv"
LOG_FILE = WORK_DIR / "install.log"
SUMMARY_FILE = WORK_DIR / "install_summary.txt"
STATE_FILE = WORK_DIR / "install_state.json"

for p in (WORK_DIR, EXTERNAL_DIR, CONTAINER_SCRIPTS_DIR):
    p.mkdir(parents=True, exist_ok=True)


def bootstrap_venv() -> None:
    if sys.prefix != sys.base_prefix:
        return

    req_file = SCRIPT_DIR / "requirements.txt"
    venv_python = VENV_DIR / "bin" / "python"

    if not VENV_DIR.exists():
        try:
            subprocess.run([sys.executable, "-m", "venv", str(VENV_DIR)], check=True)
        except subprocess.CalledProcessError:
            subprocess.run(["sudo", "apt-get", "update"], check=True)
            subprocess.run(["sudo", "apt-get", "install", "-y", "python3-venv"], check=True)
            subprocess.run([sys.executable, "-m", "venv", str(VENV_DIR)], check=True)

    if req_file.exists():
        subprocess.run([str(VENV_DIR / "bin" / "pip"), "install", "-r", str(req_file)], check=True)

    os.execv(str(venv_python), [str(venv_python), *sys.argv])


bootstrap_venv()

if "TAC425_INSTALL_START" not in os.environ:
    os.environ["TAC425_INSTALL_START"] = str(time.time())
INSTALL_START_TIME = float(os.environ["TAC425_INSTALL_START"])

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)


def log(msg: str) -> None:
    print(msg)
    logging.info(msg)


def tee_run(cmd: list[str], *, cwd: Path | None = None) -> int:
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        print(line, end="")
        logging.info(line.rstrip("\n"))
    return proc.wait()


def run(cmd: list[str], step: str, *, cwd: Path | None = None) -> None:
    log(f"[*] {step}: {' '.join(cmd)}")
    rc = tee_run(cmd, cwd=cwd)
    if rc != 0:
        raise RuntimeError(f"{step} failed with exit code {rc}")
    log(f"[+] {step} complete")


def run_retry(cmd: list[str], step: str, *, cwd: Path | None = None, retries: int = 3, delay: int = 5) -> None:
    for attempt in range(1, retries + 1):
        try:
            log(f"[*] {step} (attempt {attempt}/{retries}): {' '.join(cmd)}")
            rc = tee_run(cmd, cwd=cwd)
            if rc != 0:
                raise RuntimeError(f"exit code {rc}")
            log(f"[+] {step} complete")
            return
        except Exception as exc:
            if attempt < retries:
                log(f"[!] {step} failed on attempt {attempt}/{retries}: {exc}")
                log(f"[*] Retrying in {delay}s...")
                time.sleep(delay)
                delay *= 2
            else:
                raise RuntimeError(f"{step} failed after {retries} attempts: {exc}") from exc


def can_run(cmd: list[str]) -> bool:
    try:
        return subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    except FileNotFoundError:
        return False


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            return {}
    return {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True))


def format_elapsed_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def ensure_host_tools() -> None:
    missing: list[str] = []
    tool_map = {
        "git": "git",
        "curl": "curl",
        "lsof": "lsof",
        "dig": "dnsutils",
        "zip": "zip",
        "unzip": "unzip",
    }
    for cmd, pkg in tool_map.items():
        if shutil.which(cmd) is None:
            missing.append(pkg)

    if not missing:
        log("[=] Host tools already present")
        return

    run(["sudo", "apt-get", "update"], "apt-get update (host tools)")
    run(["sudo", "apt-get", "install", "-y", *sorted(set(missing))], "Install host tools")



def ensure_wordlists() -> None:
    rockyou_txt = Path("/usr/share/wordlists/rockyou.txt")
    rockyou_gz = Path("/usr/share/wordlists/rockyou.txt.gz")
    seclists_dir = Path("/usr/share/wordlists/SecLists")

    if not rockyou_txt.exists():
        if rockyou_gz.exists():
            run(["sudo", "gzip", "-d", str(rockyou_gz)], "Unzip rockyou")
        else:
            run(["sudo", "apt-get", "update"], "apt-get update (wordlists)")
            run(["sudo", "apt-get", "install", "-y", "wordlists"], "Install wordlists")
            if rockyou_gz.exists():
                run(["sudo", "gzip", "-d", str(rockyou_gz)], "Unzip rockyou")

    if not seclists_dir.exists():
        run(["sudo", "git", "clone", "https://github.com/danielmiessler/SecLists.git", str(seclists_dir)], "Clone SecLists")

    if WORDLISTS_LINK.is_symlink():
        if WORDLISTS_LINK.resolve() != Path("/usr/share/wordlists"):
            WORDLISTS_LINK.unlink()
    elif WORDLISTS_LINK.exists():
        if WORDLISTS_LINK.is_dir():
            shutil.rmtree(WORDLISTS_LINK)
        else:
            WORDLISTS_LINK.unlink()
    if not WORDLISTS_LINK.exists():
        WORDLISTS_LINK.symlink_to(Path("/usr/share/wordlists"))

    log("[+] Wordlists ready")


def create_wordlist_symlink() -> None:
    if not WORDLISTS_LINK.exists():
        WORDLISTS_LINK.symlink_to(Path("/usr/share/wordlists"))
    log(f"[+] Wordlist symlink ready: {WORDLISTS_LINK} -> /usr/share/wordlists")


def ensure_docker() -> tuple[list[str], str]:
    if shutil.which("docker") is None:
        log("[!] Docker not found; installing Docker Engine")
        run(["sudo", "apt-get", "update"], "apt-get update")
        run(["sudo", "DEBIAN_FRONTEND=noninteractive", "apt-get", "install", "-y", "docker.io"], "Install Docker")
        run(["sudo", "apt-get", "install", "-y", "docker-compose"], "Install Docker Compose")
        run(["sudo", "systemctl", "enable", "--now", "docker"], "Enable and start Docker")

    docker_cmd = ["docker"]
    if not (can_run(["docker", "--version"]) and can_run(["docker", "info"])):
        if can_run(["sudo", "docker", "--version"]) and can_run(["sudo", "docker", "info"]):
            docker_cmd = ["sudo", "docker"]
        else:
            raise RuntimeError("Docker installed but daemon is unavailable")

    compose_cmd = "docker-compose" if shutil.which("docker-compose") else "docker compose"
    if compose_cmd == "docker compose" and not can_run(docker_cmd + ["compose", "version"]):
        raise RuntimeError("Docker Compose not found")

    user = os.getenv("USER", "").strip()
    if user:
        try:
            groups = subprocess.check_output(["id", "-nG", user], text=True).split()
        except Exception:
            groups = []
        if "docker" not in groups:
            run(["sudo", "usermod", "-aG", "docker", user], "Add user to docker group")
            log("[!] Log out and back in once after install so Docker works without sudo")

    run(docker_cmd + ["--version"], "Check Docker")
    if compose_cmd == "docker-compose":
        run(["docker-compose", "--version"], "Check Docker Compose")
    else:
        run(docker_cmd + ["compose", "version"], "Check Docker Compose")

    return docker_cmd, compose_cmd


def ensure_zero_health_repo() -> None:
    if not ZERO_HEALTH_DIR.exists():
        run_retry(["git", "clone", "https://github.com/aligorithm/Zero-Health.git", str(ZERO_HEALTH_DIR)], "Clone Zero-Health")
    else:
        log("[=] Zero-Health repository already present")

    env_example = ZERO_HEALTH_DIR / ".env.example"
    env_file = ZERO_HEALTH_DIR / ".env"
    if env_example.exists():
        env_text = env_example.read_text()
        replacements = {
            "LLM_PROVIDER": "openai",
            "LLM_API_KEY": "sk-placeholder",
            "LLM_MODEL": "gpt-4o-mini",
        }
        for key, value in replacements.items():
            lines = env_text.splitlines()
            changed = False
            new_lines = []
            for line in lines:
                if line.startswith(f"{key}="):
                    new_lines.append(f"{key}={value}")
                    changed = True
                else:
                    new_lines.append(line)
            if not changed:
                new_lines.append(f"{key}={value}")
            env_text = "\n".join(new_lines)
        env_file.write_text(env_text + "\n")
        log("[+] Wrote Zero-Health .env")


APP_SPECS = [
    {
        "name": "dns_zone",
        "label": "DNS Zone Transfer",
        "kind": "dns",
        "image": "tac425/dns_zone:latest",
        "host_port": 53,
        "container_port": 53,
        "zone": "tac425.net",
    },
    {
        "name": "juice_shop",
        "label": "Juice Shop",
        "kind": "image",
        "image": "bkimminich/juice-shop",
        "host_port": 3000,
        "container_port": 3000,
        "path": "/",
    },
    {
        "name": "wrongsecrets",
        "label": "WrongSecrets",
        "kind": "image",
        "image": "jeroenwillemsen/wrongsecrets:latest-no-vault",
        "host_port": 8080,
        "container_port": 8080,
        "path": "/",
    },
    {
        "name": "webgoat",
        "label": "WebGoat",
        "kind": "image",
        "image": "webgoat/webgoat",
        "host_port": 8888,
        "container_port": 8080,
        "path": "/WebGoat",
    },
    {
        "name": "zero_health",
        "label": "Zero Health",
        "kind": "repo",
        "repo_dir": ZERO_HEALTH_DIR,
        "host_port": 5000,
        "path": "/",
    },
]


def build_or_pull_apps(docker_cmd: list[str]) -> None:
    state = load_state()
    for app in APP_SPECS:
        if state.get(app["name"]):
            log(f"[=] {app['name']} already prepared")
            continue

        if app["kind"] == "image":
            run_retry(docker_cmd + ["pull", app["image"]], f"Pull {app['name']}")
        elif app["kind"] == "dns":
            dns_dir = generate_dns_assets()
            run_retry(docker_cmd + ["build", "-t", app["image"], str(dns_dir)], f"Build {app['name']}")
        else:
            ensure_zero_health_repo()

        state[app["name"]] = True
        save_state(state)


def generate_dns_assets() -> None:
    """
    Create the DNS zone-transfer lab assets used by the installer.
    """
    dns_dir = DNS_DIR
    dns_dir.mkdir(parents=True, exist_ok=True)

    dockerfile = dns_dir / "Dockerfile"
    named_conf = dns_dir / "named.conf"
    named_local = dns_dir / "named.conf.local"
    zone_file = dns_dir / "db.tac425.net"

    if not dockerfile.exists():
        dockerfile.write_text(textwrap.dedent("""\
            FROM ubuntu:22.04
            ENV DEBIAN_FRONTEND=noninteractive
            RUN apt-get update && apt-get install -y bind9 bind9utils bind9-dnsutils && rm -rf /var/lib/apt/lists/*
            COPY named.conf /etc/bind/named.conf
            COPY named.conf.local /etc/bind/named.conf.local
            COPY db.tac425.net /etc/bind/db.tac425.net
            EXPOSE 53/tcp
            EXPOSE 53/udp
            CMD ["named", "-g", "-c", "/etc/bind/named.conf"]
        """))

    if not named_conf.exists():
        named_conf.write_text(textwrap.dedent("""\
            options {
                directory "/var/cache/bind";
                recursion yes;
                allow-query { any; };
                listen-on { any; };
                listen-on-v6 { any; };
                dnssec-validation no;
            };
        """))

    if not named_local.exists():
        named_local.write_text(textwrap.dedent("""\
            zone "tac425.net" {
                type master;
                file "/etc/bind/db.tac425.net";
                allow-transfer { any; };
            };
        """))

    if not zone_file.exists():
        zone_file.write_text(textwrap.dedent("""\
            $TTL 604800
            @   IN  SOA ns.tac425.net. admin.tac425.net. (
                    1
                    604800
                    86400
                    2419200
                    604800 )

            @       IN  NS  ns.tac425.net.
            ns      IN  A   127.0.0.1
            www     IN  A   127.0.0.1
            dev     IN  A   127.0.0.1
            hint    IN  TXT "Try a zone transfer"
        """))

    log("[+] DNS assets ready")
    return dns_dir

def start_script_text(app: dict, compose_cmd: str) -> str:
    if app["kind"] == "image":
        return textwrap.dedent(f"""\
            #!/usr/bin/env bash
            set -euo pipefail
            docker rm -f {app['name']} >/dev/null 2>&1 || true
            docker run -d --name {app['name']} --restart unless-stopped -p 127.0.0.1:{app['host_port']}:{app['container_port']} {app['image']}
            echo "[+] {app['label']} available at http://127.0.0.1:{app['host_port']}{app['path']}"
        """)

    elif app["kind"] == "dns":
        return textwrap.dedent(f"""\
            #!/usr/bin/env bash
            set -euo pipefail
            docker rm -f {app['name']} >/dev/null 2>&1 || true
            docker run -d --name {app['name']} --restart unless-stopped \
              -p 127.0.0.1:{app['host_port']}:53/tcp \
              -p 127.0.0.1:{app['host_port']}:53/udp \
              {app['image']}
            echo "[+] {app['label']} available for dig at 127.0.0.1:{app['host_port']} ({app['zone']})"
        """)

    else:
        return textwrap.dedent(f"""\
            #!/usr/bin/env bash
            set -euo pipefail
            cd "{app['repo_dir']}"
            if [ ! -f .env ] && [ -f .env.example ]; then
                cp .env.example .env
            fi
            {compose_cmd} -f docker-compose.yml up -d
            echo "[+] {app['label']} available at http://127.0.0.1:{app['host_port']}"
        """)


def stop_script_text(app: dict, compose_cmd: str) -> str:
    if app["kind"] == "image":
        return textwrap.dedent(f"""\
            #!/usr/bin/env bash
            set -euo pipefail
            docker rm -f {app['name']} >/dev/null 2>&1 || true
            echo "[+] {app['label']} stopped"
        """)

    elif app["kind"] == "dns":
        return textwrap.dedent(f"""\
            #!/usr/bin/env bash
            set -euo pipefail
            docker rm -f {app['name']} >/dev/null 2>&1 || true
            echo "[+] {app['label']} stopped"
        """)

    else:
        return textwrap.dedent(f"""\
            #!/usr/bin/env bash
            set -euo pipefail
            cd "{app['repo_dir']}"
            {compose_cmd} -f docker-compose.yml down -v
            echo "[+] {app['label']} stopped"
        """)


def healthcheck_command(app: dict) -> str:
    if app["kind"] == "image":
        if app["name"] == "webgoat":
            return f"curl -fsS http://127.0.0.1:{app['host_port']}{app['path']}/actuator/health >/dev/null || curl -fsS http://127.0.0.1:{app['host_port']}{app['path']} >/dev/null"
        return f"curl -fsS http://127.0.0.1:{app['host_port']} >/dev/null"
    if app["kind"] == "dns":
        return f"dig +time=2 +tries=1 @127.0.0.1 -p {app['host_port']} {app['zone']} SOA >/dev/null"
    return f"curl -fsS http://127.0.0.1:{app['host_port']} >/dev/null"



def build_zero_health_container(compose_cmd: str) -> None:
    state = load_state()
    ensure_zero_health_repo()

    if state.get("zero_health_built"):
        log("[=] Zero-Health already built")
        return

    compose_parts = compose_cmd.split()
    run_retry(
        compose_parts + ["-f", "docker-compose.yml", "build"],
        "Build Zero-Health",
        cwd=ZERO_HEALTH_DIR,
    )

    state["zero_health_built"] = True
    save_state(state)


def generate_scripts(compose_cmd: str) -> None:
    CONTAINER_SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)

    for app in APP_SPECS:
        start_path = CONTAINER_SCRIPTS_DIR / f"{app['name']}_start.sh"
        stop_path = CONTAINER_SCRIPTS_DIR / f"{app['name']}_stop.sh"

        start_path.write_text(start_script_text(app, compose_cmd))
        stop_path.write_text(stop_script_text(app, compose_cmd))

        start_path.chmod(0o755)
        stop_path.chmod(0o755)

def write_summary() -> None:

    elapsed = time.time() - INSTALL_START_TIME
    SUMMARY_FILE.write_text(textwrap.dedent(f"""\
        TAC425 Installer Summary
        ========================
        Work dir: {WORK_DIR}
        Log file: {LOG_FILE}
        Installation time: {format_elapsed_time(elapsed)}

        Access URLs:
          Juice Shop   -> http://127.0.0.1:3000
          WrongSecrets -> http://127.0.0.1:8080
          WebGoat      -> http://127.0.0.1:8888/WebGoat
          Zero Health  -> http://127.0.0.1:5000
    """))


def print_summary() -> None:
    elapsed = time.time() - INSTALL_START_TIME
    print("")
    print("=== INSTALL COMPLETE ===")
    print(f"Work dir: {WORK_DIR}")
    print(f"Log file: {LOG_FILE}")
    print(f"Total installation time: {format_elapsed_time(elapsed)}")
    print("Access URLs:")
    print("  Juice Shop   -> http://127.0.0.1:3000")
    print("  WrongSecrets -> http://127.0.0.1:8080")
    print("  WebGoat      -> http://127.0.0.1:8888/WebGoat")
    print("  Zero Health  -> http://127.0.0.1:5000")
    print("")


def main() -> None:
    parser = argparse.ArgumentParser(description="TAC425 installer")
    parser.add_argument("--repair", action="store_true", help="Force re-run of the full preparation flow")
    args = parser.parse_args()

    docker_cmd, compose_cmd = ensure_docker()
    if args.repair and STATE_FILE.exists():
        STATE_FILE.unlink()

    log("[*] Starting TAC425 installation")
    ensure_host_tools()
    ensure_wordlists()
    create_wordlist_symlink()
    build_or_pull_apps(docker_cmd)
    build_zero_health_container(compose_cmd)
    generate_scripts(compose_cmd)
    write_summary()
    print_summary()


if __name__ == "__main__":
    main()