FROM easy-tdx:tracking-background-flat-20261010
USER root
COPY --chown=10001:10001 backend/ /opt/easy_tdx/src/easy_tdx/
COPY --chown=10001:10001 backend/ /usr/local/lib/python3.12/site-packages/easy_tdx/
COPY --chown=10001:10001 dist/ /opt/easy_tdx/web-ui/dist/
COPY --chown=10001:10001 dist/ /usr/local/lib/python3.12/site-packages/easy_tdx/web/dist/
USER easytdx
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/docs', timeout=4)" || exit 1
LABEL org.easy-tdx.release="tracking-history-signals-20261010"
