#!/usr/bin/env python3

import subprocess
import sys
import os
import json
import shutil
import logging
import time
from pathlib import Path
import argparse

# -------------------------
# PATHS
# -------------------------

BASE_DIR = Path.home() / "TAC425"
LABS_DIR = BASE_DIR / "labs"
VENV_DIR = BASE_DIR / ".venv"

LOG_FILE = BASE_DIR / "install.log"
STATE_FILE = BASE_DIR / "install_state.json"
SUMMARY_FILE = BASE_DIR / "install_summary.txt"

BASE_DIR.mkdir(exist_ok=True)

# -------------------------
# VENV BOOTSTRAP
# -------------------------

def ensure_venv():
    if not VENV_DIR.exists():
        print("[*] Creating virtual environment...")
        subprocess.run([sys.executable, "-m", "venv", str(VENV_DIR)], check=True)

    pip = VENV_DIR / "bin" / "pip"
    python = VENV_DIR / "bin" / "python"

    if Path("requirements.txt").exists():
        subprocess.run([str(pip), "install", "-r", "requirements.txt"], check=True)

    if sys.executable != str(python):
        subprocess.run([str(python)] + sys.argv)
        sys.exit(0)

# -------------------------
# LOGGING
# -------------------------

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

def log(msg):
    print(msg)
    logging.info(msg)

# -------------------------
# STATE
# -------------------------

def load_state():
    if STATE_FILE.exists():
        return json.load(open(STATE_FILE))
    return {}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

# -------------------------
# SAFE EXECUTION
# -------------------------

def run(cmd, step):
    log(f"[*] {step}: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)
    log(f"[+] {step} complete")

def safe_step(fn, name):
    try:
        log(f"[*] Starting {name}")
        fn()
        log(f"[+] Finished {name}")
    except Exception as e:
        log(f"[ERROR] {name} failed: {e}")
        print(f"\n[!] {name} failed. Check install.log\n")
        sys.exit(1)

# -------------------------
# PROGRESS
# -------------------------

class ProgressTracker:
    def __init__(self, total):
        self.total = total
        self.current = 0

    def step(self, name):
        self.current += 1
        log(f"\n[{self.current}/{self.total}] {name}")

# -------------------------
# PREFLIGHT
# -------------------------

def preflight_checks():
    run(["docker", "--version"], "Check Docker")
    disk = shutil.disk_usage("/")
    if disk.free < 20 * 1024**3:
        raise Exception("Not enough disk space (~20GB required)")

# -------------------------
# DOCKER PERMISSIONS
# -------------------------

def ensure_docker_permissions():
    user = os.getenv("USER")
    groups = subprocess.check_output(["groups", user]).decode()
    if "docker" not in groups:
        run(["sudo", "usermod", "-aG", "docker", user], "Add Docker group")

# -------------------------
# WORDLISTS
# -------------------------

def ensure_wordlists():
    rockyou = Path("/usr/share/wordlists/rockyou.txt")
    rockyou_gz = Path("/usr/share/wordlists/rockyou.txt.gz")
    seclists = Path("/usr/share/wordlists/SecLists")

    if not rockyou.exists():
        if rockyou_gz.exists():
            run(["sudo", "gzip", "-d", str(rockyou_gz)], "Unzip rockyou")
        else:
            run(["sudo", "apt", "update"], "apt update")
            run(["sudo", "apt", "install", "-y", "wordlists"], "Install wordlists")

    if not seclists.exists():
        run(["sudo", "git", "clone",
             "https://github.com/danielmiessler/SecLists.git",
             str(seclists)], "Clone SecLists")

def create_wordlist_symlink():
    link = BASE_DIR / "wordlists"
    if not link.exists():
        link.symlink_to("/usr/share/wordlists")

# -------------------------
# CONFIG
# -------------------------

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
    "javafaces": "8008:8080"
}

