#!/usr/bin/env python3
"""
TAC425 installer / lab generator.

- Docker required
- Self-installs Docker if missing
- Builds lab images / pre-seeds containers
- Generates weekly compose files and scripts
- Injects lab hints and hidden bridge hints
- Creates validation script
- Uses a local Tomcat WAR asset for JavaFaces
- Week 1 includes a DNS zone-transfer lab container
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
import zipfile
from pathlib import Path

# -----------------------------------------------------------------------------
# Paths
# -----------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
SOURCE_ASSETS = SCRIPT_DIR / "assets"

WORK_DIR = Path.home() / "TAC425"
LABS_DIR = WORK_DIR / "labs"
VENV_DIR = WORK_DIR / ".venv"
LOG_FILE = WORK_DIR / "install.log"
STATE_FILE = WORK_DIR / "install_state.json"
SUMMARY_FILE = WORK_DIR / "install_summary.txt"
VALIDATION_FILE = WORK_DIR / "validate_hints.sh"

for p in (WORK_DIR, LABS_DIR, SOURCE_ASSETS):
    p.mkdir(parents=True, exist_ok=True)

# -----------------------------------------------------------------------------
# Venv bootstrap
# -----------------------------------------------------------------------------

def bootstrap_venv() -> None:
    """
    Create and re-exec into a local venv if we're not already in one.
    """
    if sys.prefix != sys.base_prefix:
        return

    req_file = SCRIPT_DIR / "requirements.txt"
    venv_python = VENV_DIR / "bin" / "python"

    if not VENV_DIR.exists():
        VENV_DIR.parent.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.run([sys.executable, "-m", "venv", str(VENV_DIR)], check=True)
        except subprocess.CalledProcessError:
            # Try to install python3-venv, then retry.
            subprocess.run(["sudo", "apt", "update"], check=True)
            subprocess.run(["sudo", "apt", "install", "-y", "python3-venv"], check=True)
            subprocess.run([sys.executable, "-m", "venv", str(VENV_DIR)], check=True)

    if req_file.exists():
        subprocess.run([str(VENV_DIR / "bin" / "pip"), "install", "-r", str(req_file)], check=True)

    os.execv(str(venv_python), [str(venv_python), *sys.argv])


bootstrap_venv()
INSTALL_START_TIME = time.time()

# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

def log(msg: str) -> None:
    print(msg)
    logging.info(msg)

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

DOCKER_CMD = ["docker"]

def format_elapsed_time(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)

    if hours:
        return f"{hours}h {minutes}m {secs}s"

    if minutes:
        return f"{minutes}m {secs}s"

    return f"{secs}s"
    
def asset(rel: str) -> Path:
    return SOURCE_ASSETS / rel

def run(cmd: list[str], step: str) -> None:
    log(f"[*] {step}: {' '.join(cmd)}")
    try:
        subprocess.run(cmd, check=True)
        log(f"[+] {step} complete")
    except FileNotFoundError as e:
        raise RuntimeError(f"Command not found: {cmd[0]}") from e
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"{step} failed: {e}") from e

def run_allow_fail(cmd: list[str]) -> None:
    subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def run_docker(args: list[str], step: str) -> None:
    run(DOCKER_CMD + args, step)

def can_run(cmd: list[str]) -> bool:
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
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

def safe_step(fn, name: str) -> None:
    try:
        log(f"[*] Starting {name}")
        fn()
        log(f"[+] Finished {name}")
    except Exception as e:
        log(f"[ERROR] {name} failed: {e}")
        raise

def try_apt_install(packages: list[str], label: str) -> bool:
    try:
        run(["sudo", "apt", "install", "-y", *packages], label)
        return True
    except Exception as e:
        log(f"[!] {label} failed: {e}")
        return False

# -----------------------------------------------------------------------------
# Preflight / host tools / Docker
# -----------------------------------------------------------------------------

MIN_DISK_GB = 25

def preflight_checks() -> None:
    log("[*] Running preflight checks")

    disk = shutil.disk_usage(Path.home())
    free_gb = disk.free / (1024 ** 3)
    if free_gb < MIN_DISK_GB:
        raise RuntimeError(f"Need at least {MIN_DISK_GB} GB free disk space; found {free_gb:.1f} GB")

    log(f"[+] Disk space OK ({free_gb:.1f} GB free)")

def ensure_host_tools() -> None:
    """
    Install common tools the scripts use if they are missing.
    """
    pkg_map = {
        "git": "git",
        "curl": "curl",
        "lsof": "lsof",
        "dig": "dnsutils",
        "zip": "zip",
        "unzip": "unzip",
    }

    missing = []
    for cmd, pkg in pkg_map.items():
        if shutil.which(cmd) is None:
            missing.append(pkg)

    if not missing:
        log("[=] Host tools already present")
        return

    run(["sudo", "apt", "update"], "apt update")
    run(["sudo", "apt", "install", "-y", *sorted(set(missing))], "Install host tools")

def ensure_docker() -> None:
    global DOCKER_CMD, COMPOSE_CMD

    if shutil.which("docker") is None:
        log("[!] Docker not found; installing Docker Engine")

        run(["sudo", "apt", "update"], "apt update")

        run(
            ["sudo", "apt", "install", "-y", "docker.io"],
            "Install Docker"
        )

        run(
            ["sudo", "apt", "install", "-y", "docker-compose"],
            "Install Docker Compose"
        )

        run(
            ["sudo", "systemctl", "enable", "--now", "docker"],
            "Enable and start Docker"
        )

    if can_run(["docker", "--version"]) and can_run(["docker", "info"]):
        DOCKER_CMD = ["docker"]

    elif can_run(["sudo", "docker", "--version"]) and can_run(["sudo", "docker", "info"]):
        DOCKER_CMD = ["sudo", "docker"]

    else:
        raise RuntimeError(
            "Docker installed but daemon is unavailable."
        )

    if shutil.which("docker-compose") is None:
        raise RuntimeError(
            "docker-compose not found."
        )

    COMPOSE_CMD = (
        ["sudo", "docker-compose"]
        if DOCKER_CMD[0] == "sudo"
        else ["docker-compose"]
    )

    run_docker(["--version"], "Verify Docker")

    user = os.getenv("USER")

    try:
        groups = subprocess.check_output(
            ["id", "-nG", user]
        ).decode().split()

        if "docker" not in groups:

            run(
                ["sudo", "usermod", "-aG", "docker", user],
                "Add user to docker group"
            )

            log(
                "[!] Log out and back in once after install "
                "so Docker works without sudo"
            )

    except Exception:
        pass

# -----------------------------------------------------------------------------
# Wordlists
# -----------------------------------------------------------------------------

def ensure_wordlists() -> None:
    """
    Ensure rockyou and SecLists exist in /usr/share/wordlists.
    """
    rockyou_txt = Path("/usr/share/wordlists/rockyou.txt")
    rockyou_gz = Path("/usr/share/wordlists/rockyou.txt.gz")
    seclists_dir = Path("/usr/share/wordlists/SecLists")

    if not rockyou_txt.exists():
        if rockyou_gz.exists():
            run(["sudo", "gzip", "-d", str(rockyou_gz)], "Unzip rockyou")
        else:
            run(["sudo", "apt", "update"], "apt update (wordlists)")
            run(["sudo", "apt", "install", "-y", "wordlists"], "Install wordlists")
            if rockyou_gz.exists():
                run(["sudo", "gzip", "-d", str(rockyou_gz)], "Unzip rockyou")

    if not seclists_dir.exists():
        run(["sudo", "git", "clone", "https://github.com/danielmiessler/SecLists.git", str(seclists_dir)], "Clone SecLists")

    log("[+] Wordlists ready")

def create_wordlist_symlink() -> None:
    link = WORK_DIR / "wordlists"
    target = Path("/usr/share/wordlists")

    if link.is_symlink():
        if link.resolve() == target:
            log("[=] Wordlist symlink already correct")
            return
        link.unlink()
    elif link.exists():
        if link.is_dir():
            shutil.rmtree(link)
        else:
            link.unlink()

    link.symlink_to(target)
    log(f"[+] Created symlink {link} -> {target}")

# -----------------------------------------------------------------------------
# Asset generation
# -----------------------------------------------------------------------------

def placeholder_content(path: Path) -> bytes | str:
    name = path.name.lower()

    if name == "contact.html":
        return textwrap.dedent("""\
            <!doctype html>
            <html>
            <head><title>Contact</title></head>
            <body>
            <h1>Contact</h1>
            <!-- Clue: Enumerate DNS to find more targets -->
            </body>
            </html>
        """)

    if name == "itp425.txt":
        return textwrap.dedent("""\
            # Nikto-style placeholder output
            # Directory indexing discovered.
            # Replace with your real lab clue text.
        """)

    if name == "drupal8.txt":
        return textwrap.dedent("""\
            # Drupal 8 version / scan results placeholder
            # Replace with your real scan output.
        """)

    if name == "webmin.txt":
        return textwrap.dedent("""\
            # Webmin version / scan results placeholder
            # Replace with your real scan output.
        """)

    if name == "clusterbomb.txt":
        return textwrap.dedent("""\
            # Burp Intruder hint placeholder
            # Try Cluster Bomb.
        """)

    if name == "flag.txt":
        return textwrap.dedent("""\
            Internal gateway clue placeholder.
            Replace with the real internal target IP.
        """)

    if name == "xml.bak":
        return textwrap.dedent("""\
            SECRET_KEY=replace_me
            ALGORITHM=hmac-sha1
        """)

    if name == "robots.txt":
        return textwrap.dedent("""\
            User-agent: *
            Disallow: /admin/
            Disallow: /secret/
        """)

    if name == "access.log":
        return textwrap.dedent("""\
            127.0.0.1 - - [01/Jan/2026:00:00:00 +0000] "GET / HTTP/1.1" 200 123
            # Replace with a real log entry for the lab
        """)

    return f"# Placeholder for {path.name}\n"

def generate_placeholder_assets() -> None:
    """
    Create missing student-facing assets so the installer can run end-to-end.
    """
    for entry in LAB_HINT_TARGETS:
        src = entry["src"]
        src.parent.mkdir(parents=True, exist_ok=True)
        if src.exists():
            continue

        if src.suffix.lower() == ".zip":
            # Create a small valid ZIP file
            with zipfile.ZipFile(src, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("README.txt", "Placeholder archive for TAC425.\nReplace with the real lab asset.\n")
                if "tomcat-stuff.zip" in src.name.lower():
                    zf.writestr(
                        "xml.bak",
                        "SECRET_KEY=replace_me\nALGORITHM=hmac-sha1\n"
                    )
            log(f"[+] Created placeholder ZIP {src}")
            continue

        content = placeholder_content(src)
        if isinstance(content, bytes):
            src.write_bytes(content)
        else:
            src.write_text(content)
        log(f"[+] Created placeholder asset {src}")

def generate_bridge_hint_assets() -> None:
    bridge_dir = SOURCE_ASSETS / "bridge"
    bridge_dir.mkdir(parents=True, exist_ok=True)

    for week, hint in BRIDGE_HINTS.items():
        p = bridge_dir / f"{week}.txt"
        p.write_text(hint.strip() + "\n")
        log(f"[+] Created bridge hint asset {p}")

def generate_dns_assets() -> None:
    dns_dir = SOURCE_ASSETS / "dns"
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

def ensure_javafaces_war() -> None:
    """
    Ensure vulnerable.war exists in SOURCE_ASSETS/javafaces.
    If there is exactly one other WAR in the directory tree, copy it into place.
    """
    jf_dir = SOURCE_ASSETS / "javafaces"
    jf_dir.mkdir(parents=True, exist_ok=True)

    war = jf_dir / "vulnerable.war"
    if war.exists() and war.stat().st_size > 0:
        return

    candidates = []
    for p in jf_dir.glob("*.war"):
        if p.name != "vulnerable.war":
            candidates.append(p)
    target_dir = jf_dir / "target"
    if target_dir.exists():
        candidates.extend([p for p in target_dir.glob("*.war") if p.is_file()])

    if len(candidates) == 1:
        shutil.copy2(candidates[0], war)
        log(f"[+] Copied JavaFaces WAR from {candidates[0]} to {war}")
        return

    raise RuntimeError(
        "Missing JavaFaces WAR.\n"
        "Place it at: assets/javafaces/vulnerable.war\n"
        "Or keep exactly one other WAR in assets/javafaces/ or assets/javafaces/target/ "
        "so the installer can copy it automatically."
    )

# -----------------------------------------------------------------------------
# Hint maps
# -----------------------------------------------------------------------------

LAB_HINT_TARGETS = [
    {"lab": "lab01", "container": "xxe_widget",    "src": asset("lab01/contact.html"),       "dst": "/var/www/html/contact.html"},
    {"lab": "lab02", "container": "phpldapadmin",   "src": asset("lab02/itp425.txt"),         "dst": "/var/www/html/itp425.txt"},
    {"lab": "lab03", "container": "drupal8",        "src": asset("lab03/drupal8.txt"),        "dst": "/var/www/html/drupal8.txt"},
    {"lab": "lab03", "container": "webmin",         "src": asset("lab03/webmin.txt"),         "dst": "/etc/webmin/webmin.txt"},
    {"lab": "lab04", "container": "dvwa",           "src": asset("lab04/clusterbomb.txt"),    "dst": "/var/www/html/.hints/clusterbomb.txt"},
    {"lab": "lab04", "container": "bwapp",          "src": asset("lab04/clusterbomb.txt"),    "dst": "/var/www/html/.hints/clusterbomb.txt"},
    {"lab": "lab04", "container": "mutillidae",     "src": asset("lab04/clusterbomb.txt"),    "dst": "/var/www/html/.hints/clusterbomb.txt"},
    {"lab": "lab09", "container": "ssrf",           "src": asset("lab09/flag.txt"),           "dst": "/etc/flag.txt"},
    {"lab": "lab10", "container": "javafaces",      "src": asset("lab10/tomcat-stuff.zip"),   "dst": "/var/backups/tomcat-stuff.zip"},
    {"lab": "lab10", "container": "javafaces",      "src": asset("lab10/xml.bak"),            "dst": "/var/backups/xml.bak"},
    {"lab": "lab11", "container": "drupal9",        "src": asset("lab11/robots.txt"),         "dst": "/var/www/html/robots.txt"},
    {"lab": "lab11", "container": "mutillidae",     "src": asset("lab11/robots.txt"),         "dst": "/var/www/html/robots.txt"},
    {"lab": "lab11", "container": "bwapp",          "src": asset("lab11/robots.txt"),         "dst": "/var/www/html/robots.txt"},
    {"lab": "lab12", "container": "mutillidae",     "src": asset("lab12/access.log"),         "dst": "/var/log/apache2/access.log"},
]

BRIDGE_HINTS = {
    "week01": "Next week: focus on headers, service versions, robots.txt, and attack surface mapping.",
    "week02": "Next week: pay attention to reflected input and Burp Repeater.",
    "week03": "Next week: compare manual and automated injection testing.",
    "week04": "Next week: think about file paths, traversal, and LFI/RFI.",
    "week05": "Next week: look closely at authentication state, cookies, and JWTs.",
    "week06": "Next week: study session handling and authorization boundaries.",
    "week07": "Next week: practice documenting evidence and mapping findings to OWASP.",
    "week08": "Next week: enumerate API endpoints before attacking them.",
    "week09": "Next week: test API auth and BOLA-style issues.",
    "week10": "Next week: move from REST to GraphQL and rate limiting.",
    "week11": "Next week: trust boundaries inside the backend matter.",
    "week12": "Next week: inspect serialized data and integrity assumptions.",
    "week13": "Next week: review logging, monitoring, crypto, and password storage.",
    "week14": "Next week: final project polish and comprehensive review.",
}

BRIDGE_HINT_TARGETS = [
    {"week": "week01", "container": "xxe_widget",  "src": asset("bridge/week01.txt"), "dst": "/var/www/html/.bridge/week02.txt"},
    {"week": "week02", "container": "phpldapadmin","src": asset("bridge/week02.txt"), "dst": "/var/www/html/.bridge/week03.txt"},
    {"week": "week03", "container": "bwapp",       "src": asset("bridge/week03.txt"), "dst": "/var/www/html/.bridge/week04.txt"},
    {"week": "week04", "container": "dvwa",        "src": asset("bridge/week04.txt"), "dst": "/var/www/html/.bridge/week05.txt"},
    {"week": "week05", "container": "path_traversal","src": asset("bridge/week05.txt"), "dst": "/var/www/html/.bridge/week06.txt"},
    {"week": "week06", "container": "juice_shop",   "src": asset("bridge/week06.txt"), "dst": "/app/.bridge/week07.txt"},
    {"week": "week07", "container": "dvna",        "src": asset("bridge/week07.txt"), "dst": "/app/.bridge/week08.txt"},
    {"week": "week08", "container": "juice_shop",   "src": asset("bridge/week08.txt"), "dst": "/app/.bridge/week09.txt"},
    {"week": "week09", "container": "vapi",        "src": asset("bridge/week09.txt"), "dst": "/app/.bridge/week10.txt"},
    {"week": "week10", "container": "dvna",        "src": asset("bridge/week10.txt"), "dst": "/app/.bridge/week11.txt"},
    {"week": "week11", "container": "vapi",        "src": asset("bridge/week11.txt"), "dst": "/app/.bridge/week12.txt"},
    {"week": "week12", "container": "ssrf",        "src": asset("bridge/week12.txt"), "dst": "/var/www/html/.bridge/week13.txt"},
    {"week": "week13", "container": "javafaces",   "src": asset("bridge/week13.txt"), "dst": "/usr/local/tomcat/webapps/.bridge/week14.txt"},
    {"week": "week14", "container": "mutillidae",  "src": asset("bridge/week14.txt"), "dst": "/var/www/html/.bridge/week15.txt"},
]

def add_injection(container_name: str, src: Path, dst: str) -> None:
    for lab in BUILD_PLAN:
        if lab["name"] == container_name:
            inj = {"src": str(src), "dst": dst}
            lab.setdefault("inject", [])
            if inj not in lab["inject"]:
                lab["inject"].append(inj)
            return
    raise RuntimeError(f"Container '{container_name}' not found in BUILD_PLAN")

def attach_lab_hints() -> None:
    for item in LAB_HINT_TARGETS:
        add_injection(item["container"], item["src"], item["dst"])

def attach_bridge_hints() -> None:
    for item in BRIDGE_HINT_TARGETS:
        add_injection(item["container"], item["src"], item["dst"])

def collect_validation_checks() -> list[tuple[str, str]]:
    checks: list[tuple[str, str]] = []

    for item in LAB_HINT_TARGETS:
        checks.append((item["container"], item["dst"]))

    for item in BRIDGE_HINT_TARGETS:
        checks.append((item["container"], item["dst"]))

    # DNS assets are baked into the image, so validate those too.
    checks.extend([
        ("dns_zone", "/etc/bind/named.conf"),
        ("dns_zone", "/etc/bind/named.conf.local"),
        ("dns_zone", "/etc/bind/db.tac425.net"),
    ])

    # Deduplicate while preserving order.
    seen = set()
    unique = []
    for c in checks:
        if c not in seen:
            seen.add(c)
            unique.append(c)
    return unique

# -----------------------------------------------------------------------------
# Build plan and weekly mapping
# -----------------------------------------------------------------------------

BUILD_PLAN = [
    # Week 1 / foundational
    {"name": "xxe_widget",   "base_image": "neuralegion/xxelab",                       "startup_delay": 3},
    {"name": "dns_zone",     "image": "tac425/dns_zone:latest", "build_context": str(SOURCE_ASSETS / "dns"), "dockerfile": str(SOURCE_ASSETS / "dns" / "Dockerfile"), "startup_delay": 2},

    # Week 2 / enumeration + misconfiguration
    {"name": "phpldapadmin", "base_image": "vulnerables/phpldapadmin-remote-dump",      "startup_delay": 3},
    {"name": "drupal8",      "base_image": "logeecom/drupal831",                        "startup_delay": 5},
    {"name": "webmin",       "base_image": "vulfocus/webmin_cve-2022-0824",             "startup_delay": 5},
    {"name": "heartbleed",   "base_image": "kacperzuk/heartbleed-testbed-nginx-bleed",  "startup_delay": 4},
    {"name": "struts2",      "base_image": "vantagepointdocker/cve-2023-50164",         "startup_delay": 4},
    {"name": "spring4shell", "base_image": "dockerbucket/cve-2022-22965",               "startup_delay": 4},

    # Week 3-5 / input handling + file handling
    {"name": "bwapp",        "base_image": "raesene/bwapp",                              "startup_delay": 4},
    {"name": "dvwa",         "base_image": "santosomar/dvwa",                            "startup_delay": 4},
    {"name": "mutillidae",   "base_image": "kirscht/mutillidae",                        "startup_delay": 4},
    {"name": "path_traversal","base_image": "blueteamsteve/cve-2021-41773:no-cgid",      "startup_delay": 3},

    # Week 6-8 / auth + midterm
    {"name": "juice_shop",   "base_image": "santosomar/juice-shop",                      "startup_delay": 6},
    {"name": "dvna",         "base_image": "appsecco/dvna:sqlite",                       "startup_delay": 5},

    # Week 9-11 / APIs
    {"name": "ssrf2",        "base_image": "appsecco/dsvw",                              "startup_delay": 4},
    {"name": "vapi",         "base_image": "roottusk/vapi",                                "startup_delay": 4},

    # Week 12 / SSRF
    {"name": "ssrf",         "base_image": "nyctophobia/ssrf-playground:latest",         "startup_delay": 4},

    # Week 13 / advanced vulns
    {"name": "javafaces",    "base_image": "tomcat:9.0",                                 "startup_delay": 6},
    {"name": "drupal9",      "base_image": "ricardoamaro/drupal9",                       "startup_delay": 5},

    # Week 14 / security operations
    {"name": "ctfd",         "base_image": "ctfd/ctfd:2.2.1-dev",                        "startup_delay": 10},
]

WEEK_MAP = {
    "week01": ["xxe_widget", "dns_zone"],
    "week02": ["phpldapadmin", "drupal8", "webmin", "heartbleed", "struts2", "spring4shell"],
    "week03": ["bwapp", "dvwa", "mutillidae"],
    "week04": ["bwapp", "dvwa", "mutillidae", "path_traversal"],
    "week05": ["dvwa", "mutillidae", "bwapp", "path_traversal"],
    "week06": ["juice_shop", "dvwa", "mutillidae", "dvna"],
    "week07": ["dvwa", "mutillidae", "bwapp"],
    "week08": ["juice_shop", "dvwa", "mutillidae", "dvna"],
    "week09": ["vapi", "ssrf2", "dvna"],
    "week10": ["vapi", "dvna", "ssrf2"],
    "week11": ["vapi", "dvna", "ssrf2"],
    "week12": ["ssrf", "mutillidae"],
    "week13": ["javafaces", "drupal8", "drupal9", "heartbleed"],
    "week14": ["mutillidae", "dvwa", "drupal9", "spring4shell"],
    "week15": ["ctfd"],
}

PORT_MAP = {
    "vapi": "8081:8081",
    "ctfd": "9990:8000",
    "juice_shop": "9901:3000",
    "phpldapadmin": "9999:80",
    "mutillidae": "8880:80",
    "ssrf2": "9900:8000",
    "bwapp": "8088:80",
    "dvwa": "8882:80",
    "spring4shell": "8098:8080",
    "ssrf": "9000:80",
    "webmin": "10000:10000",
    "heartbleed": "8443:443",
    "struts2": "8899:8080",
    "xxe_widget": "8883:80",
    "path_traversal": "8082:80",
    "dvna": "9090:9090",
    "drupal9": "8891:80",
    "drupal8": "8881:80",
    "javafaces": "8008:8080",
    "dns_zone": "5353:53",
}

SERVICE_META = {
    "webmin": {"scheme": "https", "path": "/"},
    "heartbleed": {"scheme": "https", "path": "/"},
    "dvna": {"scheme": "http", "path": "/login"},
    "javafaces": {"scheme": "http", "path": "/userSubscribe.faces"},
    "dns_zone": {"kind": "dns", "zone": "tac425.net"},
}

# -----------------------------------------------------------------------------
# Docker / build helpers
# -----------------------------------------------------------------------------

def build_lab(lab: dict) -> None:
    state = load_state()
    name = lab["name"]
    final_image = lab.get("image", f"tac425/{name}:latest")
    temp_container = f"tac425_build_{name}"

    if state.get(name):
        log(f"[=] {name} already built")
        return

    # Special case: dns_zone is built from a local Dockerfile.
    if lab.get("build_context"):
        run_docker(
            ["build", "-t", final_image, "-f", lab["dockerfile"], lab["build_context"]],
            f"Build {name}"
        )
        state[name] = True
        save_state(state)
        return

    base_image = lab["base_image"]
    startup_delay = lab.get("startup_delay", 3)

    run_allow_fail(DOCKER_CMD + ["rm", "-f", temp_container])
    run_with_retry(DOCKER_CMD + ["pull", base_image], f"Pull {name}")
    run_docker(["run", "-d", "--name", temp_container, base_image], f"Start temp {name}")

    if startup_delay:
        time.sleep(startup_delay)

    for inj in lab.get("inject", []):
        src = Path(inj["src"])
        dst = inj["dst"]

        if not src.exists():
            log(f"[WARN] Missing injection file for {name}: {src}")
            continue

        dst_parent = Path(dst).parent.as_posix()
        if dst_parent and dst_parent != "/":
            run_docker(["exec", "-u", "root", temp_container, "mkdir", "-p", dst_parent], f"Create path for {name}")

        run_docker(["cp", str(src), f"{temp_container}:{dst}"], f"Inject into {name}")

    run_docker(["commit", temp_container, final_image], f"Commit {name}")
    run_allow_fail(DOCKER_CMD + ["rm", "-f", temp_container])

    state[name] = True
    save_state(state)

# -----------------------------------------------------------------------------
# Compose / scripts / validation
# -----------------------------------------------------------------------------

def compose_ports_block(service: str) -> str:
    if service == "dns_zone":
        return '    ports:\n      - "5353:53/tcp"\n      - "5353:53/udp"\n'
    return f'    ports:\n      - "{PORT_MAP[service]}"\n'

def run_with_retry(cmd: list[str], step: str, retries: int = 3, delay: int = 5) -> None:
    last_err = None

    for attempt in range(1, retries + 1):
        try:
            log(f"[*] {step} (attempt {attempt}/{retries}): {' '.join(cmd)}")
            subprocess.run(cmd, check=True)
            log(f"[+] {step} complete")
            return
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            last_err = e
            if attempt < retries:
                log(f"[!] {step} failed on attempt {attempt}/{retries}: {e}")
                log(f"[*] Retrying in {delay}s...")
                time.sleep(delay)
                delay *= 2
            else:
                raise RuntimeError(f"{step} failed after {retries} attempts: {e}") from e
                
def generate_compose(week: str, services: list[str]) -> str:
    blocks = []
    for service in services:
        image = f"tac425/{service}:latest"
        block = f"""  {service}:
    image: {image}
    container_name: {service}
    restart: unless-stopped
{compose_ports_block(service)}"""
        blocks.append(block.rstrip())

    return "version: \"3.8\"\n\nservices:\n" + "\n".join(blocks) + "\n"

def service_target_line(service: str) -> str:
    port = PORT_MAP[service].split(":")[0]
    meta = SERVICE_META.get(service, {})
    if meta.get("kind") == "dns":
        return f"{service.upper():<15} dig axfr {meta['zone']} @127.0.0.1 -p {port}"
    scheme = meta.get("scheme", "http")
    path = meta.get("path", "/")
    return f"{service.upper():<15} {scheme}://localhost:{port}{path}"

def service_check_line(service: str) -> str:
    port = PORT_MAP[service].split(":")[0]
    meta = SERVICE_META.get(service, {})
    if meta.get("kind") == "dns":
        zone = meta["zone"]
        return f'check_dns "{service}" "{port}" "{zone}"'
    scheme = meta.get("scheme", "http")
    path = meta.get("path", "/")
    if scheme == "https":
        return f'check_https "{service}" "https://localhost:{port}{path}"'
    return f'check_http "{service}" "http://localhost:{port}{path}"'

def generate_week_scripts(week_num: int, week_name: str, services: list[str]) -> None:
    week_dir = LABS_DIR / week_name
    week_dir.mkdir(parents=True, exist_ok=True)

    compose_file = week_dir / "docker-compose.yml"
    compose_file.write_text(generate_compose(week_name, services))
    compose_file.chmod(0o644)

    unique_ports = []
    for svc in services:
        p = PORT_MAP[svc].split(":")[0]
        if p not in unique_ports:
            unique_ports.append(p)

    target_lines = [service_target_line(svc) for svc in services]
    check_lines = [service_check_line(svc) for svc in services]

    start_script = week_dir / f"lab{week_num:02d}_start.sh"
    stop_script = week_dir / f"lab{week_num:02d}_stop.sh"
    reset_script = week_dir / f"lab{week_num:02d}_reset.sh"

    start_script.write_text(textwrap.dedent(f"""\
        #!/usr/bin/env bash
        set -u

        COMPOSE_FILE="$(dirname "$0")/docker-compose.yml"

        check_port() {{
            PORT="$1"
            PID="$(lsof -ti tcp:"$PORT" 2>/dev/null | head -n1 || true)"
            if [ -n "$PID" ]; then
                PROC="$(ps -p "$PID" -o comm= 2>/dev/null | head -n1 || true)"
                echo "[WARN] Port $PORT already in use"
                echo "       Process: $PROC (PID $PID)"
            else
                echo "[OK] Port $PORT available"
            fi
        }}

        check_http() {{
            NAME="$1"
            URL="$2"
            if curl -fsS --max-time 10 "$URL" >/dev/null 2>&1; then
                echo "[OK] $NAME healthy"
                return 0
            fi
            echo "[WARN] $NAME unhealthy -> restarting"
            docker compose -f "$COMPOSE_FILE" restart "$NAME" >/dev/null 2>&1 || true
            sleep 4
            if curl -fsS --max-time 10 "$URL" >/dev/null 2>&1; then
                echo "[OK] $NAME recovered"
            else
                echo "[FAIL] $NAME still not responding"
            fi
        }}

        check_https() {{
            NAME="$1"
            URL="$2"
            if curl -kfsS --max-time 10 "$URL" >/dev/null 2>&1; then
                echo "[OK] $NAME healthy"
                return 0
            fi
            echo "[WARN] $NAME unhealthy -> restarting"
            docker compose -f "$COMPOSE_FILE" restart "$NAME" >/dev/null 2>&1 || true
            sleep 4
            if curl -kfsS --max-time 10 "$URL" >/dev/null 2>&1; then
                echo "[OK] $NAME recovered"
            else
                echo "[FAIL] $NAME still not responding"
            fi
        }}

        check_dns() {{
            NAME="$1"
            PORT="$2"
            ZONE="$3"
            if dig +time=2 +tries=1 @127.0.0.1 -p "$PORT" "$ZONE" SOA >/dev/null 2>&1; then
                echo "[OK] $NAME healthy"
                return 0
            fi
            echo "[WARN] $NAME unhealthy -> restarting"
            docker compose -f "$COMPOSE_FILE" restart "$NAME" >/dev/null 2>&1 || true
            sleep 4
            if dig +time=2 +tries=1 @127.0.0.1 -p "$PORT" "$ZONE" SOA >/dev/null 2>&1; then
                echo "[OK] $NAME recovered"
            else
                echo "[FAIL] $NAME still not responding"
            fi
        }}

        echo "[*] Checking for port conflicts..."
        echo ""
    """))

    for p in unique_ports:
        start_script.write_text(start_script.read_text() + f'check_port {p}\n')

    start_script.write_text(start_script.read_text() + textwrap.dedent(f"""\
        echo ""
        echo "[*] Starting Lab {week_num:02d} containers..."
        docker compose -f "$COMPOSE_FILE" up -d --remove-orphans

        echo ""
        echo "[*] Waiting for services..."
        sleep 5

        echo ""
        echo "[*] Verifying services..."
    """))

    for line in check_lines:
        start_script.write_text(start_script.read_text() + line + "\n")

    start_script.write_text(start_script.read_text() + textwrap.dedent("""\
        echo ""
        echo "[+] Targets:"
    """))

    for line in target_lines:
        start_script.write_text(start_script.read_text() + f'echo "{line}"\n')

    start_script.write_text(start_script.read_text() + "\n")
    start_script.chmod(0o755)

    stop_script.write_text(textwrap.dedent(f"""\
        #!/usr/bin/env bash
        set -u
        COMPOSE_FILE="$(dirname "$0")/docker-compose.yml"
        echo "[*] Stopping Lab {week_num:02d} containers..."
        docker compose -f "$COMPOSE_FILE" down
        echo "[+] Containers stopped"
    """))
    stop_script.chmod(0o755)

    reset_script.write_text(textwrap.dedent(f"""\
        #!/usr/bin/env bash
        set -u
        COMPOSE_FILE="$(dirname "$0")/docker-compose.yml"
        echo "[*] Resetting Lab {week_num:02d}..."
        docker compose -f "$COMPOSE_FILE" down -v --remove-orphans
        docker compose -f "$COMPOSE_FILE" up -d --remove-orphans
        echo "[+] Lab reset complete"
    """))
    reset_script.chmod(0o755)

def generate_root_scripts() -> None:
    for idx, week_name in enumerate(WEEK_MAP.keys(), start=1):
        for kind in ("start", "stop", "reset"):
            script = WORK_DIR / f"lab{idx:02d}_{kind}.sh"
            script.write_text(textwrap.dedent(f"""\
                #!/usr/bin/env bash
                cd "$(dirname "$0")/labs/{week_name}"
                ./lab{idx:02d}_{kind}.sh
            """))
            script.chmod(0o755)

def generate_validation_script() -> None:
    checks = collect_validation_checks()

    lines = [
        "#!/usr/bin/env bash",
        "set -u",
        "",
        'echo "========================================"',
        'echo "TAC425 Hint Validation Script"',
        'echo "========================================"',
        'echo ""',
        "PASS=0",
        "FAIL=0",
        "",
        "check_file () {",
        "    CONTAINER=\"$1\"",
        "    PATH_INSIDE=\"$2\"",
        "    echo \"[CHECK] $CONTAINER -> $PATH_INSIDE\"",
        "    if docker exec \"$CONTAINER\" test -f \"$PATH_INSIDE\" >/dev/null 2>&1; then",
        "        echo \"[OK] Found\"",
        "        PASS=$((PASS+1))",
        "    else",
        "        echo \"[FAIL] Missing\"",
        "        FAIL=$((FAIL+1))",
        "    fi",
        "    echo \"\"",
        "}",
        "",
        'echo "[*] Checking running containers..."',
        'docker ps --format "{{.Names}}"',
        'echo ""',
        "",
    ]

    current_lab = None
    for container, path in checks:
        # This block is purely informational in the generated script.
        if current_lab != container:
            current_lab = container
            lines.append(f"# {container}")
        lines.append(f'check_file "{container}" "{path}"')

    lines.extend([
        'echo "========================================"',
        'echo "Validation Summary"',
        'echo "========================================"',
        'echo ""',
        'echo "Passed: $PASS"',
        'echo "Failed: $FAIL"',
        'echo ""',
        'if [ "$FAIL" -eq 0 ]; then',
        '    echo "[SUCCESS] All hints validated"',
        'else',
        '    echo "[WARNING] Some hints missing"',
        'fi',
        'echo ""',
    ])

    VALIDATION_FILE.write_text("\n".join(lines) + "\n")
    VALIDATION_FILE.chmod(0o755)

def write_summary() -> None:
    elapsed = time.time() - INSTALL_START_TIME
    lines = [
        "TAC425 Installer Summary",
        "========================",
        f"Work dir: {WORK_DIR}",
        f"Log file: {LOG_FILE}",
        f"Validation: {VALIDATION_FILE}",
        f"Installation Time: {format_elapsed_time(elapsed)}",
        "",
        "If Docker was installed during setup, log out and back in once so Docker works without sudo.",
    ]
    SUMMARY_FILE.write_text("\n".join(lines) + "\n")

def print_summary() -> None:
    elapsed = time.time() - INSTALL_START_TIME

    print("")
    print("=== INSTALL COMPLETE ===")
    print(f"Work dir: {WORK_DIR}")
    print(f"Log file: {LOG_FILE}")
    print(f"Validation: {VALIDATION_FILE}")
    print("")
    print(f"Total installation time: {format_elapsed_time(elapsed)}")
    print("")
    print("Run a lab from the TAC425 directory, for example:")
    print("  cd ~/TAC425 && ./lab01_start.sh")
    print("")

    log(f"[+] Total installation time: {format_elapsed_time(elapsed)}")
# -----------------------------------------------------------------------------
# Main install / repair flow
# -----------------------------------------------------------------------------

def ensure_all_assets() -> None:
    generate_dns_assets()
    generate_bridge_hint_assets()
    generate_placeholder_assets()
    ensure_javafaces_war()

def attach_all_hints() -> None:
    attach_lab_hints()
    attach_bridge_hints()

def build_all_labs() -> None:
    for lab in BUILD_PLAN:
        build_lab(lab)

def generate_all_runtime_files() -> None:
    for idx, (week_name, services) in enumerate(WEEK_MAP.items(), start=1):
        generate_week_scripts(idx, week_name, services)
    generate_root_scripts()
    generate_validation_script()
    write_summary()

def repair() -> None:
    safe_step(preflight_checks, "Preflight checks")
    safe_step(ensure_host_tools, "Host tools")
    safe_step(ensure_docker, "Docker")
    safe_step(ensure_wordlists, "Wordlists")
    safe_step(create_wordlist_symlink, "Wordlist symlink")
    safe_step(ensure_all_assets, "Assets")
    safe_step(attach_all_hints, "Attach hints")
    safe_step(build_all_labs, "Build labs")
    safe_step(generate_all_runtime_files, "Generate runtime files")
    print_summary()

def main() -> None:
    parser = argparse.ArgumentParser(description="TAC425 installer")
    parser.add_argument("--repair", action="store_true", help="Repair / rebuild missing items")
    args = parser.parse_args()

    if args.repair:
        repair()
        return

    safe_step(preflight_checks, "Preflight checks")
    safe_step(ensure_host_tools, "Host tools")
    safe_step(ensure_docker, "Docker")
    safe_step(ensure_wordlists, "Wordlists")
    safe_step(create_wordlist_symlink, "Wordlist symlink")
    safe_step(ensure_all_assets, "Assets")
    safe_step(attach_all_hints, "Attach hints")
    safe_step(build_all_labs, "Build labs")
    safe_step(generate_all_runtime_files, "Generate runtime files")
    print_summary()

if __name__ == "__main__":
    main()