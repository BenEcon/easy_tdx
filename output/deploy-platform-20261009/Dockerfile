FROM easy-tdx:research-20261009
COPY --chown=10001:10001 patch/ /opt/easy_tdx/src/easy_tdx/
COPY --chown=10001:10001 patch/ /usr/local/lib/python3.12/site-packages/easy_tdx/
COPY --chown=10001:10001 dist/ /opt/easy_tdx/web-ui/dist/
COPY --chown=10001:10001 dist/ /usr/local/lib/python3.12/site-packages/easy_tdx/web/dist/
LABEL org.easy-tdx.release="platform-20261009" org.easy-tdx.source="826161d861fc38ca2ad76b91a3ac4032c273b86685d569469b64c0fe52c526f7"
