#!/usr/bin/env bash

mkdir -p tempwar/WEB-INF
echo "<html><body>TAC425 Test WAR</body></html>" > tempwar/index.html
cat > tempwar/WEB-INF/web.xml << EOF
<web-app xmlns="http://xmlns.jcp.org/xml/ns/javaee"
         version="3.1">
</web-app>
EOF
cd tempwar
zip -r ../vulnerable.war .
cd ..
file vulnerable.war
mkdir -p assets/javafaces
mv vulnerable.war assets/javafaces/
