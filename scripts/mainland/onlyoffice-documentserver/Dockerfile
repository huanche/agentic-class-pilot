FROM docker.m.daocloud.io/onlyoffice/documentserver@sha256:ca17889f10b11141cc6441836aebdd2835cf3e1b49681b2fd6e155c94b7850b3

COPY apply-baseview-fix.py /tmp/apply-baseview-fix.py
RUN python3 /tmp/apply-baseview-fix.py && rm /tmp/apply-baseview-fix.py
