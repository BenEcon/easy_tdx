FROM easy-tdx:activity-access-20261009
USER root
COPY --chown=10001:10001 auth.py /opt/easy_tdx/src/easy_tdx/web/routers/auth.py
COPY --chown=10001:10001 auth.py /usr/local/lib/python3.12/site-packages/easy_tdx/web/routers/auth.py
COPY --chown=10001:10001 dist/ /opt/easy_tdx/web-ui/dist/
COPY --chown=10001:10001 dist/ /usr/local/lib/python3.12/site-packages/easy_tdx/web/dist/
USER easytdx
LABEL org.easy-tdx.release="tracking-background-20261010"