BUILD_PLAN = [
    {"name": "dvwa", "image": "santosomar/dvwa", "inject": []},
    {"name": "mutillidae", "image": "kirscht/mutillidae", "inject": []},
    {"name": "javafaces", "image": "tomcat:9.0", "inject": [
        {"src": str(BASE_DIR / "assets/javafaces/vulnerable.war"),
         "dst": "/usr/local/tomcat/webapps/ROOT.war"}
    ]}
]

WEEK_MAP = {
    "week01": ["dvwa", "mutillidae"]
}

# -------------------------
# BUILD
# -------------------------

def build_lab(lab):
    state = load_state()
    name = lab["name"]
    base = lab["image"]
    new_image = f"tac425/{name}:latest"

    if state.get(name):
        log(f"[=] {name} already built")
        return

    container = f"TEMP_{name}"

    run(["docker", "pull", base], f"Pull {name}")
    run(["docker", "run", "-d", "--name", container, base], f"Run {name}")

    if name == "javafaces":
        time.sleep(5)

    for inj in lab.get("inject", []):
        if Path(inj["src"]).exists():
            run(["docker", "cp", inj["src"], f"{container}:{inj['dst']}"],
                f"Inject {name}")

    run(["docker", "commit", container, new_image], f"Commit {name}")
    run(["docker", "rm", "-f", container], f"Cleanup {name}")

    state[name] = True
    save_state(state)

# -------------------------
# SCRIPT GENERATION
# -------------------------

def generate_week_scripts(num, week, labs):
    week_dir = LABS_DIR / week
    week_dir.mkdir(parents=True, exist_ok=True)

    targets = "\n".join([
        f'echo "{lab.upper():<12} http://localhost:{PORT_MAP[lab].split(":")[0]}"'
        for lab in labs
    ])

    start = week_dir / f"lab{num:02d}_start.sh"
    start.write_text(f"""#!/usr/bin/env bash
docker compose up -d
echo ""
echo "Targets:"
{targets}
""")
    start.chmod(0o755)

def generate_root_scripts():
    for i, week in enumerate(WEEK_MAP.keys(), start=1):
        script = BASE_DIR / f"lab{i:02d}_start.sh"
        script.write_text(f"""#!/usr/bin/env bash
cd "$(dirname "$0")/labs/{week}"
./lab{i:02d}_start.sh
""")
        script.chmod(0o755)

# -------------------------
# SUMMARY
# -------------------------

def print_summary():
    print("\n=== INSTALL COMPLETE ===\n")
    print(f"Dir: {BASE_DIR}")
    print(f"Log: {LOG_FILE}")
    print("Run: cd ~/TAC425 && ./lab01_start.sh")

# -------------------------
# REPAIR
# -------------------------

def repair():
    ensure_wordlists()
    create_wordlist_symlink()
    for lab in BUILD_PLAN:
        build_lab(lab)

# -------------------------
# MAIN
# -------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repair", action="store_true")
    args = parser.parse_args()

    if args.repair:
        repair()
        return

    steps = 4 + len(BUILD_PLAN)
    progress = ProgressTracker(steps)

    progress.step("Preflight")
    safe_step(preflight_checks, "Preflight")

    progress.step("Docker Permissions")
    safe_step(ensure_docker_permissions, "Docker Permissions")

    progress.step("Wordlists")
    safe_step(ensure_wordlists, "Wordlists")

    progress.step("Wordlist Link")
    safe_step(create_wordlist_symlink, "Wordlist Link")

    for lab in BUILD_PLAN:
        progress.step(f"Build {lab['name']}")
        safe_step(lambda l=lab: build_lab(l), f"Build {lab['name']}")

    for i, (week, labs) in enumerate(WEEK_MAP.items(), start=1):
        generate_week_scripts(i, week, labs)

    generate_root_scripts()

    print_summary()

if __name__ == "__main__":
    ensure_venv()
    main()
