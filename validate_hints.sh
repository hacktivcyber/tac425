#!/usr/bin/env bash
set -u

echo "========================================"
echo "TAC425 Hint Validation Script"
echo "========================================"
echo ""

PASS=0
FAIL=0

check_file () {
    CONTAINER=$1
    PATH_INSIDE=$2

    echo "[CHECK] $CONTAINER -> $PATH_INSIDE"

    if docker exec "$CONTAINER" test -f "$PATH_INSIDE" >/dev/null 2>&1; then
        echo "[OK] Found"
        PASS=$((PASS+1))
    else
        echo "[FAIL] Missing"
        FAIL=$((FAIL+1))
    fi

    echo ""
}

# Week 1
check_file xxe_widget /var/www/html/contact.html
check_file dns_zone /etc/bind/db.tac425.net

# Week 2
check_file xxe_widget /var/www/html/itp425.txt
check_file drupal8 /var/www/html/drupal8.txt
check_file webmin /webmin/webmin.txt

# Week 4
check_file bwapp /var/www/html/hints/clusterbomb.txt

# Week 9
check_file ssrf /etc/flag.txt

# Week 10
check_file javafaces /var/backups/tomcat-stuff.zip
check_file javafaces /var/backups/xml.bak

# Week 11
check_file drupal9 /var/www/html/robots.txt

# Week 12
check_file mutillidae /var/log/apache2/access.log

echo "========================================"
echo "Validation Summary"
echo "========================================"
echo ""
echo "Passed: $PASS"
echo "Failed: $FAIL"
echo ""

if [ "$FAIL" -eq 0 ]; then
    echo "[SUCCESS] All hints validated"
else
    echo "[WARNING] Some hints missing"
fi
