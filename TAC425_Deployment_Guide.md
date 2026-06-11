# TAC425 Deployment Guide

This guide keeps the published schedule unchanged and updates only the installer plan. Week 1 remains the reconnaissance / environment week, which is where DNS and zone-transfer work belongs. The midterm Juice Shop placement and the later API / SSRF / JavaFaces weeks remain aligned to the current schedule. fileciteturn6file0

## 1) Freeze the scope

Do not modify the schedule. Only update the installer assets and build plans.

Keep these course-aligned lab themes in the installer:
- Week 1: environment + reconnaissance + DNS / zone transfer
- Week 2: enumeration, misconfiguration, outdated components
- Week 3–4: XSS and injection
- Week 5: file handling / traversal / insecure design
- Week 6–7: authentication and access control
- Week 8: reporting / midterm support
- Week 9–11: APIs
- Week 12: SSRF
- Week 13: advanced vulns / JavaFaces
- Week 14: defense / logging / crypto
- Week 15: final wrap-up

## 2) Prepare the asset tree

Your student bundle should look like this:

TAC425/
  tac425_setup.py
  requirements.txt
  assets/
    javafaces/
      vulnerable.war
    dns/
      named.conf
      named.conf.local
      db.tac425.net
    lab01/
      contact.html
    lab02/
      itp425.txt
    lab03/
      drupal8.txt
      webmin.txt
    lab04/
      clusterbomb.txt
    lab09/
      flag.txt
    lab10/
      tomcat-stuff.zip
      xml.bak
    lab11/
      robots.txt
    lab12/
      access.log

## 3) Build the JavaFaces WAR

Use your Kali build system or your Mac, but compile to Java 8 bytecode and test it in Tomcat before distribution.

Required artifact:
- `assets/javafaces/vulnerable.war`

You already validated that the WAR loads successfully in the browser.

## 4) Build the student bundle

Create one archive for students:
- `TAC425.zip`

Include:
- `tac425_setup.py`
- `requirements.txt`
- `assets/`

Exclude:
- `.venv/`
- logs
- generated labs
- state files

## 5) Test on a clean Kali VM

Use a fresh Kali install and require Docker only.
Do not preinstall Podman, Docker Desktop alternatives, or custom tooling.

Test flow:
1. Install Kali
2. Extract `TAC425.zip`
3. Run `python3 tac425_setup.py`
4. Start Week 1
5. Validate hints
6. Repeat installer once to test idempotency

## 6) Verify Week 1 DNS lab

Week 1 should include:
- a DNS / zone-transfer container
- a web container for the source-code clue

Validate:
- `dig axfr` works
- hidden zone records appear
- the clue is discoverable during lab work, not announced automatically

## 7) Verify JavaFaces

After installer completes:
- Week 13 should build and inject the WAR
- `/userSubscribe.faces` should load
- `javax.faces.ViewState` should appear
- `xml.bak` and `tomcat-stuff.zip` should be present in the expected paths

## 8) Verify health checks and recovery

Confirm:
- container health checks run
- unhealthy containers restart
- port conflicts are reported
- no destructive process killing occurs

## 9) Verify bridge hints

Bridge hints should be hidden and discoverable during labs.
Do not print them in scripts or installer output.

## 10) Final packaging

When the test VM passes:
- rebuild the zip
- upload to Brightspace
- keep the instructor source bundle private

## Script files

The current script set is:

- `tac425_setup.py` — installer and generator
- `requirements.txt` — intentionally minimal
- `validate_hints.sh` — generated validation script
